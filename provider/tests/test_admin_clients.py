import pytest

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

WEB_APP = {
    "clientId": "library-web",
    "name": "Library",
    "clientType": "public",
    "allowedGrants": ["authorization_code", "refresh_token"],
    "redirectUris": ["https://library.example.org/callback"],
}
SERVICE = {
    "clientId": "nightly-job",
    "name": "Nightly Job",
    "clientType": "confidential",
    "allowedGrants": ["client_credentials"],
}


class TestRegistration:
    async def test_confidential_client_secret_is_shown_once(
        self, client, admin_headers
    ):
        created = (
            await client.post("/admin/clients", json=SERVICE, headers=admin_headers)
        ).json()
        assert created["clientSecret"]

        fetched = (
            await client.get(f"/admin/clients/{created['id']}", headers=admin_headers)
        ).json()
        assert "clientSecret" not in fetched

    async def test_public_client_gets_no_secret(self, client, admin_headers):
        """It has nowhere to keep one — PKCE is what proves it."""
        created = (
            await client.post("/admin/clients", json=WEB_APP, headers=admin_headers)
        ).json()
        assert created["clientSecret"] is None

    async def test_secret_is_not_stored_in_the_clear(self, client, admin_headers, db):
        from sqlalchemy import select

        from provider.shared.models import Client

        created = (
            await client.post("/admin/clients", json=SERVICE, headers=admin_headers)
        ).json()
        stored = await db.scalar(
            select(Client).where(Client.client_id == "nightly-job")
        )

        assert stored.client_secret_hash != created["clientSecret"]

    async def test_authorization_code_grant_requires_a_redirect_uri(
        self, client, admin_headers
    ):
        response = await client.post(
            "/admin/clients", json=WEB_APP | {"redirectUris": []}, headers=admin_headers
        )

        assert response.status_code == 422
        assert response.json()["code"] == "redirect_uri_required"

    async def test_relative_redirect_uri_is_rejected(self, client, admin_headers):
        response = await client.post(
            "/admin/clients",
            json=WEB_APP | {"redirectUris": ["/callback"]},
            headers=admin_headers,
        )
        assert response.status_code == 422

    async def test_duplicate_client_id_is_rejected(self, client, admin_headers):
        await client.post("/admin/clients", json=WEB_APP, headers=admin_headers)
        again = await client.post("/admin/clients", json=WEB_APP, headers=admin_headers)

        assert again.status_code == 409


class TestSecretRotation:
    async def test_rotation_invalidates_the_previous_secret(
        self, client, admin_headers, catalogue
    ):
        created = (
            await client.post("/admin/clients", json=SERVICE, headers=admin_headers)
        ).json()
        old_secret = created["clientSecret"]

        rotated = (
            await client.post(
                f"/admin/clients/{created['id']}/rotate-secret", headers=admin_headers
            )
        ).json()

        assert rotated["clientSecret"] != old_secret

        with_old = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "nightly-job",
                "client_secret": old_secret,
            },
        )
        assert with_old.status_code == 401

        with_new = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "nightly-job",
                "client_secret": rotated["clientSecret"],
            },
        )
        assert with_new.status_code == 200

    async def test_public_client_cannot_rotate(self, client, admin_headers):
        created = (
            await client.post("/admin/clients", json=WEB_APP, headers=admin_headers)
        ).json()
        response = await client.post(
            f"/admin/clients/{created['id']}/rotate-secret", headers=admin_headers
        )

        assert response.status_code == 422
        assert response.json()["code"] == "public_client_has_no_secret"


class TestClientScopes:
    async def test_grantable_and_granted_are_independent(
        self, client, admin_headers, catalogue
    ):
        created = (
            await client.post("/admin/clients", json=SERVICE, headers=admin_headers)
        ).json()
        read = str(catalogue["scopes"]["entity:profile:read"].id)
        write = str(catalogue["scopes"]["entity:profile:write"].id)

        body = (
            await client.put(
                f"/admin/clients/{created['id']}/scopes",
                json={"grantableScopeIds": [read], "grantedScopeIds": [write]},
                headers=admin_headers,
            )
        ).json()

        assert [s["value"] for s in body["grantableScopes"]] == ["entity:profile:read"]
        assert [s["value"] for s in body["grantedScopes"]] == ["entity:profile:write"]

    async def test_put_replaces_both_sets(self, client, admin_headers, catalogue):
        created = (
            await client.post("/admin/clients", json=SERVICE, headers=admin_headers)
        ).json()
        read = str(catalogue["scopes"]["entity:profile:read"].id)

        await client.put(
            f"/admin/clients/{created['id']}/scopes",
            json={"grantableScopeIds": [read], "grantedScopeIds": [read]},
            headers=admin_headers,
        )
        emptied = (
            await client.put(
                f"/admin/clients/{created['id']}/scopes",
                json={"grantableScopeIds": [], "grantedScopeIds": []},
                headers=admin_headers,
            )
        ).json()

        assert emptied["grantableScopes"] == [] and emptied["grantedScopes"] == []

    async def test_granted_scopes_reach_a_client_credentials_token(
        self, client, admin_headers, catalogue
    ):
        created = (
            await client.post("/admin/clients", json=SERVICE, headers=admin_headers)
        ).json()
        scope_id = str(catalogue["scopes"]["entity:profile:read"].id)

        await client.put(
            f"/admin/clients/{created['id']}/scopes",
            json={"grantableScopeIds": [], "grantedScopeIds": [scope_id]},
            headers=admin_headers,
        )

        token = (
            await client.post(
                "/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "nightly-job",
                    "client_secret": created["clientSecret"],
                    "scope": "entity:profile:read",
                },
            )
        ).json()

        assert token["scope"] == "entity:profile:read"


