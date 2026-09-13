"""Single sign-out: telling the applications a session reached that it is over.

OIDC Back-Channel Logout 1.0. Ending IDEN's own session is the easy half — it
is one Redis delete. The half that makes "sign out" mean anything is this one,
because every relying party keeps its own session and will happily go on
serving the user until something tells it not to.
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

    Three rules keep it from being mistaken for an ID token, and none is
    stylistic: the `logout+jwt` header says what it is, `events` marks what it
    is for, and the **absence of `nonce`** stops it being replayed as proof
    that someone just authenticated.
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
    """POST one logout token. Returns the status, or 0 if it never arrived."""
    try:
        response = await http.post(
            client.backchannel_logout_uri or "",
            data={"logout_token": token},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        return response.status_code
    except httpx.HTTPError as exc:
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

    Best effort, concurrently, and never retried into a queue: a relying party
    that was unreachable re-validates at its next token exchange, and a durable
    job queue is a dependency this project does not otherwise need. What is not
    optional is the record — every attempt is audited with its outcome, so a
    sign-out that did not reach somewhere is visible afterwards.
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
    the session and goes when it does. Deleting alone ends nothing that matters —
    every application keeps its own session, and its refresh token keeps working.
    """
    sid = login_session.public_id
    client_ids = await session_store.clients_for(redis, login_session.id)

    await revoke_session_tokens(session, sid)
    await notify(session, client_ids=client_ids, subject=login_session.user_id, sid=sid)
    await session.commit()
    await session_store.delete(redis, login_session.id)


async def revoke_session_tokens(session: AsyncSession, sid: str) -> None:
    """Revoke every refresh token the session produced.

    Without this "signed out" would leave each client able to mint fresh access
    tokens indefinitely from a refresh token it already holds, which is not
    what anyone means by signing out. Access tokens already issued still run to
    their expiry — that is the trade the short TTL exists to make.
    """
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.sid == sid, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
