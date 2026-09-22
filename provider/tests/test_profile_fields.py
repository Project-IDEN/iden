"""Phase 4.1 — the profile schema an organization defines for itself.

The feature that lets a university and a company run the same IdP without
either of them forking it.
"""

import pytest

from provider.shared.models import Group

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

STUDENT_ID = {
    "key": "student_id",
    "label": "Student number",
    "dataType": "string",
    "unique": True,
    "userWritable": False,
    "validators": {"pattern": "^[0-9]{8}$"},
}
PREFERRED_NAME = {
    "key": "preferred_name",
    "label": "Preferred name",
    "userWritable": True,
}


async def define(client, admin_headers, body: dict):
    response = await client.post(
        "/admin/profile-fields", json=body, headers=admin_headers
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestDefiningFields:
    async def test_requires_its_own_scope(self, client, token_for):
        headers = await token_for("admin:users:write")
        response = await client.post(
            "/admin/profile-fields", json=STUDENT_ID, headers=headers
        )
        assert response.status_code == 403

    async def test_a_key_cannot_be_reused(self, client, admin_headers):
        await define(client, admin_headers, STUDENT_ID)
        again = await client.post(
            "/admin/profile-fields", json=STUDENT_ID, headers=admin_headers
        )
        assert again.status_code == 409

    async def test_an_enum_needs_options(self, client, admin_headers):
        response = await client.post(
            "/admin/profile-fields",
            json={"key": "campus", "label": "Campus", "dataType": "enum"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    async def test_a_claim_cannot_shadow_a_reserved_one(self, client, admin_headers):
        """A custom field named `sub` would let an administrator forge the
        meaning of a token."""
        response = await client.post(
            "/admin/profile-fields",
            json={
                "key": "impostor",
                "label": "Impostor",
                "claimName": "sub",
                "claimScope": "entity:profile:read",
            },
            headers=admin_headers,
        )
        assert response.status_code == 422

    async def test_a_claim_needs_a_scope_to_be_released_under(
        self, client, admin_headers
    ):
        response = await client.post(
            "/admin/profile-fields",
            json={"key": "dept", "label": "Department", "claimName": "department"},
            headers=admin_headers,
        )
        assert response.status_code == 422


class TestSelfService:
    async def test_a_writable_field_is_the_persons_own(
        self, client, admin_headers, entity_headers
    ):
        await define(client, admin_headers, PREFERRED_NAME)

        response = await client.patch(
            "/entity/profile",
            json={"fields": {"preferred_name": "Sam"}},
            headers=entity_headers,
        )

        assert response.status_code == 200
        assert response.json()["fields"]["preferred_name"] == "Sam"

    async def test_a_read_only_field_is_refused(
        self, client, admin_headers, entity_headers
    ):
        """The rule the whole module turns on: a person may change anything
        about themselves that does not change what they are allowed to do, and
        `student_id` is the registrar's, not theirs."""
        await define(client, admin_headers, STUDENT_ID)

        response = await client.patch(
            "/entity/profile",
            json={"fields": {"student_id": "00000001"}},
            headers=entity_headers,
        )

        assert response.status_code == 422
        assert response.json()["code"] == "field_not_writable"

    async def test_an_unknown_field_is_refused_not_ignored(
        self, client, entity_headers
    ):
        """Silently dropping it would let a client believe it saved something."""
        response = await client.patch(
            "/entity/profile",
            json={"fields": {"invented": "x"}},
            headers=entity_headers,
        )
        assert response.status_code == 404

    async def test_the_admin_can_write_what_the_person_cannot(
        self, client, admin_headers, entity_headers, member
    ):
        await define(client, admin_headers, STUDENT_ID)

        written = await client.patch(
            f"/admin/users/{member.id}/profile",
            json={"fields": {"student_id": "12345678"}},
            headers=admin_headers,
        )
        assert written.status_code == 200

        seen = await client.get("/entity/profile", headers=entity_headers)
        assert seen.json()["fields"]["student_id"] == "12345678"


class TestValidation:
    async def test_a_value_must_match_the_pattern(self, client, admin_headers, member):
        await define(client, admin_headers, STUDENT_ID)

        response = await client.patch(
            f"/admin/users/{member.id}/profile",
            json={"fields": {"student_id": "nope"}},
            headers=admin_headers,
        )

        assert response.status_code == 422
        assert response.json()["details"]["field"] == "student_id"

    async def test_an_integer_field_rejects_words(self, client, admin_headers, member):
        await define(
            client,
            admin_headers,
            {"key": "year", "label": "Year", "dataType": "integer"},
        )

        response = await client.patch(
            f"/admin/users/{member.id}/profile",
            json={"fields": {"year": "first"}},
            headers=admin_headers,
        )
        assert response.status_code == 422

    async def test_an_enum_rejects_values_outside_its_options(
        self, client, admin_headers, member
    ):
        await define(
            client,
            admin_headers,
            {
                "key": "campus",
                "label": "Campus",
                "dataType": "enum",
                "options": ["north", "south"],
            },
        )

        response = await client.patch(
            f"/admin/users/{member.id}/profile",
            json={"fields": {"campus": "east"}},
            headers=admin_headers,
        )
        assert response.status_code == 422

    async def test_a_unique_field_cannot_collide(
        self, client, admin_headers, member, admin_user
    ):
        """Enforced by the database, because a check-then-write in the service
        layer races — and two students sharing a number is exactly the failure
        that must not happen."""
        await define(client, admin_headers, STUDENT_ID)

        first = await client.patch(
            f"/admin/users/{member.id}/profile",
            json={"fields": {"student_id": "12345678"}},
            headers=admin_headers,
        )
        second = await client.patch(
            f"/admin/users/{admin_user.id}/profile",
            json={"fields": {"student_id": "12345678"}},
            headers=admin_headers,
        )

        assert first.status_code == 200
        assert second.status_code == 409


class TestGroupBoundFields:
    async def test_a_field_bound_to_a_group_reaches_only_its_members(
        self, client, admin_headers, entity_headers, db, member
    ):
        """How students and staff get different forms without a second
        grouping concept."""
        students = Group(name="Students")
        db.add(students)
        await db.commit()

        await define(
            client,
            admin_headers,
            {**STUDENT_ID, "groupId": str(students.id), "userWritable": True},
        )

        before = await client.get("/entity/profile/schema", headers=entity_headers)
        assert [f["key"] for f in before.json()["fields"]] == []

        member.groups = [students]
        await db.commit()

        after = await client.get("/entity/profile/schema", headers=entity_headers)
        assert [f["key"] for f in after.json()["fields"]] == ["student_id"]


class TestSchemaEndpoint:
    async def test_describes_the_form_to_render(
        self, client, admin_headers, entity_headers
    ):
        await define(client, admin_headers, STUDENT_ID)
        await define(client, admin_headers, PREFERRED_NAME)

        body = (
            await client.get("/entity/profile/schema", headers=entity_headers)
        ).json()

        by_key = {field["key"]: field for field in body["fields"]}
        assert by_key["student_id"]["writable"] is False
        assert by_key["preferred_name"]["writable"] is True
        assert by_key["student_id"]["validators"] == {"pattern": "^[0-9]{8}$"}


class TestClaimRelease:
    async def test_a_field_reaches_a_token_only_under_its_scope(
        self, client, admin_headers, member, db
    ):
        """Data minimization by default: a field is invisible to clients until
        someone maps it, and then only to clients holding that scope."""
        await define(
            client,
            admin_headers,
            {
                "key": "department",
                "label": "Department",
                "claimName": "department",
                "claimScope": "entity:profile:read",
            },
        )
        await client.patch(
            f"/admin/users/{member.id}/profile",
            json={"fields": {"department": "Computer Science"}},
            headers=admin_headers,
        )

        from provider.entity.profile import service as profile_service

        released = await profile_service.claims_for(
            db, member, {"openid", "entity:profile:read"}
        )
        withheld = await profile_service.claims_for(db, member, {"openid"})

        assert released == {"department": "Computer Science"}
        assert withheld == {}

    async def test_it_appears_in_userinfo_when_granted(
        self, client, admin_headers, token_for, member
    ):
        await define(
            client,
            admin_headers,
            {
                "key": "department",
                "label": "Department",
                "claimName": "department",
                "claimScope": "entity:profile:read",
            },
        )
        await client.patch(
            f"/admin/users/{member.id}/profile",
            json={"fields": {"department": "History"}},
            headers=admin_headers,
        )

        headers = await token_for("openid", "entity:profile:read", user=member)
        body = (await client.get("/oauth2/userinfo", headers=headers)).json()

        assert body["department"] == "History"

    async def test_it_is_absent_from_userinfo_without_the_scope(
        self, client, admin_headers, token_for, member
    ):
        await define(
            client,
            admin_headers,
            {
                "key": "department",
                "label": "Department",
                "claimName": "department",
                "claimScope": "entity:profile:read",
            },
        )
        await client.patch(
            f"/admin/users/{member.id}/profile",
            json={"fields": {"department": "History"}},
            headers=admin_headers,
        )

        headers = await token_for("openid", user=member)
        body = (await client.get("/oauth2/userinfo", headers=headers)).json()

        assert "department" not in body


class TestPresets:
    """The catalogue an administrator starts from.

    Templates, not rows: nothing here exists until it is posted back.
    """

    async def test_presets_are_listed(self, client, admin_headers):
        body = (
            await client.get("/admin/profile-fields/presets", headers=admin_headers)
        ).json()

        keys = [preset["key"] for preset in body["presets"]]
        assert "student_id" in keys and "preferred_name" in keys

    async def test_nothing_is_created_by_reading_them(self, client, admin_headers):
        await client.get("/admin/profile-fields/presets", headers=admin_headers)

        listed = (
            await client.get("/admin/profile-fields", headers=admin_headers)
        ).json()
        assert listed["meta"]["total"] == 0

    async def test_a_preset_can_be_posted_back_unchanged(self, client, admin_headers):
        """The response shape is the request shape — that is what makes the
        catalogue usable rather than merely informative."""
        presets = (
            await client.get("/admin/profile-fields/presets", headers=admin_headers)
        ).json()["presets"]
        preset = next(p for p in presets if p["key"] == "student_id")

        body = {k: v for k, v in preset.items() if k not in ("rationale", "category")}
        response = await client.post(
            "/admin/profile-fields", json=body, headers=admin_headers
        )

        assert response.status_code == 201
        assert response.json()["key"] == "student_id"
        assert response.json()["unique"] is True

    async def test_ownership_is_the_opinion_they_carry(self, client, admin_headers):
        """A preferred name belongs to its owner; a student number does not."""
        presets = (
            await client.get("/admin/profile-fields/presets", headers=admin_headers)
        ).json()["presets"]
        by_key = {preset["key"]: preset for preset in presets}

        assert by_key["preferred_name"]["userWritable"] is True
        assert by_key["student_id"]["userWritable"] is False

    async def test_the_route_is_not_read_as_a_field_id(self, client, admin_headers):
        """`/presets` is a literal path sharing a prefix with `/{field_id}`. If
        the parameter wins, this answers 422 for a malformed UUID."""
        response = await client.get(
            "/admin/profile-fields/presets", headers=admin_headers
        )
        assert response.status_code == 200

    async def test_reading_them_needs_the_scope(self, client, token_for):
        headers = await token_for("admin:users:read")
        response = await client.get("/admin/profile-fields/presets", headers=headers)
        assert response.status_code == 403


class TestValidatorRules:
    """`validators` is applied to text other people submit, so it is checked
    when the field is defined — not when someone saves their profile."""

    async def attempt(self, client, admin_headers, rules):
        return await client.post(
            "/admin/profile-fields",
            json={**STUDENT_ID, "validators": rules},
            headers=admin_headers,
        )

    async def test_an_uncompilable_pattern_is_refused(self, client, admin_headers):
        response = await self.attempt(client, admin_headers, {"pattern": "^[0-9"})
        assert response.status_code == 422

    async def test_an_enormous_pattern_is_refused(self, client, admin_headers):
        """A backtracking expression over a long value does not finish. Capping
        both the pattern and the value bounds what one worker can be made to do."""
        response = await self.attempt(client, admin_headers, {"pattern": "(a+)+" * 200})
        assert response.status_code == 422

    async def test_an_unknown_rule_is_refused_rather_than_ignored(
        self, client, admin_headers
    ):
        """`minLength` is what the documentation used to claim. Nothing read it,
        so a field defined with it enforced no length at all."""
        response = await self.attempt(client, admin_headers, {"minLength": 3})
        assert response.status_code == 422

    async def test_a_rule_of_the_wrong_type_is_refused(self, client, admin_headers):
        """Applied as written, this raised a TypeError deep inside somebody
        else's profile save."""
        response = await self.attempt(client, admin_headers, {"max_length": "long"})
        assert response.status_code == 422

    async def test_an_update_is_held_to_the_same_rules(self, client, admin_headers):
        created = await define(client, admin_headers, STUDENT_ID)

        response = await client.patch(
            f"/admin/profile-fields/{created['id']}",
            json={"validators": {"pattern": "^[0-9"}},
            headers=admin_headers,
        )
        assert response.status_code == 422

    async def test_every_shipped_preset_is_valid(self):
        """The presets are meant to be posted straight back to this API."""
        from provider.shared.profile import check_validators
        from provider.shared.profile_presets import PRESETS

        for preset in PRESETS:
            check_validators(preset.validators)