class TestProtection:
    async def test_bootstrap_client_cannot_be_deleted(
        self, client, admin_headers, db, dashboard
    ):
        dashboard.is_system = True
        db.add(dashboard)
        await db.commit()

        response = await client.delete(
            f"/admin/clients/{dashboard.id}", headers=admin_headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "system_client_immutable"

    async def test_read_scope_cannot_register_a_client(self, client, token_for):
        headers = await token_for("admin:clients:read")
        response = await client.post("/admin/clients", json=WEB_APP, headers=headers)
        assert response.status_code == 403


class TestChangingAClientNeedsAFullAdministrator:
    """A client's configuration decides who receives its tokens, so whoever
    controls it can act as anyone who signs in through it. Only a caller who
    already holds every restricted scope has nothing to gain from that."""

    @pytest.fixture
    async def almost_full_headers(self, token_for, catalogue):
        """Every admin scope but one unrelated to clients."""
        return await token_for(
            *[
                value
                for value in catalogue["scopes"]
                if value.startswith("admin:") and value != "admin:audit:read"
            ]
        )

    @pytest.fixture
    async def existing(self, client, admin_headers):
        return (
            await client.post("/admin/clients", json=SERVICE, headers=admin_headers)
        ).json()

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("POST", "/admin/clients", WEB_APP),
            ("PATCH", "/admin/clients/{id}", {"name": "Renamed"}),
            ("PUT", "/admin/clients/{id}/scopes", {}),
            ("POST", "/admin/clients/{id}/rotate-secret", None),
            ("DELETE", "/admin/clients/{id}", None),
        ],
    )
    async def test_every_write_is_refused_short_of_it(
        self, client, almost_full_headers, existing, method, path, body
    ):
        response = await client.request(
            method,
            path.format(id=existing["id"]),
            json=body,
            headers=almost_full_headers,
        )

        assert response.status_code == 403
        assert "insufficient_scope" in response.headers["www-authenticate"]
        assert "admin:audit:read" in response.json()["message"]

    async def test_reading_still_needs_only_the_read_scope(
        self, client, token_for, existing
    ):
        headers = await token_for("admin:clients:read")
        response = await client.get(f"/admin/clients/{existing['id']}", headers=headers)

        assert response.status_code == 200

    async def test_the_dashboard_cannot_be_repointed(
        self, client, almost_full_headers, dashboard
    ):
        """The takeover: add your own redirect URI to the client that skips
        consent and may request every admin scope, then send an administrator
        a link. Their code would arrive at your site."""
        response = await client.patch(
            f"/admin/clients/{dashboard.id}",
            json={"redirectUris": ["https://evil.example/cb"]},
            headers=almost_full_headers,
        )

        assert response.status_code == 403

    async def test_the_gate_is_every_restricted_scope_in_the_catalogue(self, catalogue):
        from provider.shared.scopes import FULL_ADMIN_SCOPES, RESTRICTED_PREFIXES

        restricted = {
            value
            for value in catalogue["scopes"]
            if value.split(":")[0] in RESTRICTED_PREFIXES
        }
        assert restricted == set(FULL_ADMIN_SCOPES)


class TestDeveloperApplications:
    """Their owner can repoint the redirect URIs, so a restricted scope on one
    would let a developer collect administrators' tokens."""

    @pytest.fixture
    async def owned(self, client, developer_headers):
        return (
            await client.post(
                "/developer/clients",
                json={
                    "name": "Owned",
                    "clientType": "public",
                    "redirectUris": ["https://owned.example.org/cb"],
                },
                headers=developer_headers,
            )
        ).json()

    async def test_cannot_be_given_a_restricted_scope(
        self, client, admin_headers, owned, catalogue
    ):
        response = await client.put(
            f"/admin/clients/{owned['id']}/scopes",
            json={
                "grantableScopeIds": [str(catalogue["scopes"]["admin:users:read"].id)]
            },
            headers=admin_headers,
        )

        assert response.status_code == 422
        assert response.json()["code"] == "restricted_scope_on_owned_client"

    async def test_can_be_given_an_organizations_own_scope(
        self, client, admin_headers, owned, unheld_scope
    ):
        response = await client.put(
            f"/admin/clients/{owned['id']}/scopes",
            json={"grantableScopeIds": [str(unheld_scope.id)]},
            headers=admin_headers,
        )

        assert response.status_code == 200
