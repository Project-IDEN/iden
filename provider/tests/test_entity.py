"""Phase 4.2 and 4.3 — what a signed-in person can do for themselves.

The governing rule: a person may change anything about themselves that does not
change what they are allowed to do.
"""

from urllib.parse import unquote, urlparse

import pyotp
import pytest
from sqlalchemy import select

from provider.core.config import settings
from provider.shared.models import ConsentGrant
from tests.conftest import ADMIN_PASSWORD
from tests.flows import get_tokens

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

NEW_PASSWORD = "a-longer-passphrase-1"


class TestFreshness:
    async def test_a_recent_sign_in_is_accepted(self, client, entity_headers, member):
        response = await client.post(
            "/entity/credentials/password",
            json={
                "currentPassword": ADMIN_PASSWORD,
                "newPassword": NEW_PASSWORD,
            },
            headers=entity_headers,
        )
        assert response.status_code == 200

    async def test_an_old_sign_in_is_refused(self, client, stale_headers):
        """A stolen token is enough to read a profile and not enough to take the
        account over. The attacker is sent back through the one step they
        cannot complete."""
        response = await client.post(
            "/entity/credentials/password",
            json={"currentPassword": ADMIN_PASSWORD, "newPassword": NEW_PASSWORD},
            headers=stale_headers,
        )

        assert response.status_code == 403
        assert (
            "insufficient_user_authentication" in response.headers["www-authenticate"]
        )
        assert "max_age=300" in response.headers["www-authenticate"]


class TestPasswordChange:
    async def test_the_current_password_is_required(self, client, entity_headers):
        response = await client.post(
            "/entity/credentials/password",
            json={"currentPassword": "wrong-one-entirely", "newPassword": NEW_PASSWORD},
            headers=entity_headers,
        )
        assert response.status_code == 422
        assert response.json()["code"] == "wrong_password"

    async def test_it_must_actually_change(self, client, entity_headers):
        response = await client.post(
            "/entity/credentials/password",
            json={"currentPassword": ADMIN_PASSWORD, "newPassword": ADMIN_PASSWORD},
            headers=entity_headers,
        )
        assert response.status_code == 422

    async def test_it_revokes_every_refresh_token(
        self, client, entity_headers, member, dashboard, db
    ):
        """A credential change that leaves old tokens alive has not taken
        effect — the point is to lock out whoever had the old password."""
        from provider.authz.services import token_service

        _, record = await token_service.issue_refresh_token(
            db,
            client=dashboard,
            user=member,
            scope="openid",
            acr="iden:loa:1",
            amr=["pwd"],
            authenticated_at=token_service.now(),
        )
        await db.commit()

        await client.post(
            "/entity/credentials/password",
            json={"currentPassword": ADMIN_PASSWORD, "newPassword": NEW_PASSWORD},
            headers=entity_headers,
        )

        await db.refresh(record)
        assert record.revoked_at is not None


class TestEmailChange:
    async def test_the_new_address_starts_unverified(
        self, client, entity_headers, member, db
    ):
        """Carrying the old verification over would let someone claim an
        address they cannot read."""
        await client.post(
            "/entity/credentials/email",
            json={"email": "new@test.local", "currentPassword": ADMIN_PASSWORD},
            headers=entity_headers,
        )

        await db.refresh(member)
        assert member.email == "new@test.local"
        assert member.email_verified_at is None

    async def test_it_cannot_take_someone_elses(
        self, client, entity_headers, admin_user
    ):
        response = await client.post(
            "/entity/credentials/email",
            json={"email": admin_user.email, "currentPassword": ADMIN_PASSWORD},
            headers=entity_headers,
        )
        assert response.status_code == 409


