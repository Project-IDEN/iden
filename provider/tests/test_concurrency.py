"""Races that a sequential test cannot see.

Driving these over HTTP does not work, and neither does `asyncio.gather` on two
service calls: whether the two transactions interleave at the critical section
is a matter of timing, so the test passes with or without the fix and proves
nothing.

Instead each test holds the first transaction open and asserts the second
**blocks** — which is what the row lock is for. Without the lock the second call
sails through, the assertion fails, and the race is demonstrated rather than
hoped for.
"""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from provider.authz.oauth.errors import InvalidGrant
from provider.authz.oauth.service import consume_code
from provider.authz.services import token_service as tokens
from provider.authz.services.pkce import create_challenge
from provider.core.config import settings
from provider.core.security import generate_token, hash_token
from provider.developer.clients import service as developer_service
from provider.developer.clients.errors import ApplicationQuotaReached
from provider.developer.clients.schemas import ApplicationCreate
from provider.shared.models import AuthorizationCode, Client, User

pytestmark = pytest.mark.usefixtures("catalogue")

VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
REDIRECT = "http://localhost:5173/callback"

# Long enough for an unblocked call to finish, short enough not to slow the suite.
SETTLE = 0.25


async def test_a_second_redemption_blocks_until_the_first_commits(
    engine, db, admin_user, dashboard
):
    """KI-3. Single use has to survive a race, not merely a sequence — that is
    the property that makes an intercepted authorization code survivable
    (RFC 6749 Section 4.1.2)."""
    code = generate_token()
    db.add(
        AuthorizationCode(
            code_hash=hash_token(code),
            client_id=dashboard.id,
            user_id=admin_user.id,
            redirect_uri=REDIRECT,
            scope="openid",
            code_challenge=create_challenge(VERIFIER),
            code_challenge_method="S256",
            acr="iden:loa:1",
            amr=["pwd"],
            sid="session-under-test",
            authenticated_at=tokens.now(),
            expires_at=tokens.now() + timedelta(minutes=1),
        )
    )
    await db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    redeem = lambda session: consume_code(  # noqa: E731
        session,
        code=code,
        client=dashboard,
        redirect_uri=REDIRECT,
        code_verifier=VERIFIER,
    )

    async with factory() as first, factory() as second:
        await redeem(first)  # claims the row; transaction stays open

        pending = asyncio.create_task(redeem(second))
        await asyncio.sleep(SETTLE)

        assert not pending.done(), "second redemption was not blocked by the first"

        await first.commit()

        with pytest.raises(InvalidGrant):
            await asyncio.wait_for(pending, timeout=5)


async def test_a_second_refresh_blocks_until_the_first_commits(
    engine, db, admin_user, dashboard
):
    """KI-3. Without the lock both callers see an unrotated token, both rotate,
    and reuse detection never fires."""
    token, record = await tokens.issue_refresh_token(
        db,
        client=dashboard,
        user=admin_user,
        scope="openid",
        acr="iden:loa:1",
        amr=["pwd"],
        authenticated_at=tokens.now(),
    )
    await db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as first, factory() as second:
        claimed = await tokens.consume_refresh_token(first, token)
        claimed.revoked_at = tokens.now()  # type: ignore
        await first.flush()

        pending = asyncio.create_task(tokens.consume_refresh_token(second, token))
        await asyncio.sleep(SETTLE)

        assert not pending.done(), "second refresh was not blocked by the first"

        await first.commit()

        with pytest.raises(tokens.RefreshTokenReuse):
            await asyncio.wait_for(pending, timeout=5)
        await second.rollback()


async def test_two_simultaneous_registrations_cannot_exceed_the_cap(
    engine, db, developer, monkeypatch
):
    """The application quota is a count followed by an insert.

    Without the lock both registrations count the same applications, both find
    room, and one person ends up over the cap. Nothing is escalated by that —
    it is a row, not a privilege — but the cap may as well mean what it says.

    Note which assertion does the work here. The second call blocks either way:
    inserting a client takes a `FOR KEY SHARE` lock on the owner it references,
    and that already conflicts with the open transaction. What the lock changes
    is *where* it blocks — before the count rather than after it — so the
    refusal at the end is the assertion that fails when it is removed.
    """
    monkeypatch.setattr(settings, "iden_developer_max_clients", 1)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as first, factory() as second:
        # A registration already in flight: the owner's row locked and its
        # client inserted, nothing committed. `create_application` cannot be
        # held open from out here — it commits — so this stands in for it.
        await first.execute(
            select(User.id).where(User.id == developer.id).with_for_update()
        )
        first.add(
            Client(
                client_id="showcase-in-flight",
                name="Showcase",
                client_type="public",
                allowed_grants=["authorization_code", "refresh_token"],
                redirect_uris=["https://showcase.example.org/callback"],
                owner_user_id=developer.id,
            )
        )
        await first.flush()

        pending = asyncio.create_task(
            developer_service.create_application(
                second,
                developer,
                ApplicationCreate(
                    name="Showcase",
                    client_type="public",
                    redirect_uris=["https://showcase.example.org/callback"],
                ),
            )
        )
        await asyncio.sleep(SETTLE)

        assert not pending.done(), "the second registration was not concurrent"

        await first.commit()

        # Counted after the wait, not before it, so the first one's row is
        # there to be seen. This is the assertion the lock is for.
        with pytest.raises(ApplicationQuotaReached):
            await asyncio.wait_for(pending, timeout=5)
        await second.rollback()
