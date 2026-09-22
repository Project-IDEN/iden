"""Single sign-out: telling the applications a session reached that it is over.

OIDC Back-Channel Logout 1.0. Ending IDEN's own session is one Redis delete;
this is the half that makes "sign out" mean anything, because every relying party
keeps its own session and serves the user until told not to.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from provider.authz.services import session_store
from provider.core import audit
from provider.core.config import settings
from provider.core.crypto import LOGOUT_TOKEN_TYP, sign_jwt
from provider.core.logging import logger
from provider.shared.models import Client, RefreshToken

BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"

# Short on purpose: the user is waiting on a redirect, and a relying party that
# cannot answer in this window will find out at its next token exchange anyway.
DELIVERY_TIMEOUT = 5.0


def mint_logout_token(client: Client, *, subject: uuid.UUID, sid: str) -> str:
    """A logout token — OIDC Back-Channel Logout 1.0 Section 2.4.

    Three things keep it from being mistaken for an ID token: the `logout+jwt`
    header, the `events` claim, and the absence of `nonce` — without which it
    could be replayed as proof that somebody just authenticated.
    """
    issued_at = datetime.now(UTC)
    return sign_jwt(
        {
            "iss": settings.iden_issuer,
            "aud": client.client_id,
            "iat": int(issued_at.timestamp()),
            "exp": int((issued_at + timedelta(minutes=2)).timestamp()),
            "jti": str(uuid.uuid7()),
            "sub": str(subject),
            "sid": sid,
            "events": {BACKCHANNEL_LOGOUT_EVENT: {}},
        },
        typ=LOGOUT_TOKEN_TYP,
    )


async def _deliver(http: httpx.AsyncClient, client: Client, token: str) -> int:
    """POST one logout token. Returns the status, or 0 if it never arrived.

    `InvalidURL` is not a subclass of `HTTPError`, so an unparseable stored URI
    would escape this handler and fail the whole sign-out rather than one
    delivery. Best effort has to hold for a bad URI as much as a dead host.
    """
    try:
        response = await http.post(
            client.backchannel_logout_uri or "",
            data={"logout_token": token},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        return response.status_code
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        logger.warning(
            "Back-channel logout failed",
            client_id=client.client_id,
            error=str(exc),
        )
        return 0


async def notify(
    session: AsyncSession,
    *,
    client_ids: set[str],
    subject: uuid.UUID,
    sid: str,
) -> None:
    """Tell every client that registered a back-channel URI that `sid` is over.

    Best effort, concurrently, never retried into a queue: an unreachable party
    re-validates at its next token exchange, and a durable queue is a dependency
    this project does not otherwise need. The record is not optional though —
    every attempt is audited with its outcome.
    """
    if not client_ids:
        return

    clients = list(
        await session.scalars(
            select(Client).where(
                Client.client_id.in_(client_ids),
                Client.backchannel_logout_uri.is_not(None),
            )
        )
    )
    if not clients:
        return

    async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT) as http:
        results = await asyncio.gather(
            *(
                _deliver(
                    http, client, mint_logout_token(client, subject=subject, sid=sid)
                )
                for client in clients
            )
        )

    for client, status in zip(clients, results, strict=True):
        await audit.record(
            session,
            action="POST backchannel_logout",
            status_code=status,
            target=client.client_id,
            actor_user_id=subject,
            detail={"sid": sid, "uri": client.backchannel_logout_uri},
        )


async def end_session(
    session: AsyncSession, redis: Redis, login_session: session_store.Session
) -> None:
    """End one browser session completely: revoke what it issued, tell the
    applications it reached, then delete it.

    In that order because the record of which applications it reached lives with
    the session. Deleting alone ends nothing: each application keeps its own
    session, and its refresh token keeps working.
    """
    sid = login_session.public_id
    client_ids = await session_store.clients_for(redis, login_session.id)

    await revoke_session_tokens(session, sid)
    await notify(session, client_ids=client_ids, subject=login_session.user_id, sid=sid)
    await session.commit()
    await session_store.delete(redis, login_session.id)


async def end_all_sessions(
    session: AsyncSession, redis: Redis, user_id: uuid.UUID, *, keep: str | None = None
) -> int:
    """End every browser session this person has, except `keep` — the cookie
    of the one making the change, when there is one. Returns how many ended.

    Each ends as `end_session` ends one, bar the refresh tokens: those are the
    caller's to revoke by user, since one outlives the session that issued it.
    """
    kept = session_store.public_id_of(keep) if keep else None
    ended = 0

    for live in await session_store.list_for_user(redis, user_id):
        if live.id == kept:
            continue
        client_ids = await session_store.clients_for_public_id(redis, live.id)
        await notify(session, client_ids=client_ids, subject=user_id, sid=live.id)
        await session_store.delete_by_public_id(redis, user_id, live.id)
        ended += 1

    return ended


async def revoke_session_tokens(session: AsyncSession, sid: str) -> None:
    """Revoke every refresh token the session produced.

    Otherwise each client could mint fresh access tokens indefinitely from a
    refresh token it already holds. Access tokens already issued run to their
    expiry, which is the trade the short TTL exists to make.
    """
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.sid == sid, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
