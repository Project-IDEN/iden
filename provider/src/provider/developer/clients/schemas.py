"""What a developer is allowed to say about their own application.

The fields absent here are the point of the module. `allowedGrants`,
`skipConsent`, `isSystem`, `clientId`, and both scope assignments are decided by
the server, not by the registrant — see `service.py` for why each one is.
"""

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator

from provider.core.schemas import CamelCaseBaseModel

MAX_URIS = 5
MAX_URI_LENGTH = 2048

# RFC 8252 Section 7.3: the only hosts an `http` redirect may name. A native app
# receives its callback on a loopback port; anything else must be TLS.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

REDIRECT_URI_RULES = (
    "`https://` anywhere; `http://` only on localhost or 127.0.0.1; or a "
    "reverse-DNS private-use scheme for a native app, e.g. "
    "`com.example.app:/callback` (RFC 8252). Printable ASCII only, and no "
    "wildcards, fragments, or credentials in the authority — the value is "
    "matched **exactly** at "
    "`/authorize`, so register the URI your app actually sends."
)


def _validate_uri(value: str) -> str:
    if not value or len(value) > MAX_URI_LENGTH:
        raise ValueError(f"redirect URI must be 1-{MAX_URI_LENGTH} characters")

    # Every character must be printable US-ASCII, which is what a URI is made
    # of (RFC 3986 Section 2) — anything else is percent-encoded. Three things
    # ride on this one rule:
    #
    #   - `urlsplit` silently removes tab and newline (WHATWG URL), so a URI
    #     containing them would be validated as one string and stored as another;
    #   - a raw NUL is not valid UTF-8 to PostgreSQL, so it would leave
    #     validation as a 500 rather than a 422;
    #   - a non-ASCII host is sent by a client library in punycode, so it could
    #     never match what was registered — while reading, to a human, like the
    #     domain it imitates.
    if any(character < "!" or character > "~" for character in value):
        raise ValueError(
            f"redirect URI must be printable ASCII; percent-encode anything "
            f"else: {value!r}"
        )

    if "*" in value:
        raise ValueError(f"redirect URI must not contain a wildcard: {value}")

    parsed = urlsplit(value)

    if not parsed.scheme:
        raise ValueError(f"redirect URI must be absolute: {value}")

    # RFC 6749 Section 3.1.2. The fragment is where an implicit-flow response
    # goes; a registered one cannot be matched and only confuses the comparison.
    if parsed.fragment or value.endswith("#"):
        raise ValueError(f"redirect URI must not contain a fragment: {value}")

    if "@" in parsed.netloc:
        raise ValueError(
            f"redirect URI must not contain credentials in the authority: {value}"
        )

    if parsed.scheme == "https":
        if not parsed.hostname:
            raise ValueError(f"https redirect URI needs a host: {value}")
    elif parsed.scheme == "http":
        if parsed.hostname not in LOOPBACK_HOSTS:
            raise ValueError(
                f"http is allowed only on localhost or 127.0.0.1 — use https: {value}"
            )
    elif "." not in parsed.scheme:
        # RFC 8252 Section 7.1: a native app's private-use scheme is a domain
        # name the developer controls, reversed. Requiring the dot is also what
        # keeps `javascript:` and `data:` out.
        raise ValueError(
            f"a custom scheme must be reverse-DNS, e.g. com.example.app: {value}"
        )

    return value


def _validate_uris(values: list[str]) -> list[str]:
    if len(values) > MAX_URIS:
        raise ValueError(f"at most {MAX_URIS} URIs")
    return [_validate_uri(value) for value in values]


class ApplicationCreate(CamelCaseBaseModel):
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Shown to people on the consent screen. Name it after the app.",
    )
    client_type: Literal["public", "confidential"] = Field(
        description=(
            "`public` — a browser or mobile app that cannot keep a secret; PKCE "
            "proves it. `confidential` — a server-side app; gets a secret."
        )
    )
    redirect_uris: list[str] = Field(
        min_length=1,
        description=f"Where `/authorize` may send the browser back. {REDIRECT_URI_RULES}",
    )
    post_logout_redirect_uris: list[str] = Field(
        default_factory=list,
        description="Where `/oauth2/logout` may return to. Same rules as `redirectUris`.",
    )

    @field_validator("redirect_uris", "post_logout_redirect_uris")
    @classmethod
    def check_uris(cls, values: list[str]) -> list[str]:
        return _validate_uris(values)


class ApplicationUpdate(CamelCaseBaseModel):
    """Every field is optional; the ones left out are untouched.

    `clientType` is absent on purpose — it decides whether a secret exists at
    all, and flipping it would either orphan a live secret or silently leave an
    app that believes it has one.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    redirect_uris: list[str] | None = Field(default=None, min_length=1)
    post_logout_redirect_uris: list[str] | None = None

    @field_validator("redirect_uris", "post_logout_redirect_uris")
    @classmethod
    def check_uris(cls, values: list[str] | None) -> list[str] | None:
        return None if values is None else _validate_uris(values)


class ApplicationResponse(CamelCaseBaseModel):
    id: UUID
    client_id: str = Field(
        description="Generated by IDEN. This is what your app sends at `/authorize`."
    )
    name: str
    client_type: Literal["public", "confidential"]
    allowed_grants: list[str] = Field(
        description="Fixed: the authorization code flow, with refresh."
    )
    redirect_uris: list[str]
    post_logout_redirect_uris: list[str]
    grantable_scopes: list[str] = Field(
        description=(
            "Everything this application may put in its `scope` parameter. The "
            "OpenID Connect scopes are always there; anything beyond them was "
            "attached by an administrator."
        )
    )
    has_secret: bool = Field(
        description="Whether a client secret exists. Its value is never readable."
    )
    created_at: datetime


class ApplicationCreated(ApplicationResponse):
    client_secret: str | None = Field(
        default=None,
        description=(
            "Shown **once**, here. It is argon2-hashed on the way in and cannot "
            "be recovered — only rotated. Null for a public application."
        ),
    )


class ApplicationList(CamelCaseBaseModel):
    applications: list[ApplicationResponse]
    remaining: int = Field(
        description="How many more applications this account may register."
    )


class SecretRotated(CamelCaseBaseModel):
    client_secret: str = Field(
        description="Shown once. The previous secret stops working now."
    )