class TestTotp:
    async def test_enrollment_takes_two_steps(self, client, entity_headers, member, db):
        """A mis-scanned QR code must not lock someone out, so the credential
        does not count until a generated code comes back."""
        started = (
            await client.post("/entity/totp/enroll", headers=entity_headers)
        ).json()

        midway = (await client.get("/entity/totp", headers=entity_headers)).json()
        assert midway["enrolled"] is False

        confirmed = await client.post(
            "/entity/totp/confirm",
            json={"code": pyotp.TOTP(started["secret"]).now()},
            headers=entity_headers,
        )

        assert confirmed.status_code == 200
        assert confirmed.json()["enrolled"] is True

    @pytest.mark.parametrize(
        ("configured", "expected"),
        [
            ("Example University", "Example University"),
            # Nothing configured: IDEN stands alone, as it does in the lockup.
            ("", "IDEN"),
            # What this replaced. The issuer URL's "://" split the label, and
            # the authenticator showed "https: //iden.live" as the name.
            ("https://iden.live", "https iden.live"),
        ],
    )
    async def test_the_qr_code_is_filed_under_the_organization(
        self, client, entity_headers, member, monkeypatch, configured, expected
    ):
        """Someone reads this label every time they sign in for years, so it
        names the organization and their account — not the issuer URL."""
        monkeypatch.setattr(settings, "iden_org_name", configured)

        enrolled = (
            await client.post("/entity/totp/enroll", headers=entity_headers)
        ).json()

        label = unquote(urlparse(enrolled["uri"]).path).lstrip("/")
        issuer, _, account = label.partition(":")
        assert issuer == expected
        assert account == member.email

    async def test_a_wrong_code_does_not_enroll(self, client, entity_headers):
        await client.post("/entity/totp/enroll", headers=entity_headers)

        response = await client.post(
            "/entity/totp/confirm", json={"code": "000000"}, headers=entity_headers
        )

        assert response.status_code == 422
        status = (await client.get("/entity/totp", headers=entity_headers)).json()
        assert status["enrolled"] is False

    async def test_removal_needs_a_recent_sign_in(self, client, stale_headers):
        """Removing a second factor is the first thing an attacker with a
        stolen token would do."""
        response = await client.delete("/entity/totp", headers=stale_headers)

        assert response.status_code == 403

    async def test_enrolment_needs_a_recent_sign_in(self, client, stale_headers):
        """Enrolling is not the safe half of this pair.

        A confirmed authenticator is owed at every later sign-in, so a stolen
        token that could enrol one would lock the account's owner out for good:
        they cannot produce the code, a password reset leaves the credential in
        place, and removing it needs the recent sign-in they can no longer get.
        """
        response = await client.post("/entity/totp/enroll", headers=stale_headers)

        assert response.status_code == 403

    async def test_confirmation_needs_a_recent_sign_in(self, client, stale_headers):
        response = await client.post(
            "/entity/totp/confirm", json={"code": "000000"}, headers=stale_headers
        )

        assert response.status_code == 403


class TestPermissions:
    async def test_reports_where_each_permission_comes_from(
        self, client, entity_headers
    ):
        body = (await client.get("/entity/permissions", headers=entity_headers)).json()

        by_value = {source["value"]: source for source in body["scopes"]}
        assert "member" in body["roles"]
        assert by_value["entity:profile:read"]["viaRoles"] == ["member"]

    async def test_is_read_only(self, client, entity_headers):
        """Changing what you are allowed to do is authority, and authority is
        admin territory."""
        response = await client.post("/entity/permissions", headers=entity_headers)
        assert response.status_code == 405


class TestConnections:
    async def test_lists_what_you_agreed_to(
        self, client, entity_headers, member, third_party, db
    ):
        db.add(
            ConsentGrant(
                user_id=member.id,
                client_id=third_party.id,
                scopes=["openid", "entity:profile:read"],
            )
        )
        await db.commit()

        body = (await client.get("/entity/connections", headers=entity_headers)).json()

        assert body["connections"][0]["clientId"] == "library"
        assert "entity:profile:read" in body["connections"][0]["scopes"]

    async def test_withdrawing_removes_the_grant_and_the_tokens(
        self, client, entity_headers, member, third_party, db
    ):
        from provider.authz.services import token_service

        db.add(
            ConsentGrant(user_id=member.id, client_id=third_party.id, scopes=["openid"])
        )
        _, record = await token_service.issue_refresh_token(
            db,
            client=third_party,
            user=member,
            scope="openid",
            acr="iden:loa:1",
            amr=["pwd"],
            authenticated_at=token_service.now(),
        )
        await db.commit()

        response = await client.delete(
            "/entity/connections/library", headers=entity_headers
        )

        assert response.status_code == 204
        await db.refresh(record)
        assert record.revoked_at is not None
        assert await db.scalar(select(ConsentGrant)) is None

    async def test_an_unknown_application_is_still_204(self, client, entity_headers):
        """A different answer would tell a caller which client ids exist."""
        response = await client.delete(
            "/entity/connections/not-a-client", headers=entity_headers
        )
        assert response.status_code == 204


