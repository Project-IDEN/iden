"""Phase 3.3 and 3.4 — single sign-out.

Ending IDEN's session is one Redis delete. What makes "sign out" mean anything
is telling the applications the session reached, because each keeps its own.
"""

from types import SimpleNamespace

import httpx
import jwt
import pytest
from sqlalchemy import select

from provider.authz.logout import service as logout_service
from provider.authz.recovery import service as recovery_service
from provider.authz.services import session_store
from provider.core.crypto import verify_jwt
from provider.shared.models import AuditEvent, Client
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD
from tests.flows import get_tokens, pkce_pair, query_of, sign_in, start

POST_LOGOUT_URI = "http://localhost:5173/"

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")


@pytest.fixture
def deliveries(monkeypatch):
    """Capture the logout tokens IDEN posts, without a listening server.

    The service's own `httpx` name is rebound, not httpx itself: patching the
    module would also replace the transport the test client rides on.
    """
    received: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        token = body.removeprefix("logout_token=")
        received.append((str(request.url), token))
        return httpx.Response(200)

    def factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(
        logout_service,
        "httpx",
        SimpleNamespace(
            AsyncClient=factory,
            MockTransport=httpx.MockTransport,
            HTTPError=httpx.HTTPError,
            Request=httpx.Request,
            Response=httpx.Response,
        ),
    )
    return received


@pytest.fixture
async def listening(db, dashboard) -> Client:
    """The dashboard, registered for back-channel logout."""
    dashboard.backchannel_logout_uri = "https://dashboard.example.org/logout"
    db.add(dashboard)
    await db.commit()
    return dashboard


def claims_of(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


async def refresh(client, refresh_token: str):
    return await client.post(
        "/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "dashboard",
        },
    )


async def switch_account(client, prompt: str, **credentials):
    """Ask to sign in again on a browser that already has a session, and do."""
    _, challenge = pkce_pair()
    response = await start(client, challenge, prompt=prompt)
    return await sign_in(client, query_of(response)["challenge"], **credentials)


class TestFanOut:
    async def test_a_registered_client_is_told(self, client, listening, deliveries):
        await get_tokens(client)

        await client.get("/oauth2/logout", follow_redirects=False)

        assert len(deliveries) == 1
        url, token = deliveries[0]
        assert url == "https://dashboard.example.org/logout"
        assert claims_of(token)["aud"] == "dashboard"

    async def test_a_client_without_a_uri_is_not(self, client, deliveries):
        """The dashboard has no backchannel URI in this test — nothing to tell."""
        await get_tokens(client)

        await client.get("/oauth2/logout", follow_redirects=False)

        assert deliveries == []

    async def test_only_clients_this_session_reached(
        self, client, listening, db, kiosk, deliveries
    ):
        """A client that was never signed into during this session has no
        session to end, and telling it would leak that the person exists."""
        registered, _ = kiosk
        registered.backchannel_logout_uri = "https://kiosk.example.org/logout"
        db.add(registered)
        await db.commit()

        await get_tokens(client)  # dashboard only
        await client.get("/oauth2/logout", follow_redirects=False)

        assert [url for url, _ in deliveries] == [
            "https://dashboard.example.org/logout"
        ]

    async def test_a_failed_delivery_does_not_fail_the_sign_out(
        self, client, listening, monkeypatch
    ):
        def explode(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unreachable")

        def factory(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(explode), **kwargs)

        monkeypatch.setattr(
            logout_service,
            "httpx",
            SimpleNamespace(AsyncClient=factory, HTTPError=httpx.HTTPError),
        )
        await get_tokens(client)

        response = await client.get("/oauth2/logout", follow_redirects=False)

        assert response.status_code in (204, 303)


class TestLogoutToken:
    async def test_is_signed_by_iden_and_names_the_session(
        self, client, listening, deliveries
    ):
        tokens = await get_tokens(client)
        sid = claims_of(tokens["id_token"])["sid"]

        await client.get("/oauth2/logout", follow_redirects=False)

        _, token = deliveries[0]
        claims = verify_jwt(token, audience="dashboard")
        assert claims["sid"] == sid
        assert logout_service.BACKCHANNEL_LOGOUT_EVENT in claims["events"]

    async def test_carries_no_nonce(self, client, listening, deliveries):
        """OIDC Back-Channel Logout Section 2.4 forbids it: with a nonce, a stolen
        logout token could be replayed as proof of a fresh authentication."""
        await get_tokens(client)
        await client.get("/oauth2/logout", follow_redirects=False)

        assert "nonce" not in claims_of(deliveries[0][1])

    async def test_is_refused_as_an_id_token_hint(self, client, listening, deliveries):
        """It is signed by IDEN and carries `sub`, so without the `events` check
        a client could replay the token that told it to sign out as evidence
        that someone is signed in.

        Measured against a real ID token doing the same job: the hint is what
        resolves the client, and only a resolved client's post-logout URI is
        honoured. One redirects, the other cannot.
        """
        real = await get_tokens(client)
        await client.get("/oauth2/logout", follow_redirects=False)
        _, logout_token = deliveries[0]

        accepted = await client.get(
            "/oauth2/logout",
            params={
                "id_token_hint": real["id_token"],
                "post_logout_redirect_uri": POST_LOGOUT_URI,
            },
            follow_redirects=False,
        )
        refused = await client.get(
            "/oauth2/logout",
            params={
                "id_token_hint": logout_token,
                "post_logout_redirect_uri": POST_LOGOUT_URI,
            },
            follow_redirects=False,
        )

        assert accepted.status_code == 303
        assert refused.status_code == 204


class TestTokenRevocation:
    async def test_refresh_tokens_from_the_session_are_revoked(self, client, db):
        """Otherwise a signed-out client keeps minting access tokens for as long
        as it likes, which is not what anyone means by signing out."""
        tokens = await get_tokens(client)

        await client.get("/oauth2/logout", follow_redirects=False)

        refreshed = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": "dashboard",
            },
        )
        assert refreshed.status_code == 400

    async def test_another_sessions_tokens_survive(self, client, db):
        """Signing out of one browser must not sign out the others — the point
        of revoking by `sid` rather than by user."""
        first = await get_tokens(client)
        client.cookies.clear()
        await get_tokens(client)  # a second browser session

        await client.get("/oauth2/logout", follow_redirects=False)

        refreshed = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": "dashboard",
            },
        )
        assert refreshed.status_code == 200


