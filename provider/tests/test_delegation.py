"""Nobody can hand out authority they do not hold.

Two changes together. `admin:grants:write` decides *whether* an account may
assign permissions at all, split out of `admin:users:write` so that managing
people and empowering them stop being the same privilege. The delegation rule
decides *which* — because the scope that lets you assign roles otherwise lets you
assign the role that contains it, which makes the first change decorative.

The interesting cases are the indirect ones. A scope reaches somebody by being
named, by a role, by a group's roles, by joining such a group, by the meaning of
a role changing underneath them, and by a client holding it in its own right.
Each is a separate endpoint and each is tested here, because five closed doors
and one open one is one open door.
"""

import pytest

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

# Held by the restricted administrator below. Everything they are refused is
# something outside this set.
LIMITED = (
    "admin:users:read",
    "admin:users:write",
    "admin:grants:write",
    "admin:roles:read",
    "admin:roles:write",
    "admin:groups:read",
    "admin:groups:write",
    "admin:clients:read",
    "admin:clients:write",
    "admin:scopes:read",
)

# Deliberately not held: an `admin:` scope, so restricted, and a real one.
WITHHELD = "admin:scopes:write"


@pytest.fixture
async def limited_headers(token_for):
    """An administrator who can assign permissions, but not every permission."""
    return await token_for(*LIMITED)


@pytest.fixture
async def scope_id(client, admin_headers):
    """The id of the withheld scope, looked up the way a caller would."""

    async def _id(value: str) -> str:
        apis = (await client.get("/admin/apis", headers=admin_headers)).json()
        for api in apis["items"]:
            page = await client.get(
                f"/admin/apis/{api['id']}/scopes",
                params={"limit": 200},
                headers=admin_headers,
            )
            for scope in page.json()["items"]:
                if scope["value"] == value:
                    return scope["id"]
        raise AssertionError(f"no scope {value}")

    return _id


@pytest.fixture
async def elevated_role(client, admin_headers, scope_id):
    """A role carrying the scope the limited administrator does not hold."""
    role = (
        await client.post(
            "/admin/roles", json={"name": "scope-admin"}, headers=admin_headers
        )
    ).json()
    await client.put(
        f"/admin/roles/{role['id']}/scopes",
        json={"scopeIds": [await scope_id(WITHHELD)]},
        headers=admin_headers,
    )
    return role


@pytest.fixture
async def target(client, admin_headers):
    return (
        await client.post(
            "/admin/users",
            json={"email": "t@test.local", "username": "target"},
            headers=admin_headers,
        )
    ).json()


class TestTheScopeSplit:
    """`admin:users:write` no longer carries the power to grant."""

    async def test_it_still_creates_and_resets(self, client, token_for):
        headers = await token_for("admin:users:write", "admin:users:read")

        created = await client.post(
            "/admin/users",
            json={"email": "new@test.local", "username": "newcomer"},
            headers=headers,
        )
        assert created.status_code == 201

        reset = await client.post(
            f"/admin/users/{created.json()['id']}/reset-password",
            json={},
            headers=headers,
        )
        assert reset.status_code == 200

    async def test_it_no_longer_assigns_roles(self, client, token_for, target):
        headers = await token_for("admin:users:write")

        response = await client.put(
            f"/admin/users/{target['id']}/roles",
            json={"roleIds": []},
            headers=headers,
        )

        assert response.status_code == 403
        assert "admin:grants:write" in response.headers["www-authenticate"]

    async def test_it_no_longer_assigns_scopes(self, client, token_for, target):
        headers = await token_for("admin:users:write")

        response = await client.put(
            f"/admin/users/{target['id']}/scopes",
            json={"scopeIds": []},
            headers=headers,
        )

        assert response.status_code == 403

    async def test_grants_write_is_what_assigns(self, client, token_for, target):
        headers = await token_for("admin:grants:write", "admin:users:read")

        response = await client.put(
            f"/admin/users/{target['id']}/roles",
            json={"roleIds": []},
            headers=headers,
        )

        assert response.status_code == 200


