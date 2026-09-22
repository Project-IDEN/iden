"""Validation for the URIs a client registers.

Shared because there are two ways to register a client — an administrator
through `/admin/clients`, a developer through `/developer/clients` — and a rule
that holds on one surface and not the other is not a rule. The admin surface had
only `"://" in value`, and its update body had no check at all, so `javascript:`,
a bare path, and a URI carrying credentials in its authority all went in.

Nothing here is a matter of taste. A `redirect_uri` is where an authorization
code is delivered and a `backchannelLogoutUri` is a URL the provider itself
fetches, so both are places where a sloppy value becomes someone else's problem.
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

    Held to a scheme IDEN can actually speak, which the column was not: a value
    httpx cannot parse raised `InvalidURL` from inside logout delivery — and
    `InvalidURL` is not an `httpx.HTTPError`, so it escaped the handler that
    exists to keep one unreachable client from failing a sign-out, and every
    logout touching this client answered 500 instead.

    That it may name an address inside the deployment's own network is not
    checked, and cannot usefully be: a back-channel URI is by definition a host
    IDEN reaches, and most of them are internal. It is an administrator's
    decision, made with `admin:clients:write`, and it is audited.
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

    The separator follows what is already there. Every caller used to hard-code
    `?`, and RFC 6749 Section 3.1.2 explicitly permits a registered redirect URI
    to carry a query of its own: `https://app.example/cb?tenant=acme` then became
    `...?tenant=acme?code=...`, which is one query parameter named `tenant` whose
    value happens to contain the word "code". The client saw no `code`, no
    `state` and no `iss` — so it could not complete the flow and could not
    validate the response it did get.
    """
    return f"{uri}{'&' if urlsplit(uri).query else '?'}{urlencode(params)}"
