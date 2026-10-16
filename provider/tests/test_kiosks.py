"""Registered kiosks: creating one, pairing a device, reporting in, revoking.

The face work itself is in test_biometric.py; this is about which devices may
do it, and what the dashboard can see of them.
"""

import pytest
from sqlalchemy import select

from provider.biometric import consent
from provider.biometric.engine_client import EnrollResult
from provider.core.config import settings
from provider.shared.models import AuditEvent, Client, ClientScope, Kiosk
from provider.shared.scopes import FULL_ADMIN_SCOPES
from tests import test_biometric as faces

# The face tests' fixtures, which pytest finds by name in this module.
biometric_on = faces.biometric_on
fake_engine = faces.fake_engine
face_headers = faces.face_headers
mail = faces.mail

ISSUING = (
    "admin:kiosks:read",
    "admin:kiosks:write",
    "biometric:enroll",
    "biometric:device",
)


@pytest.fixture
async def kiosk_admin(token_for):
    return await token_for(*ISSUING)


async def register(client, headers, name="Library Kiosk 2") -> dict:
    response = await client.post(
        "/admin/kiosks", headers=headers, json={"name": name, "location": "Level 1"}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def pair(client, code: str) -> dict:
    response = await client.post("/biometric/kiosk/pair", json={"code": code})
    assert response.status_code == 200, response.text
    return response.json()


async def token(client, paired: dict):
    return await client.post(
        "/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": paired["clientId"],
            "client_secret": paired["clientSecret"],
            "scope": "biometric:enroll biometric:device",
        },
    )


async def device_headers(client, paired: dict) -> dict[str, str]:
    response = await token(client, paired)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def device(client, kiosk_admin):
    """A registered, paired kiosk: its admin record and its device headers."""
    kiosk = await register(client, kiosk_admin)
    paired = await pair(client, kiosk["pairing"]["code"])
    return kiosk, await device_headers(client, paired)


async def heartbeat(client, headers):
    return await client.post(
        "/biometric/kiosk/heartbeat",
        headers=headers,
        json={"softwareVersion": "1.2.0", "camera": "Rapoo C280"},
    )


async def start(client, headers, ticket):
    return await client.post(
        "/biometric/enroll/challenge", headers=headers, json={"ticket": ticket}
    )


async def enrol(client, headers, face_headers):
    ticket = await faces.new_ticket(client, face_headers)
    challenge = (await start(client, headers, ticket)).json()
    return await client.post(
        "/biometric/enroll",
        headers=headers,
        data={
            "ticket": ticket,
            "faceChallengeId": challenge["faceChallengeId"],
            "consent": consent.version(),
        },
        files=faces.frames(len(challenge["steps"])),
    )


class TestRegistering:
    async def test_a_kiosk_gets_its_own_client_without_a_secret(
        self, client, db, kiosk_admin
    ):
        body = await register(client, kiosk_admin)

        assert body["status"] == "never_paired"
        assert body["settings"]["inService"] is True
        assert len(body["pairing"]["code"]) == 9
        row = await db.scalar(
            select(Client).where(Client.client_id == body["clientId"])
        )
        assert row is not None
        assert row.client_secret_hash is None
        assert row.allowed_grants == ["client_credentials"]
        held = {
            link.scope.value
            for link in await db.scalars(
                select(ClientScope).where(ClientScope.client_id == row.id)
            )
            if link.granted
        }
        assert held == {"biometric:enroll", "biometric:device"}

    async def test_only_someone_holding_the_biometric_scopes_may_create_one(
        self, client, token_for
    ):
        headers = await token_for("admin:kiosks:write")
        response = await client.post(
            "/admin/kiosks", headers=headers, json={"name": "Kiosk"}
        )
        assert response.status_code == 403

    async def test_listed_with_their_status(self, client, kiosk_admin, device):
        await register(client, kiosk_admin, name="Annex")
        body = (await client.get("/admin/kiosks", headers=kiosk_admin)).json()

        assert body["meta"]["total"] == 2
        assert {k["name"]: k["status"] for k in body["items"]} == {
            "Annex": "never_paired",
            "Library Kiosk 2": "offline",
        }

    async def test_absent_while_the_module_is_off(
        self, client, kiosk_admin, monkeypatch
    ):
        monkeypatch.setattr(settings, "iden_biometric_enabled", False)
        assert (
            await client.get("/admin/kiosks", headers=kiosk_admin)
        ).status_code == 404

    async def test_the_clients_api_leaves_a_kiosks_client_alone(
        self, client, db, token_for, device
    ):
        kiosk, _ = device
        row = await db.scalar(select(Kiosk).where(Kiosk.id == kiosk["id"]))
        assert row is not None
        full = await token_for(*FULL_ADMIN_SCOPES)
        for method, path in (
            ("patch", f"/admin/clients/{row.client_id}"),
            ("post", f"/admin/clients/{row.client_id}/rotate-secret"),
            ("delete", f"/admin/clients/{row.client_id}"),
        ):
            kwargs = {"json": {"name": "x"}} if method == "patch" else {}
            response = await getattr(client, method)(path, headers=full, **kwargs)
            assert response.status_code == 409, path
            assert response.json()["code"] == "kiosk_managed"


