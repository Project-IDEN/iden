"""Enrolment tickets: how a kiosk learns whose face is in front of it.

The person signs in to the dashboard and asks for one; it appears as a QR code,
which they show to the kiosk. The kiosk's own credential grants nothing on its
own — without a ticket, there is nobody it may enrol. A ticket names one person,
lasts minutes, and is gone once a face is enrolled with it.
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis

from provider.core.config import settings
from provider.core.security import generate_token, hash_token

# Each capture attempt at the kiosk counts; poor light should not end the visit,
# but a ticket must not be a way to try forever.
MAX_ATTEMPTS = 5


def _key(ticket: str) -> str:
    return f"face-ticket:{hash_token(ticket)}"


def _attempts_key(key: str) -> str:
    # Its own key, so counting an attempt is one INCR: read-modify-write on the
    # ticket let concurrent captures each see the same count. Never deleted, only
    # left to expire: a capture already past the ticket check would INCR a deleted
    # count back to 1, and get another try with no expiry on it.
    return f"{key}:attempts"


def _user_key(user_id: UUID) -> str:
    return f"face-ticket-user:{user_id}"


async def issue(redis: Redis, user_id: UUID) -> tuple[str, datetime]:
    """A new ticket, retiring any this person asked for before."""
    ttl = settings.iden_face_ticket_ttl
    if previous := await redis.get(_user_key(user_id)):
        await redis.delete(previous)

    ticket = generate_token()
    key = _key(ticket)
    await redis.set(key, json.dumps({"user_id": str(user_id)}), ex=ttl)
    await redis.set(_attempts_key(key), 0, ex=ttl)
    await redis.set(_user_key(user_id), key, ex=ttl)
    return ticket, datetime.now(UTC) + timedelta(seconds=ttl)


async def holder(
    redis: Redis, ticket: str, *, attempt: bool = False
) -> tuple[UUID, int] | None:
    """Whose ticket this is and how many attempts it has left, or None.
    `attempt` counts one try against it."""
    key = _key(ticket)
    raw = await redis.get(key)
    if raw is None:
        return None

    user_id = UUID(json.loads(raw)["user_id"])
    if attempt:
        attempts = await redis.incr(_attempts_key(key))
        if attempts > MAX_ATTEMPTS:
            await redis.delete(key)
            return None
    else:
        attempts = int(await redis.get(_attempts_key(key)) or 0)
    return user_id, MAX_ATTEMPTS - attempts


async def spend(redis: Redis, ticket: str, user_id: UUID) -> None:
    await redis.delete(_key(ticket), _user_key(user_id))
