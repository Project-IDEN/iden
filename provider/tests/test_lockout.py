"""The last-administrator guard — KI-8.

Every other administrative mistake is reversible by another administrator.
Removing the last one is not: no API call puts `admin:grants:write` back once
nobody holds it, only a hand-edited database. Each test here is one such door.
"""

import pytest

from provider.admin.lockout import RECOVERY_SCOPE
from provider.shared.models import Group

pytestmark = pytest.mark.usefixtures("catalogue")


@pytest.fixture
async def only_admin(client, admin_headers, admin_user):
    """The bootstrap administrator, who is the only holder of the recovery
    scope in a fresh deployment."""
    return admin_user


def refused(response) -> bool:
    return (
        response.status_code == 409
        and response.json()["code"] == "would_lock_everyone_out"
    )


class TestTheLastAdministrator:
    async def test_cannot_be_stripped_of_their_roles(
        self, client, admin_headers, only_admin
    ):
        response = await client.put(
            f"/admin/users/{only_admin.id}/roles",
            json={"roleIds": []},
            headers=admin_headers,
        )

        assert refused(response)

    async def test_cannot_be_deactivated(self, client, admin_headers, only_admin):
        response = await client.patch(
            f"/admin/users/{only_admin.id}",
            json={"isActive": False},
            headers=admin_headers,
        )

        assert refused(response)

    async def test_cannot_be_deleted(self, client, admin_headers, only_admin):
        response = await client.delete(
            f"/admin/users/{only_admin.id}", headers=admin_headers
        )

        assert refused(response)

    async def test_the_refusal_leaves_them_exactly_as_they_were(
        self, client, admin_headers, only_admin, db
    ):
        """A guard that refuses but half-applies the change is worse than no
        guard: the session rolls back, so nothing landed."""
        await client.put(
            f"/admin/users/{only_admin.id}/roles",
            json={"roleIds": []},
            headers=admin_headers,
        )

        await db.refresh(only_admin, ["roles"])
        assert [role.name for role in only_admin.roles] == ["administrator"]
        assert only_admin.is_active


class TestOnceThereIsASecond:
    """The guard counts holders, not names. Anyone who can restore access
    counts, however they came by the scope."""

    async def test_a_second_direct_grant_is_enough(
        self, client, admin_headers, only_admin, member, scope_of
    ):
        response = await client.put(
            f"/admin/users/{member.id}/scopes",
            json={"scopeIds": [str(scope_of(RECOVERY_SCOPE).id)]},
            headers=admin_headers,
        )
        assert response.status_code == 200

        # Now the first one is expendable.
        response = await client.patch(
            f"/admin/users/{only_admin.id}",
            json={"isActive": False},
            headers=admin_headers,
        )
        assert response.status_code == 200

    async def test_a_second_via_a_group_is_enough(
        self, client, admin_headers, only_admin, member, catalogue, db
    ):
        staff = Group(name="staff")
        db.add(staff)
        await db.commit()

        await client.put(
            f"/admin/groups/{staff.id}/roles",
            json={"roleIds": [str(catalogue["roles"]["administrator"].id)]},
            headers=admin_headers,
        )
        await client.post(
            f"/admin/groups/{staff.id}/members",
            json={"userIds": [str(member.id)]},
            headers=admin_headers,
        )

        response = await client.delete(
            f"/admin/users/{only_admin.id}", headers=admin_headers
        )
        assert response.status_code == 204

    async def test_an_inactive_second_does_not_count(
        self, client, admin_headers, only_admin, member, scope_of, db
    ):
        """A deactivated account cannot sign in, so it cannot restore anyone.
        Counting it would let the guard be satisfied by nobody."""
        member.is_active = False
        member.scopes = [scope_of(RECOVERY_SCOPE)]
        await db.commit()

        response = await client.patch(
            f"/admin/users/{only_admin.id}",
            json={"isActive": False},
            headers=admin_headers,
        )
        assert refused(response)


class TestTheOtherDoors:
    """Authority arrives through roles and groups too, and each of those has a
    delete that could empty it."""

    async def test_a_group_cannot_be_stripped_of_the_role_that_grants_it(
        self, client, admin_headers, catalogue, member, only_admin, db
    ):
        staff = Group(name="staff")
        staff.roles = [catalogue["roles"]["administrator"]]
        db.add(staff)
        await db.commit()

        await client.post(
            f"/admin/groups/{staff.id}/members",
            json={"userIds": [str(member.id)]},
            headers=admin_headers,
        )
        # The bootstrap admin steps down, which is allowed — the group now
        # carries the authority.
        stepping_down = await client.put(
            f"/admin/users/{only_admin.id}/roles",
            json={"roleIds": []},
            headers=admin_headers,
        )
        assert stepping_down.status_code == 200

        response = await client.put(
            f"/admin/groups/{staff.id}/roles",
            json={"roleIds": []},
            headers=admin_headers,
        )
        assert refused(response)

    async def test_removing_the_last_member_of_that_group_is_refused_too(
        self, client, admin_headers, catalogue, member, only_admin, db
    ):
        """Membership is the other half of the same path. Guarding the role
        binding and not the membership would leave the door ajar."""
        staff = Group(name="staff")
        staff.roles = [catalogue["roles"]["administrator"]]
        db.add(staff)
        await db.commit()

        await client.post(
            f"/admin/groups/{staff.id}/members",
            json={"userIds": [str(member.id)]},
            headers=admin_headers,
        )
        await client.put(
            f"/admin/users/{only_admin.id}/roles",
            json={"roleIds": []},
            headers=admin_headers,
        )

        assert refused(
            await client.delete(
                f"/admin/groups/{staff.id}/members/{member.id}", headers=admin_headers
            )
        )
        assert refused(
            await client.delete(f"/admin/groups/{staff.id}", headers=admin_headers)
        )

    async def test_a_custom_role_cannot_be_emptied_to_nothing(
        self, client, admin_headers, member, scope_of, only_admin
    ):
        """A deployment that moved authority off `administrator` onto a role of
        its own is protected the same way."""
        role = (
            await client.post(
                "/admin/roles", json={"name": "operator"}, headers=admin_headers
            )
        ).json()
        await client.put(
            f"/admin/roles/{role['id']}/scopes",
            json={"scopeIds": [str(scope_of(RECOVERY_SCOPE).id)]},
            headers=admin_headers,
        )
        await client.put(
            f"/admin/users/{member.id}/roles",
            json={"roleIds": [role["id"]]},
            headers=admin_headers,
        )
        # The bootstrap admin steps down, leaving the custom role as the source.
        await client.put(
            f"/admin/users/{only_admin.id}/roles",
            json={"roleIds": []},
            headers=admin_headers,
        )

        response = await client.put(
            f"/admin/roles/{role['id']}/scopes",
            json={"scopeIds": []},
            headers=admin_headers,
        )
        assert refused(response)

        response = await client.delete(
            f"/admin/roles/{role['id']}?force=true", headers=admin_headers
        )
        assert refused(response)
