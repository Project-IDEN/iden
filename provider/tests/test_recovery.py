"""Phase 4.4 — password recovery.

In the AuthZ module because a locked-out person has no token, so nothing in the
Entity RS can reach them. Without it, every forgotten password is a support
ticket.
"""

import pytest
from sqlalchemy import select

from provider.authz.recovery import service
from provider.shared.models import User
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD
from tests.flows import get_tokens

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

NEW_PASSWORD = "a-brand-new-passphrase"


@pytest.fixture
def sent(monkeypatch):
    """Capture what the notifier would deliver."""
    messages: list[dict] = []

    async def capture(*, to: str, subject: str, body: str) -> None:
        messages.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr(service.notifier, "send", capture)
    return messages


def token_from(message: dict) -> str:
    return message["body"].split("token=")[1].strip()


class TestRequesting:
    async def test_a_known_address_gets_a_link(self, client, sent):
        response = await client.post(
            "/api/v1/auth/password-reset", json={"email": ADMIN_EMAIL}
        )

        assert response.status_code == 202
        assert sent[0]["to"] == ADMIN_EMAIL

    async def test_an_unknown_address_answers_identically(self, client, sent):
        """Anything else would turn this into a way to discover who has an
        account here."""
        known = await client.post(
            "/api/v1/auth/password-reset", json={"email": ADMIN_EMAIL}
        )
        unknown = await client.post(
            "/api/v1/auth/password-reset", json={"email": "nobody@test.local"}
        )

        assert known.status_code == unknown.status_code == 202
        assert known.content == unknown.content == b""
        assert len(sent) == 1

    async def test_the_token_is_not_stored_in_the_clear(self, client, sent, redis):
        await client.post("/api/v1/auth/password-reset", json={"email": ADMIN_EMAIL})
        token = token_from(sent[0])

        keys = [str(key) for key in await redis.keys("password_reset:*")]

        assert keys
        assert not any(token in key for key in keys)


class TestConfirming:
    async def test_the_new_password_works(self, client, sent):
        await client.post("/api/v1/auth/password-reset", json={"email": ADMIN_EMAIL})

        confirmed = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token_from(sent[0]), "newPassword": NEW_PASSWORD},
        )

        assert confirmed.status_code == 204

    async def test_a_link_works_once(self, client, sent):
        await client.post("/api/v1/auth/password-reset", json={"email": ADMIN_EMAIL})
        token = token_from(sent[0])

        first = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "newPassword": NEW_PASSWORD},
        )
        again = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "newPassword": "yet-another-passphrase"},
        )

        assert first.status_code == 204
        assert again.status_code == 422

    async def test_an_invented_token_is_refused(self, client):
        response = await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": "not-a-real-token", "newPassword": NEW_PASSWORD},
        )
        assert response.status_code == 422

    async def test_it_signs_the_account_out_everywhere(self, client, sent, db):
        """Whoever prompted the reset may be the reason it was needed."""
        tokens = await get_tokens(client)
        await client.post("/api/v1/auth/password-reset", json={"email": ADMIN_EMAIL})

        await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token_from(sent[0]), "newPassword": NEW_PASSWORD},
        )

        refreshed = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": "dashboard",
            },
        )
        assert refreshed.status_code == 400

    async def test_the_old_password_stops_working(self, client, sent, db):
        await client.post("/api/v1/auth/password-reset", json={"email": ADMIN_EMAIL})
        await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token_from(sent[0]), "newPassword": NEW_PASSWORD},
        )

        user = await db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        await db.refresh(user)

        from provider.core.security import verify_secret

        assert not verify_secret(user.password_hash, ADMIN_PASSWORD)
        assert verify_secret(user.password_hash, NEW_PASSWORD)


class TestNotifierDoesNotLogTheToken:
    """The reset link is a credential for fifteen minutes.

    In development the log is the only inbox there is, so it carries the link.
    Anywhere else a log is aggregated and retained, and a link in it is an
    account takeover waiting to be read.
    """

    async def test_the_body_is_withheld_outside_development(self, monkeypatch, caplog):
        from provider.core import notifier

        monkeypatch.setattr(notifier.settings, "iden_env", "prod")
        await notifier.send(
            to="someone@example.org", subject="Reset your password", body="token=SECRET"
        )

        assert "SECRET" not in caplog.text

    async def test_the_body_is_logged_in_development(self, monkeypatch, caplog):
        from provider.core import notifier

        monkeypatch.setattr(notifier.settings, "iden_env", "dev")
        await notifier.send(
            to="someone@example.org", subject="Reset your password", body="token=SECRET"
        )

        assert "SECRET" in caplog.text