class TestAudit:
    async def test_every_delivery_is_recorded(self, client, listening, deliveries, db):
        await get_tokens(client)
        await client.get("/oauth2/logout", follow_redirects=False)

        rows = list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "POST backchannel_logout")
            )
        )
        assert len(rows) == 1
        assert rows[0].status_code == 200
        assert rows[0].target == "dashboard"

    async def test_a_failure_is_recorded_too(self, client, listening, monkeypatch, db):
        """A sign-out that did not arrive somewhere has to be visible afterwards."""

        def explode(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unreachable")

        monkeypatch.setattr(
            logout_service,
            "httpx",
            SimpleNamespace(
                AsyncClient=lambda **kw: httpx.AsyncClient(
                    transport=httpx.MockTransport(explode), **kw
                ),
                HTTPError=httpx.HTTPError,
            ),
        )
        await get_tokens(client)
        await client.get("/oauth2/logout", follow_redirects=False)

        row = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "POST backchannel_logout")
        )
        assert row is not None
        assert row.status_code == 0


class TestSwitchingAccount:
    """IDEN holds one account per browser. When someone else signs in on it, the
    previous person is signed out — and that has to mean what signing out means
    everywhere else, not only that their session disappears from Redis."""

    OTHER = {"email": "student@test.local", "password": "correct-horse-battery-staple"}

    async def test_the_previous_persons_refresh_tokens_are_revoked(
        self, client, member
    ):
        tokens = await get_tokens(client)

        switched = await switch_account(client, "select_account", **self.OTHER)

        assert switched.status_code == 200
        assert (await refresh(client, tokens["refresh_token"])).status_code == 400

    async def test_the_applications_they_reached_are_told(
        self, client, member, admin_user, listening, deliveries
    ):
        tokens = await get_tokens(client)
        sid = claims_of(tokens["id_token"])["sid"]

        await switch_account(client, "login", **self.OTHER)

        assert len(deliveries) == 1
        claims = verify_jwt(deliveries[0][1], audience="dashboard")
        assert claims["sub"] == str(admin_user.id)
        assert claims["sid"] == sid

    async def test_their_session_is_gone_and_the_new_one_is_not(
        self, client, redis, member, admin_user
    ):
        await get_tokens(client)

        await switch_account(client, "select_account", **self.OTHER)

        assert await session_store.list_for_user(redis, admin_user.id) == []
        assert len(await session_store.list_for_user(redis, member.id)) == 1

    async def test_the_same_person_again_ends_nothing(
        self, client, listening, deliveries
    ):
        """`prompt=login` by the person already signed in is a fresh proof on the
        same session, not a sign-out."""
        tokens = await get_tokens(client)

        await switch_account(client, "login")

        assert deliveries == []
        assert (await refresh(client, tokens["refresh_token"])).status_code == 200


