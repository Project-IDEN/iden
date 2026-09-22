"""KI-12. Every state-changing request leaves a record that outlives its actor."""

import pytest
from sqlalchemy import select

from provider.shared.models import AuditEvent, User
from tests.flows import get_tokens, pkce_pair, query_of, sign_in, start

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")


async def events(db) -> list[AuditEvent]:
    return list(
        await db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at.desc()))
    )


class TestRecording:
    async def test_records_an_admin_write(self, client, admin_headers, db):
        await client.post(
            "/admin/groups",
            json={"name": "engineering", "description": "Builders."},
            headers=admin_headers,
        )

        (event,) = await events(db)
        assert event.action == "POST /admin/groups"
        assert event.status_code == 201
        assert event.detail["name"] == "engineering"

    async def test_does_not_record_reads(self, client, admin_headers, db):
        await client.get("/admin/groups", headers=admin_headers)
        await client.get("/admin/users", headers=admin_headers)

        assert await events(db) == []

    async def test_records_a_refused_attempt(self, client, token_for, db):
        headers = await token_for("admin:groups:read")
        await client.post("/admin/groups", json={"name": "nope"}, headers=headers)

        (event,) = await events(db)
        assert event.status_code == 403
        assert event.action == "POST /admin/groups"

    async def test_records_the_object_acted_on(self, client, admin_headers, db):
        group = (
            await client.post(
                "/admin/groups", json={"name": "ops"}, headers=admin_headers
            )
        ).json()

        await client.delete(f"/admin/groups/{group['id']}", headers=admin_headers)

        deletion = (await events(db))[0]
        assert deletion.action == "DELETE /admin/groups/{group_id}"
        assert deletion.target == group["id"]

    async def test_names_the_actor_and_the_client(
        self, client, admin_headers, db, admin_user
    ):
        await client.post(
            "/admin/groups", json={"name": "finance"}, headers=admin_headers
        )

        (event,) = await events(db)
        assert event.actor_user_id == admin_user.id
        assert event.actor_label == admin_user.email
        assert event.actor_client == "dashboard"


class TestSecrets:
    async def test_a_password_is_never_stored(self, client, admin_headers, db):
        await client.post(
            "/admin/users",
            json={
                "email": "new@test.local",
                "username": "new",
                "displayName": "New",
                "password": "hunter2-hunter2",
            },
            headers=admin_headers,
        )

        (event,) = await events(db)
        assert event.detail["password"] == "[redacted]"
        assert "hunter2-hunter2" not in str(event.detail)

    async def test_a_failed_login_is_recorded_without_the_password(self, client, db):
        """An unauthenticated attempt has no actor — the submitted email is a
        claim, not an identity, so it stays in the detail."""
        _, challenge = pkce_pair()
        challenge_id = query_of(await start(client, challenge))["challenge"]

        await sign_in(client, challenge_id, password="wrong")

        (event,) = await events(db)
        assert event.action == "POST /api/v1/auth/login"
        assert event.status_code == 401
        assert event.actor_user_id is None
        assert event.detail["password"] == "[redacted]"
        assert event.detail["email"] == "admin@test.local"

    async def test_a_successful_login_names_the_person(self, client, db, admin_user):
        await get_tokens(client)

        actions = {event.action: event for event in await events(db)}
        login = actions["POST /api/v1/auth/login"]
        assert login.status_code == 200
        assert login.actor_user_id == admin_user.id


class TestHistorySurvivesDeletion:
    async def test_deleting_a_user_keeps_what_they_did(self, client, admin_headers, db):
        created = (
            await client.post(
                "/admin/users",
                json={
                    "email": "temp@test.local",
                    "username": "temp",
                    "displayName": "Temp",
                },
                headers=admin_headers,
            )
        ).json()

        await client.delete(f"/admin/users/{created['id']}", headers=admin_headers)
        await db.commit()

        assert await db.get(User, created["id"]) is None
        actions = [event.action for event in await events(db)]
        assert "POST /admin/users" in actions
        assert "DELETE /admin/users/{user_id}" in actions


class TestReadEndpoint:
    async def test_requires_its_own_scope(self, client, token_for):
        headers = await token_for("admin:users:read")
        assert (await client.get("/admin/audit", headers=headers)).status_code == 403

    async def test_lists_newest_first(self, client, admin_headers):
        for name in ("one", "two"):
            await client.post(
                "/admin/groups", json={"name": name}, headers=admin_headers
            )

        body = (await client.get("/admin/audit", headers=admin_headers)).json()

        assert body["meta"]["total"] == 2
        assert body["items"][0]["detail"]["name"] == "two"
        assert body["items"][0]["actorLabel"] == "admin@test.local"

    async def test_filters_by_action(self, client, admin_headers):
        await client.post("/admin/groups", json={"name": "one"}, headers=admin_headers)
        await client.post(
            "/admin/roles", json={"name": "auditor"}, headers=admin_headers
        )

        body = (
            await client.get(
                "/admin/audit", params={"action": "/admin/roles"}, headers=admin_headers
            )
        ).json()

        assert body["meta"]["total"] == 1
        assert body["items"][0]["action"] == "POST /admin/roles"


class TestTokenLifecycle:
    async def test_revocation_is_recorded_without_the_token(self, client, db):
        tokens = await get_tokens(client)

        await client.post(
            "/oauth2/revoke",
            data={"token": tokens["refresh_token"], "client_id": "dashboard"},
        )

        revocation = (await events(db))[0]
        assert revocation.action == "POST /oauth2/revoke"
        assert tokens["refresh_token"] not in str(revocation.detail)

    async def test_logout_is_recorded_despite_being_a_get(self, client, db):
        """RP-initiated logout is a GET by specification and still ends a
        session, so it is the one read-shaped request worth recording."""
        await get_tokens(client)
        await client.get("/oauth2/logout", follow_redirects=False)

        assert "GET /oauth2/logout" in {event.action for event in await events(db)}


class TestOversizedValues:
    """A caller must not be able to act without being recorded.

    Every column in `audit_events` has a width, and a value over it fails the
    insert rather than truncating. The failure is caught — the request has
    already committed — so the entry would simply be missing. Both values below
    are chosen by the caller.
    """

    async def test_a_long_user_agent_still_leaves_a_record(
        self, client, admin_headers, db
    ):
        response = await client.post(
            "/admin/groups",
            json={"name": "engineering"},
            headers={**admin_headers, "user-agent": "A" * 4000},
        )
        assert response.status_code == 201

        (event,) = await events(db)
        assert event.action == "POST /admin/groups"
        assert event.user_agent is not None
        assert len(event.user_agent) <= 512

    async def test_a_long_path_parameter_still_leaves_a_record(
        self, client, admin_headers, db
    ):
        await client.delete("/entity/sessions/" + "b" * 2000, headers=admin_headers)

        (event,) = await events(db)
        assert event.action == "DELETE /entity/sessions/{session_id}"
        assert event.target is not None
        assert len(event.target) <= 255
