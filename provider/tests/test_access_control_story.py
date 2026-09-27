"""The whole point of Phase 2, exercised end to end.

An administrator defines a permission for a backend that IDEN has never heard
of, routes it to people through a role and a group, and a token comes out the
other side carrying it — with no code change and no redeploy.
"""

import jwt
import pytest

from tests.conftest import REDIRECT_URI
from tests.flows import pkce_pair, query_of, sign_in, start

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

PASSWORD = "a-perfectly-fine-password"
AUDIENCE = "https://api.example.org/attendance"
SCOPE = "attendance:records:read"


async def sign_in_as(client, email: str, scope: str) -> dict:
    """Run the authorization code flow as a given user, returning the token response."""
    verifier, challenge = pkce_pair()

    response = await start(client, challenge, scope=scope)
    challenge_id = query_of(response)["challenge"]

    login = await sign_in(client, challenge_id, email=email, password=PASSWORD)
    resumed = await client.get(login.json()["resumeUrl"])
    code = query_of(resumed)["code"]

    return (
        await client.post(
            "/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
                "client_id": "dashboard",
            },
        )
    ).json()


@pytest.fixture
async def attendance(client, admin_headers):
    """A third-party API, its permission, a role, and a group that holds it."""
    api = (
        await client.post(
            "/admin/apis",
            json={"name": "attendance", "audience": AUDIENCE},
            headers=admin_headers,
        )
    ).json()

    scope = (
        await client.post(
            f"/admin/apis/{api['id']}/scopes",
            json={"value": SCOPE, "description": "View attendance records."},
            headers=admin_headers,
        )
    ).json()

    role = (
        await client.post(
            "/admin/roles",
            json={"name": "attendance-officer", "scopeIds": [scope["id"]]},
            headers=admin_headers,
        )
    ).json()

    group = (
        await client.post(
            "/admin/groups", json={"name": "Registrar"}, headers=admin_headers
        )
    ).json()
    await client.put(
        f"/admin/groups/{group['id']}/roles",
        json={"roleIds": [role["id"]]},
        headers=admin_headers,
    )

    # The dashboard must also be allowed to *ask* for it — holding a permission
    # and being able to request it are separate decisions.
    dashboard_id = next(
        c["id"]
        for c in (await client.get("/admin/clients", headers=admin_headers)).json()[
            "items"
        ]
        if c["clientId"] == "dashboard"
    )
    await client.put(
        f"/admin/clients/{dashboard_id}/scopes",
        json={"grantableScopeIds": [scope["id"]], "grantedScopeIds": []},
        headers=admin_headers,
    )

    return {"api": api, "scope": scope, "role": role, "group": group}


@pytest.fixture
async def officer(client, admin_headers, attendance):
    user = (
        await client.post(
            "/admin/users",
            json={
                "emailLocalPart": "officer",
                "username": "officer",
                "password": PASSWORD,
            },
            headers=admin_headers,
        )
    ).json()
    await client.post(
        f"/admin/groups/{attendance['group']['id']}/members",
        json={"userIds": [user["id"]]},
        headers=admin_headers,
    )
    return user


@pytest.fixture
async def outsider(client, admin_headers):
    return (
        await client.post(
            "/admin/users",
            json={
                "emailLocalPart": "outsider",
                "username": "outsider",
                "password": PASSWORD,
            },
            headers=admin_headers,
        )
    ).json()


async def test_a_runtime_defined_permission_reaches_a_token(
    client, admin_headers, officer
):
    tokens = await sign_in_as(client, "officer@test.local", f"openid {SCOPE}")
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})

    assert SCOPE in claims["scope"].split()
    assert AUDIENCE in claims["aud"]


async def test_provenance_explains_where_it_came_from(client, admin_headers, officer):
    body = (
        await client.get(
            f"/admin/users/{officer['id']}/effective-scopes", headers=admin_headers
        )
    ).json()
    entry = next(s for s in body["scopes"] if s["value"] == SCOPE)

    assert entry["viaGroups"] == ["Registrar → attendance-officer"]
    assert entry["viaRoles"] == [] and entry["viaDirect"] is False


async def test_someone_outside_the_group_is_pruned_silently(
    client, outsider, attendance
):
    """Asking for more than you hold yields a narrower token, not an error."""
    tokens = await sign_in_as(client, "outsider@test.local", f"openid {SCOPE}")
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})

    assert SCOPE not in claims["scope"].split()
    assert claims["scope"] == "openid"


async def test_removing_the_user_from_the_group_revokes_it_at_the_next_token(
    client, admin_headers, officer, attendance
):
    """Permissions are evaluated at issuance — which is why access tokens are
    short-lived rather than long-lived."""
    first = await sign_in_as(
        client, "officer@test.local", f"openid offline_access {SCOPE}"
    )
    assert (
        SCOPE
        in jwt.decode(first["access_token"], options={"verify_signature": False})[
            "scope"
        ]
    )

    await client.delete(
        f"/admin/groups/{attendance['group']['id']}/members/{officer['id']}",
        headers=admin_headers,
    )

    refreshed = (
        await client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": "dashboard",
            },
        )
    ).json()

    assert SCOPE not in refreshed["scope"].split()


async def test_taking_the_scope_off_the_role_revokes_it_for_everyone(
    client, admin_headers, officer, attendance
):
    first = await sign_in_as(
        client, "officer@test.local", f"openid offline_access {SCOPE}"
    )

    await client.put(
        f"/admin/roles/{attendance['role']['id']}/scopes",
        json={"scopeIds": []},
        headers=admin_headers,
    )

    refreshed = (
        await client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": "dashboard",
            },
        )
    ).json()

    assert SCOPE not in refreshed["scope"].split()


async def test_a_client_not_allowed_to_request_it_cannot_obtain_it(
    client, admin_headers, officer, attendance
):
    """Holding a permission and being able to request it are separate gates."""
    dashboard_id = next(
        c["id"]
        for c in (await client.get("/admin/clients", headers=admin_headers)).json()[
            "items"
        ]
        if c["clientId"] == "dashboard"
    )
    await client.put(
        f"/admin/clients/{dashboard_id}/scopes",
        json={"grantableScopeIds": [], "grantedScopeIds": []},
        headers=admin_headers,
    )

    tokens = await sign_in_as(client, "officer@test.local", f"openid {SCOPE}")
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})

    assert SCOPE not in claims["scope"].split()


async def test_the_new_scope_is_advertised_in_discovery(client, attendance):
    body = (await client.get("/.well-known/openid-configuration")).json()
    assert SCOPE in body["scopes_supported"]
