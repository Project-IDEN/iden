"""The gate every resource-server route depends on."""

import time
import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request

from provider.authz.services.token_service import is_denylisted
from provider.core.audit import set_actor
from provider.core.config import settings
from provider.core.crypto import ACCESS_TOKEN_TYP, verify_jwt
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.shared.models import User


@dataclass
class AccessToken:
    subject: str
    client_id: str
    scopes: set[str]
    audience: list[str]
    jti: str
    acr: str | None
    amr: list[str]
    claims: dict


# The scope prefixes whose audience is derivable, because IDEN registers those
# APIs itself under exactly these names. A scope outside this set has an
# audience only its own registration knows, so guessing one would mint a
# nonexistent expectation and 401 every request that satisfied it.
SYSTEM_SCOPE_PREFIXES = frozenset({"admin", "entity", "developer", "biometric"})


def _audience_for(scope: str) -> str:
    """The audience a scope's API was registered under.

    IDEN's own APIs are named after the scope prefix (`admin:users:read` → the
    `admin` API), so it is derivable rather than repeated on every route.

    Refuses to guess otherwise: a route guarded by a scope outside the convention
    must pass `audience=`. Raising at import time turns a silent 401 on every
    request into a startup failure naming the scope.
    """
    prefix = scope.split(":")[0]
    if prefix not in SYSTEM_SCOPE_PREFIXES:
        raise ValueError(
            f"Cannot derive an audience from {scope!r}: {prefix!r} is not one of "
            f"IDEN's own APIs. Pass require_scope(..., audience=...) instead."
        )
    return f"{settings.iden_issuer}/{prefix}"


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")

    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": 'Bearer realm="iden"'},
        )
    return token


def require_scope(*required: str, audience: str | None = None):
    """Verify the access token and enforce scopes.

    401 means *authenticate again*; 403 means *authentication will not help*.
    Collapsing them would tell a client to retry a login that cannot fix
    anything.

    `audience` overrides the one derived from the first scope's prefix.
    """
    if audience is None and required:
        audience = _audience_for(required[0])

    async def dependency(request: Request, redis: RedisDep) -> AccessToken:
        raw = _bearer(request)

        try:
            # Only an access token opens a resource server. Before this check the
            # sole thing separating one from an ID token here was which claims it
            # happened to carry (RFC 9068 Section 4).
            claims = verify_jwt(raw, audience=audience, typ=ACCESS_TOKEN_TYP)
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {exc}",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            ) from exc

        if await is_denylisted(redis, claims["jti"]):
            raise HTTPException(
                status_code=401,
                detail="Token has been revoked.",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )

        granted = set(claims.get("scope", "").split())
        missing = set(required) - granted
        if missing:
            # RFC 6750 Section 3.1: `insufficient_scope`, naming what would satisfy it.
            # Without the header a client cannot tell this 403 from any other
            # without reading the prose.
            raise HTTPException(
                status_code=403,
                detail=f"Missing required scope: {' '.join(sorted(missing))}",
                headers={
                    "WWW-Authenticate": (
                        'Bearer error="insufficient_scope", '
                        f'error_description="Missing required scope", '
                        f'scope="{" ".join(sorted(required))}"'
                    )
                },
            )

        # A client_credentials token's subject is the client itself, not a
        # person, so only parse it as a user id when it is one.
        subject = claims["sub"]
        set_actor(
            request,
            user_id=uuid.UUID(subject) if _is_uuid(subject) else None,
            client_id=claims["client_id"],
        )

        aud = claims["aud"]
        return AccessToken(
            subject=claims["sub"],
            client_id=claims["client_id"],
            scopes=granted,
            audience=aud if isinstance(aud, list) else [aud],
            jti=claims["jti"],
            acr=claims.get("acr"),
            amr=claims.get("amr", []),
            claims=claims,
        )

    return dependency


# For routes that need an authenticated caller but gate on nothing further.
CurrentTokenDep = Annotated[AccessToken, Depends(require_scope())]


def require_fresh_auth(max_age: int = 300):
    """Demand a *recent* authentication, not merely a valid token.

    A valid token is not enough to change a password, an address or an
    authenticator: somebody holding a stolen one could take the account over.
    Requiring a login within `max_age` sends them back through the one step they
    cannot complete.

    Refused as RFC 9470's `insufficient_user_authentication` with the `max_age`
    that would satisfy it; `/authorize` accepts the same, which closes the loop.
    """

    async def dependency(request: Request, token: CurrentTokenDep) -> AccessToken:
        authenticated_at = token.claims.get("auth_time")
        age = time.time() - authenticated_at if authenticated_at else None

        if age is None or age > max_age:
            raise HTTPException(
                status_code=403,
                detail="This action needs a recent sign-in.",
                headers={
                    "WWW-Authenticate": (
                        'Bearer error="insufficient_user_authentication", '
                        f'error_description="A sign-in within {max_age}s is '
                        f'required", max_age={max_age}'
                    )
                },
            )
        return token

    return dependency


FreshTokenDep = Annotated[AccessToken, Depends(require_fresh_auth())]


async def get_current_user(token: CurrentTokenDep, session: DBSessionDep) -> User:
    """The person a route acts for, taken from the token's `sub`.

    No self-service route accepts a user id in a path or body, which removes a
    class of IDOR bugs by construction. In core because `/entity/*` and
    `/developer/*` both start here.
    """
    user = await session.get(User, uuid.UUID(token.subject))
    if user is None or not user.is_active:
        # The token is valid but its subject is gone or disabled. 401, not 404:
        # the caller needs to authenticate again, not look somewhere else.
        raise HTTPException(
            status_code=401,
            detail="This account is no longer active.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
