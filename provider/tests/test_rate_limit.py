"""KI-13. Argon2 makes a guess expensive for the server, not the attacker."""

import pytest

from provider.core import ratelimit
from tests.flows import pkce_pair, query_of, sign_in, start

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")


async def challenge_id(client) -> str:
    _, challenge = pkce_pair()
    return query_of(await start(client, challenge))["challenge"]


class TestLoginLimits:
    async def test_repeated_wrong_passwords_are_cut_off(self, client):
        cid = await challenge_id(client)
        limit = ratelimit.LOGIN_FAILURES["limit"]

        for _ in range(limit):
            assert (await sign_in(client, cid, password="wrong")).status_code == 401

        blocked = await sign_in(client, cid, password="wrong")

        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) > 0

    async def test_the_right_password_still_works_under_attack(self, client):
        """The reason failures are counted rather than attempts: otherwise
        anyone could lock anyone else out by guessing badly on purpose."""
        cid = await challenge_id(client)
        for _ in range(ratelimit.LOGIN_FAILURES["limit"] - 1):
            await sign_in(client, cid, password="wrong")

        response = await sign_in(client, cid)

        assert response.status_code == 200

    async def test_success_clears_the_count(self, client):
        cid = await challenge_id(client)
        for _ in range(ratelimit.LOGIN_FAILURES["limit"] - 1):
            await sign_in(client, cid, password="wrong")
        await sign_in(client, cid)

        client.cookies.clear()
        again = await sign_in(client, await challenge_id(client), password="wrong")

        assert again.status_code == 401

    async def test_the_limit_follows_the_account_not_the_address(self, client, redis):
        """Credential stuffing rotates addresses and does not rotate the
        target, so the address counter alone would not touch it."""
        cid = await challenge_id(client)
        for _ in range(ratelimit.LOGIN_FAILURES["limit"]):
            await sign_in(client, cid, password="wrong")

        # Clear every per-address counter, as moving to a new address would.
        for key in await redis.keys("ratelimit:login-ip:*"):
            await redis.delete(key)

        blocked = await sign_in(client, cid, password="wrong")

        assert blocked.status_code == 429


class TestConfiguration:
    async def test_it_can_be_switched_off(self, client, monkeypatch):
        """For a load test against a deployment you own."""
        from provider.core.config import settings

        monkeypatch.setattr(settings, "iden_rate_limit_enabled", False)
        cid = await challenge_id(client)

        attempts = [
            await sign_in(client, cid, password="wrong")
            for _ in range(ratelimit.LOGIN_FAILURES["limit"] + 3)
        ]

        assert {attempt.status_code for attempt in attempts} == {401}


class TestRefusalIsRecorded:
    async def test_a_blocked_attempt_reaches_the_audit_log(self, client, db):
        """The refusal runs after routing precisely so this still happens — a
        burst of them is what someone reviewing the log wants to find."""
        from sqlalchemy import select

        from provider.shared.models import AuditEvent

        cid = await challenge_id(client)
        for _ in range(ratelimit.LOGIN_FAILURES["limit"] + 1):
            await sign_in(client, cid, password="wrong")

        rows = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.status_code == 429))
        )

        assert rows
        assert rows[0].action == "POST /api/v1/auth/login"
        assert rows[0].detail["password"] == "[redacted]"
