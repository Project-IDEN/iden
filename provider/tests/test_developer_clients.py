"""Self-service application registration.

Most of this file is about what a registrant *cannot* do. The endpoints are
open to people outside the organization, so the interesting assertions are the
refusals: someone else's application, a grant nobody offered, a redirect URI
that is not theirs.
"""

import pytest
from sqlalchemy import select

from provider.shared.models import Client
from tests.flows import pkce_pair, query_of, sign_in, start

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

WEB_APP = {
    "name": "Attendance",
    "clientType": "public",
    "redirectUris": ["https://attendance.example.org/callback"],
}
SERVER_APP = {
    "name": "Attendance Server",
    "clientType": "confidential",
    "redirectUris": ["https://attendance.example.org/callback"],
}


async def register(client, headers, body=WEB_APP) -> dict:
    response = await client.post("/developer/clients", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def sign_in_through(client, app: dict, *, scope: str) -> dict:
    """Run the whole flow against a self-registered application, consent and
    all, and return its token response."""
    redirect = app["redirectUris"][0]
    verifier, challenge = pkce_pair()

    started = await start(
        client,
        challenge,
        client_id=app["clientId"],
        redirect_uri=redirect,
        scope=scope,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    login = await sign_in(client, query_of(started)["challenge"])
    resumed = await client.get(login.json()["resumeUrl"])

    assert "/auth/consent" in resumed.headers["location"]
    approval = await client.post(
        "/api/v1/auth/consent",
        json={"challengeId": query_of(resumed)["challenge"], "approved": True},
    )
    delivered = await client.get(approval.json()["redirectUrl"])

    body = {
        "grant_type": "authorization_code",
        "code": query_of(delivered)["code"],
        "redirect_uri": redirect,
        "code_verifier": verifier,
        "client_id": app["clientId"],
    }
    if app.get("clientSecret"):
        body["client_secret"] = app["clientSecret"]

    response = await client.post("/oauth2/token", data=body)
    assert response.status_code == 200, response.text
    return response.json()


class TestRegistration:
    async def test_a_public_application_gets_no_secret(self, client, developer_headers):
        created = await register(client, developer_headers)

        assert created["clientSecret"] is None
        assert created["hasSecret"] is False

    async def test_a_confidential_application_is_handed_its_secret_once(
        self, client, developer_headers
    ):
        created = await register(client, developer_headers, SERVER_APP)
        assert created["clientSecret"]

        fetched = await client.get(
            f"/developer/clients/{created['id']}", headers=developer_headers
        )
        assert "clientSecret" not in fetched.json()

    async def test_the_secret_is_not_stored_in_the_clear(
        self, client, developer_headers, db
    ):
        created = await register(client, developer_headers, SERVER_APP)
        stored = await db.scalar(
            select(Client).where(Client.client_id == created["clientId"])
        )

        assert stored is not None
        assert stored.client_secret_hash != created["clientSecret"]

    async def test_the_client_id_is_generated_not_chosen(
        self, client, developer_headers
    ):
        """A registrant who picked their own could take `dashboard`."""
        created = await register(
            client, developer_headers, WEB_APP | {"clientId": "dashboard"}
        )

        assert created["clientId"] != "dashboard"
        assert created["clientId"].startswith("attendance-")

    async def test_two_applications_of_the_same_name_do_not_collide(
        self, client, developer_headers
    ):
        first = await register(client, developer_headers)
        second = await register(client, developer_headers)

        assert first["clientId"] != second["clientId"]

    async def test_the_application_belongs_to_whoever_registered_it(
        self, client, developer_headers, developer, db
    ):
        created = await register(client, developer_headers)
        stored = await db.scalar(
            select(Client).where(Client.client_id == created["clientId"])
        )

        assert stored is not None
        assert stored.owner_user_id == developer.id

    async def test_the_openid_scopes_are_available_without_any_grant(
        self, client, developer_headers
    ):
        """What makes 'Continue with IDEN' work with no administrator involved."""
        created = await register(client, developer_headers)

        assert set(created["grantableScopes"]) == {
            "openid",
            "profile",
            "email",
            "offline_access",
        }

    async def test_a_redirect_uri_is_required(self, client, developer_headers):
        response = await client.post(
            "/developer/clients",
            json=WEB_APP | {"redirectUris": []},
            headers=developer_headers,
        )

        assert response.status_code == 422


class TestWhatIsNotOnOffer:
    """The fields a registrant does not get to decide.

    Pydantic ignores unknown keys, so each of these asserts the *effect* — that
    the stored client is what the server decided — rather than that the request
    was refused.
    """

    async def test_client_credentials_cannot_be_asked_for(
        self, client, developer_headers, db
    ):
        created = await register(
            client,
            developer_headers,
            SERVER_APP | {"allowedGrants": ["client_credentials"]},
        )
        stored = await db.scalar(
            select(Client).where(Client.client_id == created["clientId"])
        )

        assert stored is not None
        assert stored.allowed_grants == ["authorization_code", "refresh_token"]

    async def test_the_consent_screen_cannot_be_skipped(
        self, client, developer_headers, db
    ):
        created = await register(
            client, developer_headers, WEB_APP | {"skipConsent": True}
        )
        stored = await db.scalar(
            select(Client).where(Client.client_id == created["clientId"])
        )

        assert stored is not None
        assert stored.skip_consent is False

    async def test_an_application_cannot_be_registered_as_a_system_client(
        self, client, developer_headers, db
    ):
        created = await register(
            client, developer_headers, WEB_APP | {"isSystem": True}
        )
        stored = await db.scalar(
            select(Client).where(Client.client_id == created["clientId"])
        )

        assert stored is not None
        assert stored.is_system is False

    async def test_scopes_cannot_be_granted_to_yourself(
        self, client, developer_headers, db, scope_of
    ):
        """The escalation this module exists to prevent: a self-registered
        client holding `admin:users:write` for client_credentials."""
        admin_write = scope_of("admin:users:write")
        created = await register(
            client,
            developer_headers,
            SERVER_APP
            | {
                "grantableScopeIds": [str(admin_write.id)],
                "grantedScopeIds": [str(admin_write.id)],
            },
        )
        stored = await db.scalar(
            select(Client).where(Client.client_id == created["clientId"])
        )

        assert stored is not None
        assert stored.scopes == []
        assert created["grantableScopes"] == [
            "email",
            "offline_access",
            "openid",
            "profile",
        ]

    async def test_a_back_channel_logout_uri_cannot_be_set(
        self, client, developer_headers, db
    ):
        """It would make the provider POST to an address a stranger chose."""
        created = await register(
            client,
            developer_headers,
            WEB_APP
            | {"backchannelLogoutUri": "http://169.254.169.254/latest/meta-data/"},
        )
        stored = await db.scalar(
            select(Client).where(Client.client_id == created["clientId"])
        )

        assert stored is not None
        assert stored.backchannel_logout_uri is None

    async def test_ownership_cannot_be_reassigned(
        self, client, developer_headers, developer, other_developer, db
    ):
        created = await register(
            client,
            developer_headers,
            WEB_APP | {"ownerUserId": str(other_developer.id)},
        )
        stored = await db.scalar(
            select(Client).where(Client.client_id == created["clientId"])
        )

        assert stored is not None
        assert stored.owner_user_id == developer.id


class TestRedirectUriPolicy:
    @pytest.mark.parametrize(
        "uri",
        [
            "https://app.example.org/callback",
            "https://app.example.org:8443/callback?flavour=demo",
            "http://localhost:3000/callback",
            "http://127.0.0.1:19999/callback",
            "com.example.app:/oauth2redirect",
        ],
    )
    async def test_accepted(self, client, developer_headers, uri):
        response = await client.post(
            "/developer/clients",
            json=WEB_APP | {"redirectUris": [uri]},
            headers=developer_headers,
        )

        assert response.status_code == 201, response.text

    @pytest.mark.parametrize(
        "uri",
        [
            "http://app.example.org/callback",  # cleartext off the loopback
            "https://*.example.org/callback",  # wildcard
            "https://app.example.org/callback#fragment",  # RFC 6749 3.1.2
            "https://user:pass@app.example.org/cb",  # credentials
            "https://evil.example.com@app.example.org/cb",  # authority confusion
            "javascript:alert(1)",  # not a URL at all
            "data:text/html,<script>alert(1)</script>",
            "/callback",  # relative
            "https://app.example.org/call\nback",  # whitespace
            "https://app.example.org/cb\x00",  # NUL — not valid UTF-8 to postgres
            "https://app.example.org/cb\x01",  # control character
            "https://\u0430pp.example.org/cb",  # Cyrillic lookalike host
            "https://",  # no host
        ],
    )
    async def test_refused(self, client, developer_headers, uri):
        response = await client.post(
            "/developer/clients",
            json=WEB_APP | {"redirectUris": [uri]},
            headers=developer_headers,
        )

        assert response.status_code == 422, uri

    async def test_a_handful_at_most(self, client, developer_headers):
        response = await client.post(
            "/developer/clients",
            json=WEB_APP
            | {"redirectUris": [f"https://app.example.org/{n}" for n in range(6)]},
            headers=developer_headers,
        )

        assert response.status_code == 422

    async def test_the_same_rules_apply_on_update(self, client, developer_headers):
        created = await register(client, developer_headers)

        response = await client.patch(
            f"/developer/clients/{created['id']}",
            json={"redirectUris": ["http://app.example.org/callback"]},
            headers=developer_headers,
        )

        assert response.status_code == 422


class TestIsolation:
    """One registrant, one set of applications."""

    async def test_the_list_holds_only_your_own(
        self, client, developer_headers, other_developer_headers
    ):
        await register(client, developer_headers)
        await register(client, other_developer_headers)

        mine = await client.get("/developer/clients", headers=developer_headers)

        assert len(mine.json()["applications"]) == 1

    async def test_the_list_excludes_the_organizations_own_clients(
        self, client, developer_headers
    ):
        """`dashboard` and `kiosk` have no owner and belong to nobody here."""
        response = await client.get("/developer/clients", headers=developer_headers)

        assert response.json()["applications"] == []

    @pytest.mark.parametrize(
        ("method", "suffix"),
        [
            ("get", ""),
            ("patch", ""),
            ("post", "/rotate-secret"),
            ("delete", ""),
        ],
    )
    async def test_someone_elses_application_is_not_found(
        self, client, developer_headers, other_developer_headers, method, suffix
    ):
        """404 rather than 403 — a 403 would confirm the id exists."""
        theirs = await register(client, other_developer_headers, SERVER_APP)

        response = await getattr(client, method)(
            f"/developer/clients/{theirs['id']}{suffix}",
            headers=developer_headers,
            **({"json": {}} if method in ("patch", "post") else {}),
        )

        assert response.status_code == 404

    async def test_someone_elses_application_survives_the_attempt(
        self, client, developer_headers, other_developer_headers, db
    ):
        theirs = await register(client, other_developer_headers)

        await client.delete(
            f"/developer/clients/{theirs['id']}", headers=developer_headers
        )

        assert await db.get(Client, theirs["id"]) is not None

    async def test_an_organization_client_cannot_be_touched(
        self, client, developer_headers, dashboard
    ):
        response = await client.delete(
            f"/developer/clients/{dashboard.id}", headers=developer_headers
        )

        assert response.status_code == 404


class TestTheGate:
    async def test_no_token_is_refused(self, client):
        response = await client.get("/developer/clients")

        assert response.status_code == 401

    async def test_a_member_cannot_register_anything(self, client, entity_headers):
        """An ordinary account holds no developer scope.

        401 rather than 403: `aud` is derived from the scopes that survived
        issuance, so a member's token was never minted for the developer API at
        all and fails audience verification before any scope is compared.
        """
        response = await client.post(
            "/developer/clients", json=WEB_APP, headers=entity_headers
        )

        assert response.status_code == 401

    async def test_reading_does_not_imply_writing(
        self, client, token_for, developer, catalogue
    ):
        headers = await token_for("developer:clients:read", user=developer)

        response = await client.post(
            "/developer/clients", json=WEB_APP, headers=headers
        )

        assert response.status_code == 403

    async def test_an_admin_token_does_not_open_this_module(
        self, client, admin_headers
    ):
        """`admin:clients:write` is a different authority against a different
        audience. It opens `/admin/clients`, not someone's own list."""
        response = await client.get("/developer/clients", headers=admin_headers)

        assert response.status_code == 401


class TestQuota:
    async def test_the_cap_is_enforced(self, client, developer_headers, monkeypatch):
        from provider.core.config import settings

        monkeypatch.setattr(settings, "iden_developer_max_clients", 2)

        await register(client, developer_headers)
        await register(client, developer_headers)
        response = await client.post(
            "/developer/clients", json=WEB_APP, headers=developer_headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "application_quota_reached"

    async def test_the_cap_is_per_person(
        self, client, developer_headers, other_developer_headers, monkeypatch
    ):
        from provider.core.config import settings

        monkeypatch.setattr(settings, "iden_developer_max_clients", 1)

        await register(client, developer_headers)
        response = await client.post(
            "/developer/clients", json=WEB_APP, headers=other_developer_headers
        )

        assert response.status_code == 201

    async def test_deleting_one_frees_a_slot(
        self, client, developer_headers, monkeypatch
    ):
        from provider.core.config import settings

        monkeypatch.setattr(settings, "iden_developer_max_clients", 1)

        created = await register(client, developer_headers)
        await client.delete(
            f"/developer/clients/{created['id']}", headers=developer_headers
        )
        response = await client.post(
            "/developer/clients", json=WEB_APP, headers=developer_headers
        )

        assert response.status_code == 201


class TestLifecycle:
    async def test_redirect_uris_can_be_changed(self, client, developer_headers):
        created = await register(client, developer_headers)

        response = await client.patch(
            f"/developer/clients/{created['id']}",
            json={"redirectUris": ["https://attendance.example.org/auth/callback"]},
            headers=developer_headers,
        )

        assert response.json()["redirectUris"] == [
            "https://attendance.example.org/auth/callback"
        ]

    async def test_the_client_type_cannot_be_changed(self, client, developer_headers):
        created = await register(client, developer_headers)

        response = await client.patch(
            f"/developer/clients/{created['id']}",
            json={"clientType": "confidential"},
            headers=developer_headers,
        )

        assert response.json()["clientType"] == "public"

    async def test_rotating_replaces_the_secret(self, client, developer_headers):
        created = await register(client, developer_headers, SERVER_APP)

        rotated = await client.post(
            f"/developer/clients/{created['id']}/rotate-secret",
            headers=developer_headers,
        )

        assert rotated.json()["clientSecret"] != created["clientSecret"]

    async def test_a_public_application_has_no_secret_to_rotate(
        self, client, developer_headers
    ):
        created = await register(client, developer_headers)

        response = await client.post(
            f"/developer/clients/{created['id']}/rotate-secret",
            headers=developer_headers,
        )

        assert response.status_code == 422

    async def test_deleting_removes_it(self, client, developer_headers):
        created = await register(client, developer_headers)

        response = await client.delete(
            f"/developer/clients/{created['id']}", headers=developer_headers
        )
        listed = await client.get("/developer/clients", headers=developer_headers)

        assert response.status_code == 204
        assert listed.json()["applications"] == []

    async def test_the_remaining_allowance_is_reported(
        self, client, developer_headers, monkeypatch
    ):
        from provider.core.config import settings

        monkeypatch.setattr(settings, "iden_developer_max_clients", 3)
        await register(client, developer_headers)

        response = await client.get("/developer/clients", headers=developer_headers)

        assert response.json()["remaining"] == 2


class TestItActuallyWorks:
    """The point of the module: a self-registered application can sign someone
    in, without an administrator touching anything."""

    async def test_continue_with_iden_end_to_end(self, client, developer_headers):
        app = await register(client, developer_headers)

        # `sign_in_through` asserts the consent prompt on the way past, which is
        # the behaviour the registrant cannot switch off.
        tokens = await sign_in_through(client, app, scope="openid profile email")

        assert tokens["id_token"]

    async def test_it_cannot_ask_for_an_admin_scope(self, client, developer_headers):
        """Pruning is silent — the request succeeds and the scope is simply not
        in the token."""
        app = await register(client, developer_headers, SERVER_APP)

        tokens = await sign_in_through(client, app, scope="openid admin:users:write")

        assert "admin:users:write" not in tokens["scope"]

    async def test_it_cannot_use_the_client_credentials_grant(
        self, client, developer_headers
    ):
        app = await register(client, developer_headers, SERVER_APP)

        response = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": app["clientId"],
                "client_secret": app["clientSecret"],
                "scope": "admin:users:write",
            },
        )

        # Refused during client authentication: the grant is not one this
        # client is allowed, so it never reaches the grant handler.
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_client"


class TestWhenThingsGoAway:
    async def test_deleting_an_application_in_use_takes_its_grants_with_it(
        self, client, developer_headers, db
    ):
        """The delete has to survive a client that has actually been used —
        consent grants and refresh tokens both point at it."""
        from provider.shared.models import ConsentGrant, RefreshToken

        app = await register(client, developer_headers)
        await sign_in_through(client, app, scope="openid offline_access")

        response = await client.delete(
            f"/developer/clients/{app['id']}", headers=developer_headers
        )

        assert response.status_code == 204
        assert list(await db.scalars(select(ConsentGrant))) == []
        assert list(await db.scalars(select(RefreshToken))) == []

    async def test_deleting_the_owner_leaves_the_application_standing(
        self, client, developer_headers, developer, admin_headers, db
    ):
        """SET NULL, not CASCADE: it becomes organization-owned and an
        administrator decides what happens to it."""
        app = await register(client, developer_headers)

        await client.delete(f"/admin/users/{developer.id}", headers=admin_headers)
        db.expire_all()
        stored = await db.get(Client, app["id"])

        assert stored is not None
        assert stored.owner_user_id is None


async def test_an_administrator_sees_who_registered_it(
    client, developer_headers, developer, admin_headers
):
    """An event runner has to be able to tell a participant's app from their
    own, and reach the person who registered it."""
    created = await register(client, developer_headers)

    listed = (await client.get("/admin/clients", headers=admin_headers)).json()
    by_id = {item["clientId"]: item for item in listed["items"]}

    assert by_id[created["clientId"]]["ownerUserId"] == str(developer.id)
    assert by_id["dashboard"]["ownerUserId"] is None


async def test_registration_is_audited(client, developer_headers, db):
    """`/developer` is in AUDITED_PREFIXES, so this needed no per-route work."""
    from provider.shared.models import AuditEvent

    created = await register(client, developer_headers)

    events = list(await db.scalars(select(AuditEvent)))

    assert [event.action for event in events] == ["POST /developer/clients"]
    assert events[0].status_code == 201
    assert created["clientSecret"] is None