class TestPairing:
    async def test_the_code_buys_a_secret_that_signs_in(self, client, kiosk_admin):
        kiosk = await register(client, kiosk_admin)
        paired = await pair(client, kiosk["pairing"]["code"])

        assert paired["clientId"] == kiosk["clientId"]
        assert paired["name"] == "Library Kiosk 2"
        assert (await token(client, paired)).status_code == 200

    async def test_a_code_works_once(self, client, kiosk_admin):
        code = (await register(client, kiosk_admin))["pairing"]["code"]
        await pair(client, code)

        again = await client.post("/biometric/kiosk/pair", json={"code": code})
        assert again.status_code == 404
        assert again.json()["code"] == "pairing_code_invalid"

    async def test_case_spaces_and_the_dash_do_not_matter(self, client, kiosk_admin):
        code = (await register(client, kiosk_admin))["pairing"]["code"]
        sloppy = " " + code.replace("-", " ").lower()
        assert (
            await client.post("/biometric/kiosk/pair", json={"code": sloppy})
        ).status_code == 200

    async def test_a_new_code_retires_the_last(self, client, kiosk_admin):
        kiosk = await register(client, kiosk_admin)
        response = await client.post(
            f"/admin/kiosks/{kiosk['id']}/pairing-code", headers=kiosk_admin
        )
        assert response.status_code == 201

        old = await client.post(
            "/biometric/kiosk/pair", json={"code": kiosk["pairing"]["code"]}
        )
        assert old.status_code == 404
        await pair(client, response.json()["code"])

    async def test_pairing_again_locks_out_the_previous_device(
        self, client, kiosk_admin
    ):
        kiosk = await register(client, kiosk_admin)
        first = await pair(client, kiosk["pairing"]["code"])
        code = (
            await client.post(
                f"/admin/kiosks/{kiosk['id']}/pairing-code", headers=kiosk_admin
            )
        ).json()["code"]
        second = await pair(client, code)

        assert (await token(client, first)).status_code == 401
        assert (await token(client, second)).status_code == 200

    async def test_guessing_is_rate_limited(self, client, monkeypatch):
        monkeypatch.setattr(settings, "iden_rate_limit_enabled", True)
        statuses = [
            (
                await client.post("/biometric/kiosk/pair", json={"code": "AAAA-AAAA"})
            ).status_code
            for _ in range(11)
        ]
        assert statuses[:10] == [404] * 10
        assert statuses[10] == 429

    async def test_the_code_never_reaches_the_audit_log(self, client, db, kiosk_admin):
        code = (await register(client, kiosk_admin))["pairing"]["code"]
        await pair(client, code)

        events = list(
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "POST /biometric/kiosk/pair"
                )
            )
        )
        assert len(events) == 1
        assert code not in str(events[0].detail)


class TestHeartbeat:
    async def test_the_kiosk_is_given_the_consent_text(
        self, client, device, monkeypatch
    ):
        _, headers = device
        given = (await heartbeat(client, headers)).json()["consent"]
        assert given["version"] == consent.version()
        assert given["statements"] == consent.statements()
        assert "not kept" in " ".join(given["statements"])

        # The words say what this deployment does, and saying something else
        # is a different consent.
        monkeypatch.setattr(settings, "iden_biometric_keep_images", True)
        kept = (await heartbeat(client, headers)).json()["consent"]
        assert "also kept" in " ".join(kept["statements"])
        assert kept["version"] != given["version"]

    async def test_reports_in_and_reads_its_settings(self, client, kiosk_admin, device):
        kiosk, headers = device
        await client.patch(
            f"/admin/kiosks/{kiosk['id']}",
            headers=kiosk_admin,
            json={"settings": {"idleSeconds": 45, "notice": "Open 9 to 5"}},
        )

        response = await heartbeat(client, headers)

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Library Kiosk 2"
        assert body["settings"]["idleSeconds"] == 45
        assert body["settings"]["notice"] == "Open 9 to 5"
        assert body["heartbeatSeconds"] == 60
        seen = (
            await client.get(f"/admin/kiosks/{kiosk['id']}", headers=kiosk_admin)
        ).json()
        assert seen["status"] == "online"
        assert seen["lastSeenVersion"] == "1.2.0"
        assert seen["lastSeenCamera"] == "Rapoo C280"

    async def test_is_not_audited(self, client, db, device):
        _, headers = device
        await heartbeat(client, headers)
        assert (
            await db.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "POST /biometric/kiosk/heartbeat"
                )
            )
            is None
        )

    async def test_settings_are_validated(self, client, kiosk_admin, device):
        kiosk, _ = device
        response = await client.patch(
            f"/admin/kiosks/{kiosk['id']}",
            headers=kiosk_admin,
            json={"settings": {"idleSeconds": 5}},
        )
        assert response.status_code == 422


