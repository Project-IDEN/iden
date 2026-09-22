"""Session provenance — what a session records about where it came from.

Store-level, so no database and no HTTP: these are properties of the Redis
payload and the rules for writing it. The endpoint that surfaces them is
covered in `test_entity.py::TestSessions`.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

from provider.authz.services import session_store
from provider.core.security import generate_token

CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
)


async def _stored(redis, session_id: str) -> dict:
    raw = await redis.get(f"session:{session_store.public_id_of(session_id)}")
    return json.loads(raw)


async def _age_last_seen(redis, session_id: str, *, seconds: int) -> datetime:
    """Backdate the stored `last_seen_at`, to test the throttle without sleeping."""
    key = f"session:{session_store.public_id_of(session_id)}"
    data = json.loads(await redis.get(key))
    stale = datetime.now(UTC) - timedelta(seconds=seconds)
    data["last_seen_at"] = stale.isoformat()
    await redis.set(key, json.dumps(data))
    return stale


async def test_a_new_session_records_where_it_came_from(redis):
    session = await session_store.create(
        redis, uuid.uuid7(), "pwd", ip="203.0.113.7", user_agent=CHROME_MAC
    )

    stored = await session_store.get(redis, session.id)

    assert stored is not None
    assert stored.ip == "203.0.113.7"
    assert stored.user_agent == CHROME_MAC
    assert stored.last_seen_at == stored.authenticated_at


async def test_a_payload_written_before_this_change_still_loads(redis):
    """The upgrade case.

    A deployment upgrading in place has live sessions whose payload predates
    these fields, and raising on them would sign everyone out. Written directly
    rather than through `create`, which would produce the current shape.
    """
    session_id = generate_token()
    signed_in = datetime.now(UTC)
    await redis.set(
        f"session:{session_store.public_id_of(session_id)}",
        json.dumps(
            {
                "user_id": str(uuid.uuid7()),
                "amr": ["pwd"],
                "authenticated_at": signed_in.isoformat(),
            }
        ),
    )

    stored = await session_store.get(redis, session_id)

    assert stored is not None
    assert stored.ip is None
    assert stored.user_agent is None
    # Nothing better was ever recorded, so the sign-in time is the honest answer.
    assert stored.last_seen_at == signed_in


async def test_a_read_inside_the_resolution_does_not_rewrite(redis):
    """`get` runs on every request carrying the cookie. Saving on each one would
    turn every session read into a session write."""
    session = await session_store.create(redis, uuid.uuid7(), "pwd")
    before = (await _stored(redis, session.id))["last_seen_at"]

    await session_store.get(redis, session.id)

    assert (await _stored(redis, session.id))["last_seen_at"] == before


async def test_a_read_after_the_resolution_advances_last_seen(redis):
    session = await session_store.create(redis, uuid.uuid7(), "pwd")
    stale = await _age_last_seen(
        redis, session.id, seconds=session_store.SEEN_RESOLUTION + 5
    )

    refreshed = await session_store.get(redis, session.id)

    assert refreshed is not None
    assert refreshed.last_seen_at > stale
    assert (
        datetime.fromisoformat((await _stored(redis, session.id))["last_seen_at"])
        > stale
    )


async def test_reauthentication_replaces_the_address_and_agent(redis):
    """The session id survives a re-authentication, but the person may well be
    on a different machine — so what describes the machine does not."""
    session = await session_store.create(
        redis, uuid.uuid7(), "pwd", ip="203.0.113.7", user_agent=CHROME_MAC
    )

    await session_store.reauthenticate(
        redis, session, "pwd", ip="198.51.100.4", user_agent="curl/8.7.1"
    )

    stored = await session_store.get(redis, session.id)
    assert stored is not None
    assert stored.ip == "198.51.100.4"
    assert stored.user_agent == "curl/8.7.1"


async def test_the_listing_carries_the_same_fields(redis):
    user_id = uuid.uuid7()
    await session_store.create(
        redis, user_id, "pwd", ip="203.0.113.7", user_agent=CHROME_MAC
    )

    listed = await session_store.list_for_user(redis, user_id)

    assert [(s.ip, s.user_agent) for s in listed] == [("203.0.113.7", CHROME_MAC)]
