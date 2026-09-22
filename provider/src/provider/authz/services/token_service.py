"""Minting and lifecycle for every token IDEN issues."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from provider.core.config import settings
from provider.core.crypto import ACCESS_TOKEN_TYP, sign_jwt
from provider.core.security import generate_token, hash_token
from provider.shared import avatars
from provider.shared.models import Client, RefreshToken, ResourceApi, Scope, User


def now() -> datetime:
    return datetime.now(UTC)


async def audiences_for(session: AsyncSession, values: set[str]) -> list[str]:
    """The `aud` of an access token is the audience of every API owning a
    granted scope, so a resource server can reject tokens minted for someone
    else (RFC 9068 Section 3).

    Falls back to the issuer when only OIDC scopes were granted, where the token
    reaches no other API.
    """
    if not values:
        return [settings.iden_issuer]

    rows = await session.scalars(
        select(ResourceApi.audience)
        .join(Scope, Scope.api_id == ResourceApi.id)
        .where(Scope.value.in_(values))
        .distinct()
    )
    return sorted(rows) or [settings.iden_issuer]


async def mint_access_token(
    session: AsyncSession,
    *,
    subject: str,
    client: Client,
    scopes: set[str],
    acr: str | None = None,
    amr: list[str] | None = None,
    authenticated_at: datetime | None = None,
) -> tuple[str, str, int]:
    """Returns (token, jti, expires_in)."""
    issued_at = now()
    jti = str(uuid.uuid7())
    audience = await audiences_for(session, scopes)

    claims = {
        "iss": settings.iden_issuer,
        "sub": subject,
        "aud": audience,
        "client_id": client.client_id,
        "scope": " ".join(sorted(scopes)),
        "jti": jti,
        "iat": int(issued_at.timestamp()),
        "exp": int(
            (issued_at + timedelta(seconds=settings.iden_access_token_ttl)).timestamp()
        ),
    }
    # Absent for client_credentials: no person authenticated, so there is no
    # assurance level to report.
    if acr:
        claims["acr"] = acr
    if amr:
        claims["amr"] = amr
    # RFC 9068 Section 2.2.1. A resource server cannot demand a *recent* sign-in for a
    # sensitive action without knowing when the sign-in happened, and it only
    # ever sees the access token — the ID token belongs to the client.
    if authenticated_at:
        claims["auth_time"] = int(authenticated_at.timestamp())

    return sign_jwt(claims, typ=ACCESS_TOKEN_TYP), jti, settings.iden_access_token_ttl


def mint_id_token(
    user: User,
    client: Client,
    *,
    scopes: set[str],
    acr: str,
    amr: list[str],
    authenticated_at: datetime,
    sid: str | None = None,
    nonce: str | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """The ID token describes the authentication event to the client that asked
    for it — hence `aud` is the client, not an API (OIDC Core Section 2)."""
    issued_at = now()
    claims = {
        "iss": settings.iden_issuer,
        "sub": str(user.id),
        "aud": client.client_id,
        "iat": int(issued_at.timestamp()),
        "exp": int(
            (issued_at + timedelta(seconds=settings.iden_id_token_ttl)).timestamp()
        ),
        "auth_time": int(authenticated_at.timestamp()),
        "acr": acr,
        "amr": amr,
    }
    # Names the browser session, so a back-channel logout can tell this client
    # which of its sessions to end. Absent on tokens issued before sessions
    # were recorded.
    if sid:
        claims["sid"] = sid
    # Organization-defined fields, already filtered to the scopes this client
    # holds. Safe to merge wholesale: the OIDC reserved names are refused when
    # a field is defined, so nothing here can shadow `sub` or `iss`.
    claims |= extra_claims or {}

    # Binds the token to the client's authorization request, defeating replay.
    if nonce:
        claims["nonce"] = nonce

    claims |= identity_claims(user, scopes)
    return sign_jwt(claims)


def identity_claims(user: User, scopes: set[str]) -> dict[str, Any]:
    """Claims released by scope — OIDC Core Section 5.4. Shared with /userinfo so the
    two can never disagree."""
    claims: dict[str, Any] = {}

    if "profile" in scopes:
        claims["name"] = user.display_name
        claims["preferred_username"] = user.username
        claims["picture"] = avatars.public_url(user.picture_key)

    if "email" in scopes:
        claims["email"] = user.email
        claims["email_verified"] = user.email_verified_at is not None

    return claims


async def issue_refresh_token(
    session: AsyncSession,
    *,
    client: Client,
    user: User,
    scope: str,
    acr: str,
    amr: list[str],
    authenticated_at: datetime,
    sid: str | None = None,
    family_id: uuid.UUID | None = None,
) -> tuple[str, RefreshToken]:
    token = generate_token()
    record = RefreshToken(
        token_hash=hash_token(token),
        client_id=client.id,
        user_id=user.id,
        scope=scope,
        acr=acr,
        amr=amr,
        authenticated_at=authenticated_at,
        sid=sid,
        family_id=family_id or uuid.uuid7(),
        expires_at=now() + timedelta(seconds=settings.iden_refresh_token_ttl),
    )
    session.add(record)
    await session.flush()
    return token, record


def _replay_key(token: str) -> str:
    return f"refresh_replay:{hash_token(token)}"


def rotation_lock(redis: Redis, token: str):
    """Serialise exchanges of one refresh token across every worker.

    The replay window alone only helps a caller arriving after the first exchange
    finished; two tabs firing at the same instant both find no replay, both
    rotate, and the loser is treated as theft. Held around the replay check *and*
    the rotation, so the loser waits and finds the winner's answer.

    Keyed by the token rather than the family: two tokens of one family arriving
    together is the case detection is for.
    """
    return redis.lock(
        f"refresh_lock:{hash_token(token)}",
        # Ceilings, not expected durations: the lock is released in a finally.
        # They only matter if a worker dies mid-exchange, and then the next
        # caller should get on with it rather than inherit the outage.
        timeout=10,
        blocking_timeout=5,
    )


async def remember_rotation(
    redis: Redis, token: str, *, client_id: str, response: dict, expires_at: datetime
) -> None:
    """Remember what a refresh token was exchanged for, briefly.

    Rotation is what makes theft detectable, but two tabs refreshing at once — or
    a retried request — present the same token twice for honest reasons and look
    exactly like theft. Replaying the original answer serves both.

    Only the presenting client can collect it, and only for a few seconds; beyond
    that the second use is theft again.
    """
    if settings.iden_refresh_grace_period <= 0:
        return

    payload = json.dumps(
        {
            "client_id": client_id,
            "expires_at": expires_at.timestamp(),
            "response": response,
        }
    )
    await redis.set(_replay_key(token), payload, ex=settings.iden_refresh_grace_period)


async def replayed_rotation(redis: Redis, token: str, *, client_id: str) -> dict | None:
    """The answer this token already received, if it is still within the window.

    Returns None for a token that has not been spent, so this is safe to ask
    before doing any work.
    """
    raw = await redis.get(_replay_key(token))
    if raw is None:
        return None

    remembered = json.loads(raw)
    # A different client holding the same token is not a retry — it is the case
    # rotation exists to catch, so it falls through to reuse detection.
    if remembered["client_id"] != client_id:
        return None

    response = remembered["response"]
    # The access token is the one that was minted, so it expires when it always
    # would have. Repeating the original `expires_in` would overstate its life
    # by however long the replay window has been running.
    remaining = remembered["expires_at"] - now().timestamp()
    response["expires_in"] = max(1, int(remaining))
    return response


class RefreshTokenReuse(Exception):
    """A rotated or revoked token was presented again — assume it was stolen."""


async def consume_refresh_token(
    session: AsyncSession, token: str
) -> RefreshToken | None:
    """Validate a refresh token for rotation.

    None when unknown or expired. `RefreshTokenReuse` when an already-rotated or
    revoked token is presented again, having revoked the family first: a second
    use means two parties hold it and only one is legitimate.
    """
    # Locked for the same reason as an authorization code: without it two
    # concurrent refreshes both see an unrotated token, both succeed, and reuse
    # detection never fires.
    record = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(token))
        .with_for_update()
    )
    if record is None:
        return None

    if record.revoked_at is not None or record.rotated_to_id is not None:
        await revoke_family(session, record.family_id)
        raise RefreshTokenReuse

    if record.expires_at <= now():
        return None

    return record


async def revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now())
    )


def _denylist_key(jti: str) -> str:
    return f"denylist:{jti}"


async def denylist_access_token(redis: Redis, jti: str, expires_at: int) -> None:
    """Revoke an access token before it expires.

    Access tokens are stateless, so revocation means remembering the few that
    died early, and only until they would have expired anyway.
    """
    ttl = expires_at - int(now().timestamp())
    if ttl > 0:
        await redis.set(_denylist_key(jti), "1", ex=ttl)


async def is_denylisted(redis: Redis, jti: str) -> bool:
    return await redis.exists(_denylist_key(jti)) == 1