class TestEndingEverySession:
    """A password change, a reset, deactivation and deletion end every session
    a person has at once. Each has to reach the applications those sessions
    signed into — revoking the refresh tokens stops new access tokens, but an
    application keeps its own session until it is told."""

    MEMBER = TestSwitchingAccount.OTHER

    async def sign_in_member(self, client):
        """A browser session for the member that has reached the dashboard."""
        client.cookies.clear()
        _, challenge = pkce_pair()
        response = await start(client, challenge)
        step = await sign_in(client, query_of(response)["challenge"], **self.MEMBER)
        await client.get(step.json()["resumeUrl"])
        client.cookies.clear()

    async def test_a_password_change_tells_every_session(
        self, client, redis, admin_user, self_headers, listening, deliveries
    ):
        first = claims_of((await get_tokens(client))["id_token"])["sid"]
        client.cookies.clear()
        second = claims_of((await get_tokens(client))["id_token"])["sid"]
        client.cookies.clear()

        response = await client.post(
            "/entity/credentials/password",
            json={"currentPassword": ADMIN_PASSWORD, "newPassword": "a-new-passphrase"},
            headers=self_headers,
        )

        assert response.json()["sessionsEnded"] == 2
        assert {claims_of(token)["sid"] for _, token in deliveries} == {first, second}
        assert await session_store.list_for_user(redis, admin_user.id) == []

    async def test_the_session_making_the_change_survives(
        self, client, redis, admin_user, self_headers, listening, deliveries
    ):
        """Signing someone out of the page they are using to secure their
        account is hostile. The browser sends its cookie; that session stays."""
        other = claims_of((await get_tokens(client))["id_token"])["sid"]
        client.cookies.clear()
        await get_tokens(client)  # this browser, which keeps its cookie

        response = await client.post(
            "/entity/credentials/password",
            json={"currentPassword": ADMIN_PASSWORD, "newPassword": "a-new-passphrase"},
            headers=self_headers,
        )

        assert response.json()["sessionsEnded"] == 1
        assert [claims_of(token)["sid"] for _, token in deliveries] == [other]
        assert len(await session_store.list_for_user(redis, admin_user.id)) == 1

    async def test_a_password_reset_tells_every_session(
        self, client, redis, admin_user, listening, deliveries, monkeypatch
    ):
        links: list[str] = []

        async def capture(*, to: str, subject: str, body: str) -> None:
            links.append(body.split("token=")[1].strip())

        monkeypatch.setattr(recovery_service.notifier, "send", capture)
        sid = claims_of((await get_tokens(client))["id_token"])["sid"]
        client.cookies.clear()

        await client.post("/api/v1/auth/password-reset", json={"email": ADMIN_EMAIL})
        await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": links[0], "newPassword": "a-new-passphrase"},
        )

        assert [claims_of(token)["sid"] for _, token in deliveries] == [sid]
        assert await session_store.list_for_user(redis, admin_user.id) == []

    async def test_deactivation_tells_every_session(
        self, client, member, admin_headers, listening, deliveries
    ):
        await self.sign_in_member(client)

        response = await client.patch(
            f"/admin/users/{member.id}", json={"isActive": False}, headers=admin_headers
        )

        assert response.status_code == 200
        assert [claims_of(token)["sub"] for _, token in deliveries] == [str(member.id)]

    async def test_deletion_tells_every_session(
        self, client, db, member, admin_headers, listening, deliveries
    ):
        """Deletion writes the delivery to the audit log in the same transaction
        that removes the person it names, and must still commit."""
        await self.sign_in_member(client)

        response = await client.delete(
            f"/admin/users/{member.id}", headers=admin_headers
        )

        assert response.status_code == 204
        assert [claims_of(token)["sub"] for _, token in deliveries] == [str(member.id)]
        row = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "POST backchannel_logout")
        )
        assert row is not None
        assert row.actor_user_id is None