class TestSessions:
    async def test_lists_the_current_session(self, client, self_headers):
        await get_tokens(client)

        body = (await client.get("/entity/sessions", headers=self_headers)).json()

        assert len(body["sessions"]) == 1
        assert body["sessions"][0]["current"] is True
        assert body["sessions"][0]["clients"] == ["dashboard"]

    async def test_a_session_says_where_it_came_from(self, client, self_headers):
        """The list has to answer "is this one mine?", which needs more than
        when it started."""
        await get_tokens(client)

        session = (await client.get("/entity/sessions", headers=self_headers)).json()[
            "sessions"
        ][0]

        assert session["ip"] == "127.0.0.1"
        assert session["lastSeenAt"] >= session["authenticatedAt"]
        # The test client sends `python-httpx/…`, which is not a browser IDEN
        # can name — and an unnamed session is the correct answer, not an error.
        assert session["device"] is None
        assert session["browser"] is None

    async def test_the_user_agent_becomes_a_label(self, client, self_headers):
        # Set on the client rather than passed to the helper: the session is
        # created by the login POST, so that is the request whose header counts.
        client.headers["user-agent"] = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        )
        await get_tokens(client)

        session = (await client.get("/entity/sessions", headers=self_headers)).json()[
            "sessions"
        ][0]

        assert session["device"] == "Mac"
        assert session["browser"] == "Chrome 142"

    async def test_the_listed_id_is_not_a_cookie(self, client, self_headers):
        """It names a session; it must not be usable as one."""
        await get_tokens(client)
        body = (await client.get("/entity/sessions", headers=self_headers)).json()

        client.cookies.set("iden_session", body["sessions"][0]["id"])
        response = await client.get("/entity/sessions", headers=self_headers)

        assert response.json()["sessions"][0]["current"] is False

    async def test_signing_out_another_session_revokes_its_tokens(
        self, client, self_headers, db
    ):
        first = await get_tokens(client)
        client.cookies.clear()
        await get_tokens(client)

        listed = (await client.get("/entity/sessions", headers=self_headers)).json()
        other = next(s for s in listed["sessions"] if not s["current"])

        await client.delete(f"/entity/sessions/{other['id']}", headers=self_headers)

        refreshed = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": "dashboard",
            },
        )
        assert refreshed.status_code == 400

    async def test_signing_out_your_own_session_clears_the_cookie(
        self, client, self_headers
    ):
        """Otherwise the browser keeps a cookie naming a session that is gone."""
        await get_tokens(client)
        listed = (await client.get("/entity/sessions", headers=self_headers)).json()
        current = next(s for s in listed["sessions"] if s["current"])

        await client.delete(f"/entity/sessions/{current['id']}", headers=self_headers)

        assert "iden_session" not in client.cookies

    async def test_signing_out_another_session_leaves_your_cookie(
        self, client, self_headers
    ):
        await get_tokens(client)
        client.cookies.clear()
        await get_tokens(client)
        listed = (await client.get("/entity/sessions", headers=self_headers)).json()
        other = next(s for s in listed["sessions"] if not s["current"])

        await client.delete(f"/entity/sessions/{other['id']}", headers=self_headers)

        assert "iden_session" in client.cookies

    async def test_you_cannot_sign_out_someone_elses_session(
        self, client, self_headers, entity_headers
    ):
        """A public id is not a credential, so holding one implies nothing."""
        await get_tokens(client)
        listed = (await client.get("/entity/sessions", headers=self_headers)).json()
        victim = listed["sessions"][0]["id"]

        await client.delete(f"/entity/sessions/{victim}", headers=entity_headers)

        after = (await client.get("/entity/sessions", headers=self_headers)).json()
        assert len(after["sessions"]) == 1
