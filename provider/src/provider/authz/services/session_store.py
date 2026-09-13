"""Browser login sessions, in Redis under a sliding TTL.

Not in Postgres: a session is ephemeral, and expiry should be the storage
layer's job rather than a cleanup job's.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis

from provider.core.config import settings
from provider.core.security import generate_token, hash_token

COOKIE_NAME = "iden_session"

# How stale `last_seen_at` is allowed to get before a read rewrites it.
#
# `get` runs on every request that carries the cookie — /authorize, each login
# step, consent, logout — so saving on every read would turn each session read
# into a session write for a field whose only consumer is a human reading
# "3 hr ago". A minute is finer than that sentence can express.
SEEN_RESOLUTION = 60


@dataclass
class Session:
    id: str
    user_id: UUID
    amr: list[str]
    authenticated_at: datetime
    # When this session last made a request, as opposed to when the person
    # signed in. On a 24-hour sliding session those diverge immediately, and
    # it is the one that answers "am I still using this?".
    last_seen_at: datetime
    # Both are best effort and stay `None` for sessions created before they
    # were recorded. The address is the socket peer, never `X-Forwarded-For`.
    ip: str | None = None
    user_agent: str | None = None

    @property
    def public_id(self) -> str:
        """The `sid` claim: a hash of the session id, never the id itself.

        `id` is the cookie value — a bearer credential. Publishing it to every
        client in every ID token would hand each of them, and anyone who read a
        token in transit, the ability to set that cookie and become the user.
        The hash names the session without being usable as one.
        """
        return hash_token(self.id)


def public_id_of(session_id: str) -> str:
    """The public name of a session id — see `Session.public_id`."""
    return hash_token(session_id)


def _key(session_id: str) -> str:
    # Hashed like any other credential: a Redis dump must not yield usable
    # session ids.
    return f"session:{hash_token(session_id)}"


def _clients_key(session_id: str) -> str:
    """The clients a session has signed into.

    Sign-out has to notify the applications this session reached, and there is
    no other record of which those were: an authorization code is short-lived
    and a refresh token may never have been issued. Keyed by the same hash as
    the session, so it is unreadable from a Redis dump and expires with it.
    """
    return f"session_clients:{hash_token(session_id)}"


def _user_key(user_id: UUID) -> str:
    """Index of a user's live sessions.

    Sessions are keyed by a hash of an id nobody but the browser holds, so
    without this index there is no way to answer "sign me out everywhere" or to
    invalidate sessions when a password changes.
    """
    return f"user_sessions:{user_id}"


async def create(
    redis: Redis,
    user_id: UUID,
    method: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Session:
    now = datetime.now(UTC)
    session = Session(
        id=generate_token(),
        user_id=user_id,
        amr=[method],
        authenticated_at=now,
        last_seen_at=now,
        ip=ip,
        user_agent=user_agent,
    )
    await _save(redis, session)
    await redis.sadd(_user_key(user_id), _key(session.id))
    await redis.expire(_user_key(user_id), settings.iden_session_ttl)
    return session


async def _save(redis: Redis, session: Session) -> None:
    payload = json.dumps(
        {
            "user_id": str(session.user_id),
            "amr": session.amr,
            "authenticated_at": session.authenticated_at.isoformat(),
            "last_seen_at": session.last_seen_at.isoformat(),
            "ip": session.ip,
            "user_agent": session.user_agent,
        }
    )
    await redis.set(_key(session.id), payload, ex=settings.iden_session_ttl)


def _parse(session_id: str, raw: str) -> Session:
    """A stored payload as a `Session`.

    Every field added after the first release is read with a default: a
    deployment upgrading in place has live sessions written in the older shape,
    and raising on them would sign out everyone who was signed in at the moment
    of the deploy. `last_seen_at` falls back to the sign-in time, which is the
    truthful answer when nothing better was ever recorded.
    """
    data = json.loads(raw)
    authenticated_at = datetime.fromisoformat(data["authenticated_at"])
    last_seen = data.get("last_seen_at")

    return Session(
        id=session_id,
        user_id=UUID(data["user_id"]),
        amr=data["amr"],
        authenticated_at=authenticated_at,
        last_seen_at=datetime.fromisoformat(last_seen)
        if last_seen
        else authenticated_at,
        ip=data.get("ip"),
        user_agent=data.get("user_agent"),
    )


async def get(redis: Redis, session_id: str | None) -> Session | None:
    if not session_id:
        return None

    raw = await redis.get(_key(session_id))
    if raw is None:
        return None

    # Sliding expiry: an active session should not be logged out mid-use.
    # Unconditional, unlike the last_seen write below — this one is what keeps
    # the session alive, not what describes it.
    await redis.expire(_key(session_id), settings.iden_session_ttl)

    session = _parse(session_id, str(raw))

    now = datetime.now(UTC)
    if (now - session.last_seen_at).total_seconds() > SEEN_RESOLUTION:
        session.last_seen_at = now
        await _save(redis, session)

    return session


async def list_for_user(redis: Redis, user_id: UUID) -> list[Session]:
    """Every live session for this person, named by `public_id`.

    The raw session id is never returned: it is the cookie, and an endpoint that
    handed one back would let anyone with read access to a person's session list
    assume any of them. The `id` on these is the public one, and the `Session`
    returned here cannot be used to authenticate.
    """
    keys = [str(key) for key in await redis.smembers(_user_key(user_id))]
    sessions = []

    for key in keys:
        raw = await redis.get(key)
        if raw is None:
            # Expired between the index read and now; the index is cleaned up
            # lazily rather than transactionally.
            await redis.srem(_user_key(user_id), key)
            continue
        sessions.append(_parse(key.removeprefix("session:"), str(raw)))

    # By when each sign-in began, not by activity: this list is read while it is
    # being acted on, and ordering by last-seen would reshuffle it under the
    # reader as their own session ticks.
    return sorted(sessions, key=lambda s: s.authenticated_at, reverse=True)


async def clients_for_public_id(redis: Redis, public_id: str) -> set[str]:
    return {
        str(value) for value in await redis.smembers(f"session_clients:{public_id}")
    }


async def delete_by_public_id(redis: Redis, user_id: UUID, public_id: str) -> bool:
    """Delete one of a person's own sessions, named by its public id.

    The ownership check is the point: a public id is not a credential, so
    nothing about holding one implies the right to end that session.
    """
    key = f"session:{public_id}"
    raw = await redis.get(key)
    if raw is None or UUID(json.loads(raw)["user_id"]) != user_id:
        return False

    await redis.delete(key, f"session_clients:{public_id}")
    await redis.srem(_user_key(user_id), key)
    return True


async def add_client(redis: Redis, session_id: str, client_id: str) -> None:
    """Record that this session issued a code to a client."""
    await redis.sadd(_clients_key(session_id), client_id)
    await redis.expire(_clients_key(session_id), settings.iden_session_ttl)


async def clients_for(redis: Redis, session_id: str) -> set[str]:
    # The client is built with decode_responses=True, so members come back as
    # str; the type stubs describe both shapes.
    return {str(value) for value in await redis.smembers(_clients_key(session_id))}


async def reauthenticate(
    redis: Redis,
    session: Session,
    method: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Session:
    """A fresh authentication on an existing session — `prompt=login`, or a
    `max_age` the session no longer satisfies.

    The session id is kept. Replacing it would strand the old one in Redis with
    no cookie pointing at it, and would break sign-out for every application
    that was told the old `sid`.

    The address and agent are replaced rather than kept: the session continues,
    but this is a new sign-in and the person may well be on a different machine.
    """
    now = datetime.now(UTC)
    session.amr = [method]
    session.authenticated_at = now
    session.last_seen_at = now
    session.ip = ip
    session.user_agent = user_agent
    await _save(redis, session)
    return session


async def add_method(redis: Redis, session: Session, method: str) -> Session:
    """Record a step-up. The acr claim is recomputed from amr at issuance."""
    if method not in session.amr:
        session.amr.append(method)
        await _save(redis, session)
    return session


async def delete(redis: Redis, session_id: str) -> None:
    session = await get(redis, session_id)
    await redis.delete(_key(session_id), _clients_key(session_id))
    if session is not None:
        await redis.srem(_user_key(session.user_id), _key(session_id))