class TestDelegationIsRefused:
    """Six ways a scope reaches somebody, and none of them is a way around."""

    async def test_by_direct_grant(self, client, limited_headers, target, scope_id):
        response = await client.put(
            f"/admin/users/{target['id']}/scopes",
            json={"scopeIds": [await scope_id(WITHHELD)]},
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_delegate"
        assert WITHHELD in response.json()["message"]

    async def test_by_role_assignment(
        self, client, limited_headers, target, elevated_role
    ):
        response = await client.put(
            f"/admin/users/{target['id']}/roles",
            json={"roleIds": [elevated_role["id"]]},
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_delegate"

    async def test_by_creating_a_user_that_already_holds_it(
        self, client, limited_headers, elevated_role
    ):
        """The most tempting one: the response carries a password for the
        account it just made, so an escalation here needs no second step."""
        response = await client.post(
            "/admin/users",
            json={
                "email": "backdoor@test.local",
                "username": "backdoor",
                "roleIds": [elevated_role["id"]],
            },
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_delegate"

    async def test_by_a_group_role(self, client, limited_headers, elevated_role):
        group = (
            await client.post(
                "/admin/groups", json={"name": "Staff"}, headers=limited_headers
            )
        ).json()

        response = await client.put(
            f"/admin/groups/{group['id']}/roles",
            json={"roleIds": [elevated_role["id"]]},
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_delegate"

    async def test_by_joining_a_group_that_already_has_it(
        self, client, admin_headers, limited_headers, elevated_role, target
    ):
        """Membership confers the group's roles — including on the caller, if
        they add themselves."""
        group = (
            await client.post(
                "/admin/groups", json={"name": "Elevated"}, headers=admin_headers
            )
        ).json()
        await client.put(
            f"/admin/groups/{group['id']}/roles",
            json={"roleIds": [elevated_role["id"]]},
            headers=admin_headers,
        )

        response = await client.post(
            f"/admin/groups/{group['id']}/members",
            json={"userIds": [target["id"]]},
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_delegate"

    async def test_by_redefining_a_role_from_underneath(
        self, client, limited_headers, scope_id
    ):
        """Editing what a role means promotes everybody already holding it."""
        role = (
            await client.post(
                "/admin/roles", json={"name": "innocuous"}, headers=limited_headers
            )
        ).json()

        response = await client.put(
            f"/admin/roles/{role['id']}/scopes",
            json={"scopeIds": [await scope_id(WITHHELD)]},
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_delegate"

    async def test_by_creating_a_role_that_has_it(
        self, client, limited_headers, scope_id
    ):
        response = await client.post(
            "/admin/roles",
            json={"name": "sneaky", "scopeIds": [await scope_id(WITHHELD)]},
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_delegate"

    async def test_by_registering_a_client_that_holds_it(
        self, client, limited_headers, scope_id
    ):
        """The second complete escalation path, and the quieter one: a
        confidential client holding a scope outright is one
        `client_credentials` request away from using it, with a secret the
        caller is shown once."""
        response = await client.post(
            "/admin/clients",
            json={
                "clientId": "backdoor",
                "name": "Back Door",
                "clientType": "confidential",
                "allowedGrants": ["client_credentials"],
                "grantedScopeIds": [await scope_id(WITHHELD)],
            },
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_delegate"

    async def test_by_adding_it_to_an_existing_client(
        self, client, limited_headers, scope_id
    ):
        created = (
            await client.post(
                "/admin/clients",
                json={
                    "clientId": "later",
                    "name": "Later",
                    "clientType": "confidential",
                    "allowedGrants": ["client_credentials"],
                },
                headers=limited_headers,
            )
        ).json()

        response = await client.put(
            f"/admin/clients/{created['id']}/scopes",
            json={
                "grantableScopeIds": [],
                "grantedScopeIds": [await scope_id(WITHHELD)],
            },
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_delegate"


class TestDelegationIsAllowed:
    """The rule has to leave an administrator able to administer."""

    async def test_a_scope_the_caller_holds(
        self, client, limited_headers, target, scope_id
    ):
        response = await client.put(
            f"/admin/users/{target['id']}/scopes",
            json={"scopeIds": [await scope_id("admin:users:read")]},
            headers=limited_headers,
        )

        assert response.status_code == 200
        assert "admin:users:read" in response.json()["directScopes"]

    async def test_an_organizations_own_scope_the_caller_does_not_hold(
        self, client, limited_headers, target, unheld_scope
    ):
        """The point of an identity provider is granting permissions you do not
        personally need. Requiring the registrar to hold
        `library:loans:read` before granting it would mean holding every
        permission in the organization."""
        response = await client.put(
            f"/admin/users/{target['id']}/scopes",
            json={"scopeIds": [str(unheld_scope.id)]},
            headers=limited_headers,
        )

        assert response.status_code == 200
        assert "library:loans:read" in response.json()["directScopes"]

    async def test_a_self_service_scope_the_caller_does_not_hold(
        self, client, token_for, target, scope_id
    ):
        """`entity:` is absent from the restricted set: holding
        `entity:profile:write` lets you edit your own profile and nobody
        else's, so granting it raises the grantee's authority over themselves
        and the granter's over nothing."""
        headers = await token_for("admin:grants:write", "admin:users:read")

        response = await client.put(
            f"/admin/users/{target['id']}/scopes",
            json={"scopeIds": [await scope_id("entity:profile:write")]},
            headers=headers,
        )

        assert response.status_code == 200

    async def test_a_client_that_already_holds_more_is_off_limits_entirely(
        self, client, admin_headers, limited_headers, scope_id, unheld_scope
    ):
        """Not merely the scope that is beyond them — the whole client.

        An earlier version of this rule checked only what an edit newly
        conferred, on the reasoning that a scope already present is not being
        granted again. That reasoning is wrong for a client: what it already
        holds becomes usable the moment somebody adds the `client_credentials`
        grant and rotates the secret, and neither of those is a scope
        assignment. See `TestActingOnAClientAboveYou`.
        """
        created = (
            await client.post(
                "/admin/clients",
                json={
                    "clientId": "existing",
                    "name": "Existing",
                    "clientType": "confidential",
                    "allowedGrants": ["client_credentials"],
                    "grantedScopeIds": [await scope_id(WITHHELD)],
                },
                headers=admin_headers,
            )
        ).json()

        response = await client.put(
            f"/admin/clients/{created['id']}/scopes",
            json={
                "grantableScopeIds": [str(unheld_scope.id)],
                "grantedScopeIds": [await scope_id(WITHHELD)],
            },
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_administer"

    async def test_a_full_administrator_is_unaffected(
        self, client, admin_headers, target, scope_id
    ):
        response = await client.put(
            f"/admin/users/{target['id']}/scopes",
            json={"scopeIds": [await scope_id(WITHHELD)]},
            headers=admin_headers,
        )

        assert response.status_code == 200


class TestActingOnSomebodyAboveYou:
    """The other half of the rule, and the one that is easy to miss.

    Delegation stops an administrator *granting* authority they lack. This stops
    them *borrowing* it: managing a person includes resetting their password and
    clearing their authenticator, and those two together are a way to become
    them. Without it, `admin:users:write` would still reach every permission —
    by way of whoever already holds it — and splitting `admin:grants:write` out
    would have bought nothing at all.
    """

    @pytest.fixture
    async def helpdesk(self, token_for):
        """Manages people. Assigns nothing."""
        return await token_for("admin:users:read", "admin:users:write")

    async def test_their_password_cannot_be_reset(self, client, helpdesk, admin_user):
        response = await client.post(
            f"/admin/users/{admin_user.id}/reset-password", json={}, headers=helpdesk
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_administer"

    async def test_their_authenticator_cannot_be_cleared(
        self, client, helpdesk, admin_user, db
    ):
        """The step that completes the takeover: reset the password of someone
        more privileged, then remove the factor that would have stopped you."""
        from tests.test_auth_code_flow import enrol

        await enrol(db, admin_user)

        response = await client.delete(
            f"/admin/users/{admin_user.id}/totp", headers=helpdesk
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_administer"

    async def test_they_cannot_be_deactivated(self, client, helpdesk, admin_user):
        response = await client.patch(
            f"/admin/users/{admin_user.id}",
            json={"isActive": False},
            headers=helpdesk,
        )

        assert response.status_code == 403

    async def test_they_cannot_be_deleted(self, client, helpdesk, admin_user):
        response = await client.delete(
            f"/admin/users/{admin_user.id}", headers=helpdesk
        )

        assert response.status_code == 403

    async def test_their_roles_cannot_be_stripped(
        self, client, limited_headers, admin_user
    ):
        """Even with `admin:grants:write`: demoting somebody above you is not
        delegation, but it is still acting on an account you do not outrank."""
        response = await client.put(
            f"/admin/users/{admin_user.id}/roles",
            json={"roleIds": []},
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_administer"

    async def test_an_ordinary_account_is_still_managed_normally(
        self, client, helpdesk, target
    ):
        """The help-desk account has to remain useful for what it is for."""
        reset = await client.post(
            f"/admin/users/{target['id']}/reset-password", json={}, headers=helpdesk
        )
        cleared = await client.delete(
            f"/admin/users/{target['id']}/totp", headers=helpdesk
        )
        renamed = await client.patch(
            f"/admin/users/{target['id']}",
            json={"displayName": "Renamed"},
            headers=helpdesk,
        )

        assert reset.status_code == 200
        assert cleared.status_code == 204
        assert renamed.status_code == 200

    async def test_a_full_administrator_may_act_on_a_peer(
        self, client, admin_headers, admin_user
    ):
        response = await client.post(
            f"/admin/users/{admin_user.id}/reset-password",
            json={},
            headers=admin_headers,
        )

        assert response.status_code == 200


class TestActingOnAClientAboveYou:
    """A client is the other kind of principal, and the quieter one.

    A scope a client holds in its own right goes into a `client_credentials`
    token on request, with no person involved. Everything needed to use one is
    `admin:clients:write` and none of it is a scope assignment — which is why
    the gate is on touching the client at all.
    """

    @pytest.fixture
    async def elevated_client(self, client, admin_headers, scope_id):
        """Holds the withheld scope outright, but cannot yet use it."""
        return (
            await client.post(
                "/admin/clients",
                json={
                    "clientId": "dormant",
                    "name": "Dormant",
                    "clientType": "confidential",
                    "allowedGrants": ["authorization_code"],
                    "redirectUris": ["https://app.example.org/cb"],
                    "grantedScopeIds": [await scope_id(WITHHELD)],
                },
                headers=admin_headers,
            )
        ).json()

    async def test_the_grant_cannot_be_added(
        self, client, limited_headers, elevated_client
    ):
        """Waking it up: `client_credentials` is what turns a held scope into a
        token somebody can ask for."""
        response = await client.patch(
            f"/admin/clients/{elevated_client['id']}",
            json={"allowedGrants": ["client_credentials"]},
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_administer"

    async def test_its_secret_cannot_be_rotated(
        self, client, limited_headers, elevated_client
    ):
        """And taking the secret is how you would then use it."""
        response = await client.post(
            f"/admin/clients/{elevated_client['id']}/rotate-secret",
            headers=limited_headers,
        )

        assert response.status_code == 403

    async def test_it_cannot_be_deleted(self, client, limited_headers, elevated_client):
        response = await client.delete(
            f"/admin/clients/{elevated_client['id']}", headers=limited_headers
        )

        assert response.status_code == 403

    async def test_grantable_cannot_be_promoted_to_granted(
        self, client, admin_headers, limited_headers, scope_id
    ):
        """The two are not the same privilege. `grantable` reaches a token only
        through `/authorize`, where it is intersected with what the signed-in
        person holds; `granted` has no such bound. Comparing only which scope
        ids were attached treated the promotion as no change at all.
        """
        sid = await scope_id(WITHHELD)
        made = (
            await client.post(
                "/admin/clients",
                json={
                    "clientId": "flip",
                    "name": "Flip",
                    "clientType": "confidential",
                    "allowedGrants": ["client_credentials"],
                    "grantableScopeIds": [sid],
                },
                headers=admin_headers,
            )
        ).json()

        response = await client.put(
            f"/admin/clients/{made['id']}/scopes",
            json={"grantableScopeIds": [], "grantedScopeIds": [sid]},
            headers=limited_headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "cannot_delegate"

    async def test_an_ordinary_client_is_still_managed_normally(
        self, client, limited_headers
    ):
        made = (
            await client.post(
                "/admin/clients",
                json={
                    "clientId": "ordinary",
                    "name": "Ordinary",
                    "clientType": "confidential",
                    "allowedGrants": ["client_credentials"],
                },
                headers=limited_headers,
            )
        ).json()

        renamed = await client.patch(
            f"/admin/clients/{made['id']}",
            json={"name": "Renamed"},
            headers=limited_headers,
        )
        rotated = await client.post(
            f"/admin/clients/{made['id']}/rotate-secret", headers=limited_headers
        )

        assert renamed.status_code == 200
        assert rotated.status_code == 200

    async def test_grantable_alone_does_not_lock_a_client(
        self, client, admin_headers, limited_headers, scope_id
    ):
        """The dashboard is grantable for every admin scope and holds none of
        them. Treating that as authority would leave a limited administrator
        unable to touch the deployment's own client for no gain in safety."""
        made = (
            await client.post(
                "/admin/clients",
                json={
                    "clientId": "broker",
                    "name": "Broker",
                    "clientType": "public",
                    "redirectUris": ["https://app.example.org/cb"],
                    "grantableScopeIds": [await scope_id(WITHHELD)],
                },
                headers=admin_headers,
            )
        ).json()

        response = await client.patch(
            f"/admin/clients/{made['id']}",
            json={"name": "Renamed"},
            headers=limited_headers,
        )

        assert response.status_code == 200