class TestWhoMayEnrol:
    async def test_a_registered_kiosk_enrols_and_learns_the_attempts_left(
        self, client, fake_engine, device, face_headers, mail
    ):
        _, headers = device
        ticket = await faces.new_ticket(client, face_headers)
        first = (await start(client, headers, ticket)).json()
        second = (await start(client, headers, ticket)).json()

        assert first["attemptsLeft"] == 4
        assert second["attemptsLeft"] == 3
        assert (await enrol(client, headers, face_headers)).status_code == 201
        assert mail[0]["body"].count("Library Kiosk 2") >= 1

    async def test_a_client_that_is_not_a_kiosk_may_not(
        self, client, db, kiosk, scope_of, face_headers
    ):
        row, secret = kiosk
        db.add(
            ClientScope(
                client_id=row.id,
                scope_id=scope_of("biometric:enroll").id,
                grantable=False,
                granted=True,
            )
        )
        await db.commit()
        issued = await token(client, {"clientId": "kiosk", "clientSecret": secret})
        headers = {"Authorization": f"Bearer {issued.json()['access_token']}"}

        ticket = await faces.new_ticket(client, face_headers)
        assert (await start(client, headers, ticket)).status_code == 401

    async def test_a_revoked_kiosk_stops_at_once(
        self, client, kiosk_admin, device, face_headers
    ):
        kiosk, headers = device
        response = await client.delete(
            f"/admin/kiosks/{kiosk['id']}", headers=kiosk_admin
        )
        assert response.status_code == 204

        ticket = await faces.new_ticket(client, face_headers)
        assert (await start(client, headers, ticket)).status_code == 401
        assert (await heartbeat(client, headers)).status_code == 401

    async def test_out_of_service_refuses_enrolment_but_still_reports_in(
        self, client, kiosk_admin, device, face_headers
    ):
        kiosk, headers = device
        await client.patch(
            f"/admin/kiosks/{kiosk['id']}",
            headers=kiosk_admin,
            json={"settings": {"inService": False}},
        )

        ticket = await faces.new_ticket(client, face_headers)
        response = await start(client, headers, ticket)
        assert response.status_code == 403
        assert response.json()["code"] == "kiosk_out_of_service"
        assert (await heartbeat(client, headers)).json()["settings"][
            "inService"
        ] is False
        listed = (
            await client.get(f"/admin/kiosks/{kiosk['id']}", headers=kiosk_admin)
        ).json()
        assert listed["status"] == "out_of_service"


class TestHistory:
    async def test_lists_what_it_enrolled_and_why_attempts_failed(
        self, client, fake_engine, kiosk_admin, device, face_headers, mail, admin_user
    ):
        kiosk, headers = device
        live = fake_engine.enroll_result
        fake_engine.enroll_result = EnrollResult(
            usable=False, reasons=["too_dark"], model_version=faces.VERSION
        )
        await enrol(client, headers, face_headers)
        fake_engine.enroll_result = live
        await enrol(client, headers, face_headers)

        body = (
            await client.get(
                f"/admin/kiosks/{kiosk['id']}/enrolments", headers=kiosk_admin
            )
        ).json()

        assert body["meta"]["total"] == 2
        latest, earlier = body["items"]
        assert latest["outcome"] == "enrolled"
        assert latest["userId"] == str(admin_user.id)
        assert latest["userLabel"] == admin_user.display_name
        assert earlier["outcome"] == "failed"
        assert earlier["error"] == "poor_capture"

    async def test_another_kiosks_enrolments_are_not_listed(
        self, client, fake_engine, kiosk_admin, device, face_headers, mail
    ):
        _, headers = device
        await enrol(client, headers, face_headers)
        other = await register(client, kiosk_admin, name="Annex")

        body = (
            await client.get(
                f"/admin/kiosks/{other['id']}/enrolments", headers=kiosk_admin
            )
        ).json()
        assert body["items"] == []
