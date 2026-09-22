"""Validation for the URIs a client registers.

Shared because there are two ways to register one — an administrator through
`/admin/clients`, a developer through `/developer/clients` — and a rule that holds
on one surface and not the other is not a rule.

A `redirect_uri` is where an authorization code is delivered and a
`backchannelLogoutUri` is a URL the provider itself fetches, so a sloppy value in
either becomes somebody else's problem.
"""

from urllib.parse import urlencode, urlsplit

MAX_URI_LENGTH = 2048

# RFC 8252 Section 7.3: the only hosts an `http` redirect may name. A native app
# receives its callback on a loopback port; anything else must be TLS, because
# the code travels in the clear otherwise.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

REDIRECT_URI_RULES = (
    "`https://` anywhere; `http://` only on localhost or 127.0.0.1; or a "
    "reverse-DNS private-use scheme for a native app, e.g. "
    "`com.example.app:/callback` (RFC 8252). Printable ASCII only, and no "
    "wildcards, fragments, or credentials in the authority — the value is "
    "matched **exactly** at `/authorize`, so register the URI your app actually "
    "sends."
)


def validate_redirect_uri(value: str) -> str:
    """One redirect or post-logout URI, or `ValueError` saying what is wrong."""
    if not value or len(value) > MAX_URI_LENGTH:
        raise ValueError(f"redirect URI must be 1-{MAX_URI_LENGTH} characters")

    # Printable US-ASCII is what a URI is made of (RFC 3986 Section 2). Three
    # things ride on it: `urlsplit` silently strips tab and newline, so such a URI
    # would be validated as one string and stored as another; a raw NUL is not
    # valid UTF-8 to PostgreSQL, giving a 500 instead of a 422; and a non-ASCII
    # host arrives in punycode, so it could never match while reading to a human
    # like the domain it imitates.
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

    # RFC 6749 Section 3.1.2: the fragment is where an implicit-flow response
    # goes, and a registered one cannot be matched.
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
        # RFC 8252 Section 7.1: a reversed domain the developer controls.
        # Requiring the dot is also what keeps `javascript:` and `data:` out.
        raise ValueError(
            f"a custom scheme must be reverse-DNS, e.g. com.example.app: {value}"
        )

    return value


def validate_redirect_uris(values: list[str], *, maximum: int) -> list[str]:
    if len(values) > maximum:
        raise ValueError(f"at most {maximum} URIs")
    return [validate_redirect_uri(value) for value in values]


BACKCHANNEL_URI_RULES = (
    "Absolute `https://`, or `http://` on localhost for local development. No "
    "fragment, and no credentials in the authority."
)


def validate_backchannel_uri(value: str | None) -> str | None:
    """A URL the provider itself will POST to when a session ends.

    Held to a scheme IDEN can speak: a value httpx cannot parse raises
    `InvalidURL`, which is not an `httpx.HTTPError` and so escapes the handler
    that keeps one unreachable client from failing a sign-out.

    That it may name an address inside the deployment's own network is not
    checked and cannot usefully be — a back-channel URI is by definition a host
    IDEN reaches, and most are internal. It is an audited administrator's call.
    """
    if value is None or value == "":
        return None

    if len(value) > MAX_URI_LENGTH:
        raise ValueError(
            f"backchannel logout URI must be at most {MAX_URI_LENGTH} characters"
        )

    if any(character < "!" or character > "~" for character in value):
        raise ValueError("backchannel logout URI must be printable ASCII")

    parsed = urlsplit(value)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("backchannel logout URI must be http or https")

    if not parsed.hostname:
        raise ValueError("backchannel logout URI needs a host")

    if parsed.scheme == "http" and parsed.hostname not in LOOPBACK_HOSTS:
        raise ValueError(
            "http is allowed only on localhost or 127.0.0.1 — use https: "
            "a logout token names the person who signed out"
        )

    if parsed.fragment or "@" in parsed.netloc:
        raise ValueError(
            "backchannel logout URI must not contain a fragment or credentials"
        )

    return value


def redirect_with(uri: str, params: dict[str, str]) -> str:
    """`uri` with `params` added to its query — RFC 6749 Section 4.1.2.

    The separator follows what is already there. RFC 6749 Section 3.1.2 permits a
    registered redirect URI to carry a query of its own, and a hard-coded `?`
    turns `...cb?tenant=acme` into `...?tenant=acme?code=...` — one parameter
    named `tenant`, with no `code`, `state` or `iss` the client can read.
    """
    return f"{uri}{'&' if urlsplit(uri).query else '?'}{urlencode(params)}"
