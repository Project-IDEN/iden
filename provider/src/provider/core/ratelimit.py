"""Fixed-window rate limiting, in Redis.

Argon2 makes a password guess expensive for *the server*, so `/api/v1/auth/login`
is both a brute-force target and a way to exhaust its CPU.

Per-route rather than global middleware: a blanket cap would be either too loose
to stop credential stuffing or too tight for a dashboard. A global cap against
crude flooding belongs in the reverse proxy, which can refuse a connection before
Python is involved.

Fixed windows, not sliding — one counter and an expiry. An attacker can spend a
full allowance at the end of one window and again at the start of the next, which
for a handful of attempts per minute changes nothing.
"""

from fastapi import Request

from provider.core.config import settings
from provider.core.errors import RateLimitedError
from provider.core.redis import RedisDep


def client_ip(request: Request) -> str:
    """The address to attribute an attempt to.

    The socket peer, unless that peer is a trusted proxy —
    `IDEN_FORWARDED_ALLOW_IPS` draws the line and uvicorn applies it before this
    runs, so what arrives here is already the answer. Trust nothing and every
    caller behind a proxy shares one bucket; trust everything and a header
    decides who they are counted as.
    """
    return request.client.host if request.client else "unknown"


async def hit(redis, bucket: str, identity: str, *, limit: int, window: int) -> None:
    """Count one attempt against `bucket:identity`, or refuse it.

    Raises `RateLimitedError` with the seconds remaining in the window.
    """
    if not settings.iden_rate_limit_enabled:
        return

    key = f"ratelimit:{bucket}:{identity}"
    count = await redis.incr(key)

    if count == 1:
        await redis.expire(key, window)
        return

    if count > limit:
        # The window's TTL is exactly when the counter resets. -1 means no
        # expiry, where reporting the whole window is the safe answer.
        ttl = await redis.ttl(key)
        raise RateLimitedError(retry_after=ttl if ttl and ttl > 0 else window)


def limit_by_ip(bucket: str, *, limit: int, window: int):
    """A dependency that limits a route by caller address.

    A dependency rather than middleware so it runs *after* routing, which keeps
    the refusal in the audit log — a burst of them is what a reviewer wants.
    """

    async def dependency(request: Request, redis: RedisDep) -> None:
        await hit(redis, bucket, client_ip(request), limit=limit, window=window)

    return dependency


async def guard(redis, bucket: str, identity: str, *, limit: int, window: int) -> None:
    """Refuse when this identity has already failed too often.

    Counts **failures only**, paired with `record_failure` and `clear`. Limiting
    all attempts against one account is a way to lock its owner out: an attacker
    simply burns the allowance. Clearing on success keeps the person who knows
    the password able to sign in.
    """
    if not settings.iden_rate_limit_enabled:
        return

    key = f"ratelimit:{bucket}:{identity}"
    count = int(await redis.get(key) or 0)
    if count >= limit:
        ttl = await redis.ttl(key)
        raise RateLimitedError(retry_after=ttl if ttl and ttl > 0 else window)


async def record_failure(redis, bucket: str, identity: str, *, window: int) -> None:
    key = f"ratelimit:{bucket}:{identity}"
    if await redis.incr(key) == 1:
        await redis.expire(key, window)


async def clear(redis, bucket: str, identity: str) -> None:
    await redis.delete(f"ratelimit:{bucket}:{identity}")


# Ceilings on abuse, not targets for ordinary use. Per address, and generous,
# because an office or a campus is one address to us.
LOGIN_PER_IP = limit_by_ip("login-ip", limit=30, window=300)
TOTP_PER_IP = limit_by_ip("totp-ip", limit=20, window=300)
RESET_PER_IP = limit_by_ip("reset-ip", limit=10, window=3600)

# The three endpoints that verify a client secret, which is argon2: 64 MiB and
# real CPU per attempt, spent before the caller has proved anything. Separate
# buckets so spending one endpoint's allowance does not close the others.
TOKEN_PER_IP = limit_by_ip("token-ip", limit=120, window=60)
REVOKE_PER_IP = limit_by_ip("revoke-ip", limit=120, window=60)
INTROSPECT_PER_IP = limit_by_ip("introspect-ip", limit=120, window=60)

# `/authorize` writes a challenge into Redis for anyone who asks, which lives
# IDEN_CHALLENGE_TTL whether the interaction happens or not; a flood evicts the
# sessions beside them. Matched to the token endpoint, since every authorization
# is followed by an exchange.
AUTHORIZE_PER_IP = limit_by_ip("authorize-ip", limit=120, window=60)

# Failures against one account, from anywhere — the limit that stops credential
# stuffing, which rotates addresses and not the target.
LOGIN_FAILURES = {"bucket": "login-fail", "limit": 8, "window": 900}
TOTP_FAILURES = {"bucket": "totp-fail", "limit": 8, "window": 900}

# So the endpoint cannot be used to bury someone in mail they did not ask for.
RESET_PER_ADDRESS = {"bucket": "reset-addr", "limit": 3, "window": 3600}
