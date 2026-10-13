"""Pairing codes: how a freshly installed kiosk becomes a registered one.

An administrator registers a kiosk in the dashboard and is shown a short code;
the device sends it once and receives its own client secret. The code is the
only credential a new device has, so it is single use, lasts minutes, and a new
one retires the last.
"""

import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis

from provider.core.config import settings
from provider.core.security import hash_token

# No 0/O, 1/I/L, or U: the code is read off a screen and may be typed on one.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
LENGTH = 8


def _key(code: str) -> str:
    return f"kiosk-pairing:{hash_token(normalise(code))}"


def _kiosk_key(kiosk_id: UUID) -> str:
    return f"kiosk-pairing-kiosk:{kiosk_id}"


def normalise(code: str) -> str:
    return "".join(c for c in code.upper() if c.isalnum())


def display(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


async def issue(redis: Redis, kiosk_id: UUID) -> tuple[str, datetime]:
    """A new code for this kiosk, retiring any issued before."""
    ttl = settings.iden_kiosk_pairing_ttl
    if previous := await redis.get(_kiosk_key(kiosk_id)):
        await redis.delete(previous)

    code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    await redis.set(_key(code), json.dumps({"kiosk_id": str(kiosk_id)}), ex=ttl)
    await redis.set(_kiosk_key(kiosk_id), _key(code), ex=ttl)
    return display(code), datetime.now(UTC) + timedelta(seconds=ttl)


async def consume(redis: Redis, code: str) -> UUID | None:
    """The kiosk this code pairs, or None. Either way the code is gone."""
    raw = await redis.getdel(_key(code))
    if raw is None:
        return None
    kiosk_id = UUID(json.loads(raw)["kiosk_id"])
    await redis.delete(_kiosk_key(kiosk_id))
    return kiosk_id
