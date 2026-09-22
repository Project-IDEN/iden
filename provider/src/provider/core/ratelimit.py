"""Fixed-window rate limiting, in Redis.

Argon2 makes a password guess expensive for *the server*, not for the attacker.
Without a limit, `/api/v1/auth/login` is both a brute-force target and a way to
exhaust the machine's CPU with a few hundred requests.

**Deliberately per-route rather than global middleware.** A blanket cap in
front of every endpoint would either be too loose to stop credential stuffing
or too tight for a dashboard that legitimately makes many calls. A global cap
against crude flooding belongs in the reverse proxy — nginx's `limit_req` is
better placed for it, because it can refuse the connection before Python is
involved at all.

Fixed windows, not sliding: a counter and an expiry, one round trip. The cost
is that an attacker can spend a full allowance at the very end of one window
and again at the start of the next. For the limits here — a handful of attempts
per minute — that doubling changes nothing about whether guessing works.
"""

from fastapi import Request

from provider.core.config import settings
from provider.core.errors import RateLimitedError
from provider.core.redis import RedisDep


def client_ip(request: Request) -> str:
    """The address to attribute an attempt to.

    The socket peer — unless that peer is a trusted proxy, in which case it is
    the address that proxy claims in `X-Forwarded-For`. `IDEN_FORWARDED_ALLOW_IPS`
    draws that line and uvicorn applies it before any of this runs, so what
    arrives here is already the answer.

    Which line is drawn matters more than it looks. Trust nothing and every
    request behind a proxy shares one bucket, so a limit meant to be per caller
    becomes a cap on the whole deployment. Trust everything and a header anyone
    can set decides who they are counted as, which is no limit at all.
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
        # The window's own TTL is the honest answer: it is exactly when the
        # counter resets. -1 means the key somehow has no expiry, and waiting
        # the whole window is the safe thing to report.
        ttl = await redis.ttl(key)
        raise RateLimitedError(retry_after=ttl if ttl and ttl > 0 else window)


def limit_by_ip(bucket: str, *, limit: int, window: int):
    """A dependency that limits a route by caller address.

    A dependency rather than middleware so it runs *after* routing, which means
    the refusal is still recorded by the audit log — a burst of refused
    attempts is exactly what someone reviewing that log wants to find.
    """

    async def dependency(request: Request, redis: RedisDep) -> None:
        await hit(redis, bucket, client_ip(request), limit=limit, window=window)

    return dependency


async def guard(redis, bucket: str, identity: str, *, limit: int, window: int) -> None:
    """Refuse when this identity has already failed too often.

    Paired with `record_failure` and `clear`, this counts **failures only**. A
    limit on all attempts against one account is a way to lock its owner out:
    an attacker who wants someone locked out simply burns the allowance. Count
    only what went wrong, and clear it on success, and the person who knows the
    password can always still sign in.
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


# The numbers, in one place, so they can be argued about without hunting for
# them. Each is a ceiling on abuse, not a target for ordinary use: a person
# signing in types their password once, and gets several tries at a typo.

# Everything arriving from one address. Generous, because an office or a campus
# is one address to us.
LOGIN_PER_IP = limit_by_ip("login-ip", limit=30, window=300)
TOTP_PER_IP = limit_by_ip("totp-ip", limit=20, window=300)
RESET_PER_IP = limit_by_ip("reset-ip", limit=10, window=3600)

# The three endpoints that verify a **client secret**, which is argon2 and
# therefore costs the server 64 MiB and real CPU per attempt — before the caller
# has proved anything. Without a limit here, a few hundred requests a second
# naming any confidential client and any wrong secret is enough to exhaust a
# small machine, and the caller needs no credential to send them. Each gets its
# own bucket so spending one endpoint's allowance does not close the others.
TOKEN_PER_IP = limit_by_ip("token-ip", limit=120, window=60)
REVOKE_PER_IP = limit_by_ip("revoke-ip", limit=120, window=60)
INTROSPECT_PER_IP = limit_by_ip("introspect-ip", limit=120, window=60)

# `/authorize` writes a challenge into Redis for anyone who asks, and the entry
# lives `IDEN_CHALLENGE_TTL` whether or not the interaction it stands for ever
# happens. Unlimited, a flood fills Redis with them — which evicts the sessions
# stored beside them. The same number as the token endpoint deliberately: every
# authorization is followed by a token exchange, so this cannot be the limit a
# busy deployment meets first.
AUTHORIZE_PER_IP = limit_by_ip("authorize-ip", limit=120, window=60)

# Failures against one account, from anywhere. This is the limit that actually
# stops credential stuffing, because that attack rotates addresses and does not
# rotate the target.
LOGIN_FAILURES = {"bucket": "login-fail", "limit": 8, "window": 900}
TOTP_FAILURES = {"bucket": "totp-fail", "limit": 8, "window": 900}

# Reset requests for one address, so the endpoint cannot be used to bury
# someone in mail they did not ask for.
RESET_PER_ADDRESS = {"bucket": "reset-addr", "limit": 3, "window": 3600}
