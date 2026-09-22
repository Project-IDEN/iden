import pytest

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

NEW_API = {
    "name": "attendance",
    "audience": "https://api.example.org/attendance",
    "description": "Attendance records.",
}


class TestAuthorization:
    async def test_requires_a_token(self, client):
        assert (await client.get("/admin/apis")).status_code == 401

    async def test_read_scope_is_not_enough_to_write(self, client, token_for):
        headers = await token_for("admin:apis:read")
        response = await client.post("/admin/apis", json=NEW_API, headers=headers)

        assert response.status_code == 403
        assert "admin:apis:write" in response.json()["message"]

    async def test_write_scope_is_accepted(self, client, token_for):
        headers = await token_for("admin:apis:write")
        assert (
            await client.post("/admin/apis", json=NEW_API, headers=headers)
        ).status_code == 201


class TestListing:
    async def test_lists_the_system_apis(self, client, admin_headers):
        """Named against the catalogue: `system_apis()` is what the seed
        registers, so a new one does not need this test edited twice."""
        from provider.shared.scopes import system_apis

        body = (await client.get("/admin/apis", headers=admin_headers)).json()
        expected = {spec.name for spec in system_apis()}

        assert {api["name"] for api in body["items"]} == expected
        assert body["meta"]["total"] == len(expected)

    async def test_reports_scope_counts(self, client, admin_headers):
        """Counted against the catalogue rather than a literal, so adding a
        scope does not require editing this test."""
        from provider.shared.scopes import (
            ADMIN_SCOPES,
            DEVELOPER_SCOPES,
            ENTITY_SCOPES,
        )

        body = (await client.get("/admin/apis", headers=admin_headers)).json()
        by_name = {api["name"]: api for api in body["items"]}

        assert by_name["admin"]["scopeCount"] == len(ADMIN_SCOPES)
        assert by_name["entity"]["scopeCount"] == len(ENTITY_SCOPES)
        assert by_name["developer"]["scopeCount"] == len(DEVELOPER_SCOPES)

    async def test_pagination_limits_and_reports_total(self, client, admin_headers):
        from provider.shared.scopes import system_apis

        body = (await client.get("/admin/apis?limit=1", headers=admin_headers)).json()

        assert len(body["items"]) == 1
        assert body["meta"] == {
            "total": len(system_apis()),
            "limit": 1,
            "offset": 0,
        }


class TestCreation:
    async def test_creates_an_api(self, client, admin_headers):
        response = await client.post("/admin/apis", json=NEW_API, headers=admin_headers)
        body = response.json()

        assert response.status_code == 201
        assert body["audience"] == NEW_API["audience"]
        assert body["isSystem"] is False
        assert body["scopeCount"] == 0

    async def test_duplicate_name_is_rejected(self, client, admin_headers):
        await client.post("/admin/apis", json=NEW_API, headers=admin_headers)
        again = await client.post(
            "/admin/apis",
            json=NEW_API | {"audience": "https://other.test"},
            headers=admin_headers,
        )

        assert again.status_code == 409
        assert again.json()["code"] == "api_name_taken"

    async def test_duplicate_audience_is_rejected(self, client, admin_headers):
        await client.post("/admin/apis", json=NEW_API, headers=admin_headers)
        again = await client.post(
            "/admin/apis", json=NEW_API | {"name": "other"}, headers=admin_headers
        )

        assert again.status_code == 409
        assert again.json()["code"] == "audience_taken"

    @pytest.mark.parametrize("audience", ["not-a-uri", "example.org/api", ""])
    async def test_audience_must_be_absolute(self, client, admin_headers, audience):
        response = await client.post(
            "/admin/apis", json=NEW_API | {"audience": audience}, headers=admin_headers
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "name", ["Attendance", "attendance api", "1attendance", ""]
    )
    async def test_name_must_be_lowercase_slug(self, client, admin_headers, name):
        response = await client.post(
            "/admin/apis", json=NEW_API | {"name": name}, headers=admin_headers
        )
        assert response.status_code == 422

    async def test_trailing_slash_is_normalized_away(self, client, admin_headers):
        """Otherwise two audiences differing only by a slash would both exist and
        tokens would validate against only one of them."""
        body = (
            await client.post(
                "/admin/apis",
                json=NEW_API | {"audience": "https://api.example.org/attendance/"},
                headers=admin_headers,
            )
        ).json()

        assert body["audience"] == "https://api.example.org/attendance"


class TestSystemApiProtection:
    async def test_system_api_cannot_be_updated(self, client, admin_headers):
        listing = (await client.get("/admin/apis", headers=admin_headers)).json()
        admin_api = next(a for a in listing["items"] if a["name"] == "admin")

        response = await client.patch(
            f"/admin/apis/{admin_api['id']}",
            json={"name": "renamed"},
            headers=admin_headers,
        )

        assert response.status_code == 409
        assert response.json()["code"] == "system_api_immutable"

    async def test_system_api_cannot_be_deleted(self, client, admin_headers):
        """Deleting the admin API would remove the scopes that let anyone
        administer the deployment — a one-way door."""
        listing = (await client.get("/admin/apis", headers=admin_headers)).json()
        admin_api = next(a for a in listing["items"] if a["name"] == "admin")

        response = await client.delete(
            f"/admin/apis/{admin_api['id']}", headers=admin_headers
        )
        assert response.status_code == 409


class TestDeletion:
    async def test_deletes_an_unused_api(self, client, admin_headers):
        created = (
            await client.post("/admin/apis", json=NEW_API, headers=admin_headers)
        ).json()

        assert (
            await client.delete(f"/admin/apis/{created['id']}", headers=admin_headers)
        ).status_code == 204
        assert (
            await client.get(f"/admin/apis/{created['id']}", headers=admin_headers)
        ).status_code == 404

    async def test_refuses_while_its_scopes_are_granted(self, client, admin_headers):
        api = (
            await client.post("/admin/apis", json=NEW_API, headers=admin_headers)
        ).json()
        scope = (
            await client.post(
                f"/admin/apis/{api['id']}/scopes",
                json={
                    "value": "attendance:records:read",
                    "description": "Read records.",
                },
                headers=admin_headers,
            )
        ).json()
        await client.post(
            "/admin/roles",
            json={"name": "officer", "scopeIds": [scope["id"]]},
            headers=admin_headers,
        )

        response = await client.delete(
            f"/admin/apis/{api['id']}", headers=admin_headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "api_in_use"

    async def test_force_deletes_anyway(self, client, admin_headers):
        api = (
            await client.post("/admin/apis", json=NEW_API, headers=admin_headers)
        ).json()
        scope = (
            await client.post(
                f"/admin/apis/{api['id']}/scopes",
                json={
                    "value": "attendance:records:read",
                    "description": "Read records.",
                },
                headers=admin_headers,
            )
        ).json()
        await client.post(
            "/admin/roles",
            json={"name": "officer", "scopeIds": [scope["id"]]},
            headers=admin_headers,
        )

        response = await client.delete(
            f"/admin/apis/{api['id']}?force=true", headers=admin_headers
        )
        assert response.status_code == 204

    async def test_unknown_api_is_404(self, client, admin_headers):
        missing = "00000000-0000-0000-0000-000000000000"
        assert (
            await client.get(f"/admin/apis/{missing}", headers=admin_headers)
        ).status_code == 404
