"""Face enrolment at a kiosk, and face as a second factor at sign-in.

The engine is replaced by a fake that returns whatever verdict a test sets: the
engine's own judgement is tested in engine/, and what matters here is what the
provider does with one.
"""

import httpx
import jwt
import pytest
from sqlalchemy import select

from provider.biometric import challenges, consent, service
from provider.biometric.engine_client import (
    EnrollResult,
    VerifyResult,
    get_engine,
)
from provider.core.config import settings
from provider.core.security import decrypt_bytes
from provider.shared.models import AuditEvent, FaceTemplate
from tests.biometric import (
    SPOOF,
    VECTORS,
    VERSION,
    FakeEngine,
    begin,
    enrol_at_kiosk,
    face_step,
    frames,
    kiosk_capture,
    new_ticket,
)
from tests.conftest import REDIRECT_URI
from tests.flows import pkce_pair, query_of, sign_in, start


@pytest.fixture(autouse=True)
def biometric_on(monkeypatch):
    # Autouse, so it runs before `catalogue` seeds the scopes the flag adds.
    monkeypatch.setattr(settings, "iden_biometric_enabled", True)


def decode(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


class TestDisabled:
    async def test_the_module_answers_as_though_it_did_not_exist(
        self, client, monkeypatch, face_headers, kiosk_headers
    ):
        monkeypatch.setattr(settings, "iden_biometric_enabled", False)

        assert (
            await client.get("/entity/face", headers=face_headers)
        ).status_code == 404
        response = await client.post(
            "/biometric/enroll/challenge", headers=kiosk_headers, json={"ticket": "x"}
        )
        assert response.status_code == 404
        response = await client.post("/api/v1/auth/biometric/challenge", json={})
        assert response.status_code in (422, 501)

    async def test_sign_in_with_a_face_is_not_implemented(self, client, monkeypatch):
        monkeypatch.setattr(settings, "iden_biometric_enabled", False)
        response = await client.post(
            "/api/v1/auth/biometric",
            data={"challengeId": "x", "faceChallengeId": "y"},
            files=frames(1),
        )
        assert response.status_code == 501

    async def test_discovery_does_not_advertise_face(self, client, monkeypatch):
        monkeypatch.setattr(settings, "iden_biometric_enabled", False)
        config = (await client.get("/.well-known/openid-configuration")).json()
        assert "face" not in config["amr_values_supported"]
        assert "urn:iden:acr:mfa-face" not in config["acr_values_supported"]


async def test_discovery_advertises_face_when_enabled(client):
    config = (await client.get("/.well-known/openid-configuration")).json()
    assert "face" in config["amr_values_supported"]
    assert "urn:iden:acr:mfa-face" in config["acr_values_supported"]


class TestTickets:
    async def test_a_ticket_needs_the_face_write_scope(self, client, token_for):
        headers = await token_for("entity:face:read")
        response = await client.post("/entity/face/ticket", headers=headers)
        assert response.status_code == 403

    async def test_the_kiosk_learns_whose_face_and_what_to_capture(
        self, client, kiosk_headers, face_headers, admin_user
    ):
        ticket = await new_ticket(client, face_headers)
        body = (await kiosk_capture(client, kiosk_headers, ticket)).json()

        assert body["displayName"] == admin_user.display_name
        assert body["steps"][:3] == ["center"] * 3
        assert len(body["steps"]) == 3 + 2 * 3

    async def test_an_unknown_ticket_names_nobody(self, client, kiosk_headers):
        response = await kiosk_capture(client, kiosk_headers, "not-a-ticket")
        assert response.status_code == 404
        assert response.json()["code"] == "enrolment_ticket_invalid"

    async def test_a_new_ticket_retires_the_last(
        self, client, kiosk_headers, face_headers
    ):
        first = await new_ticket(client, face_headers)
        await new_ticket(client, face_headers)
        assert (await kiosk_capture(client, kiosk_headers, first)).status_code == 404

    async def test_a_ticket_allows_a_few_attempts_not_endless_ones(
        self, client, kiosk_headers, face_headers
    ):
        ticket = await new_ticket(client, face_headers)
        statuses = [
            (await kiosk_capture(client, kiosk_headers, ticket)).status_code
            for _ in range(6)
        ]
        assert statuses == [200] * 5 + [404]

    async def test_a_signed_in_person_cannot_use_the_kiosk_api(
        self, client, face_headers, token_for
    ):
        ticket = await new_ticket(client, face_headers)
        headers = await token_for("entity:face:write")
        response = await client.post(
            "/biometric/enroll/challenge", headers=headers, json={"ticket": ticket}
        )
        assert response.status_code == 401


class TestKioskEnrolment:
    async def test_enrolment_stores_encrypted_embeddings(
        self, client, db, fake_engine, kiosk_headers, face_headers, admin_user
    ):
        response = await enrol_at_kiosk(client, kiosk_headers, face_headers)

        assert response.status_code == 201
        assert response.json() == {"enrolled": True, "samples": 3}
        rows = list(await db.scalars(select(FaceTemplate)))
        assert len(rows) == 3
        assert {row.enrolled_by for row in rows} == {"kiosk"}
        assert {row.model_version for row in rows} == {VERSION}
        for row in rows:
            assert row.embedding_encrypted.startswith("v1:")
            assert "0.1" not in row.embedding_encrypted
        stored = sorted(
            service.unpack(r.embedding_encrypted, admin_user.id) for r in rows
        )
        for got, sent in zip(stored, sorted(VECTORS), strict=True):
            assert got == pytest.approx(sent)

    async def test_the_engine_is_asked_for_exactly_the_challenge(
        self, client, fake_engine, kiosk_headers, face_headers
    ):
        await enrol_at_kiosk(client, kiosk_headers, face_headers)
        kind, count, steps = fake_engine.calls[0]
        assert kind == "enroll"
        assert count == len(steps) == 9

    async def test_a_ticket_enrols_once(
        self, client, fake_engine, kiosk_headers, face_headers
    ):
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()
        payload = {
            "ticket": ticket,
            "faceChallengeId": challenge["faceChallengeId"],
            "consent": consent.version(),
        }
        first = await client.post(
            "/biometric/enroll", headers=kiosk_headers, data=payload, files=frames(9)
        )
        again = await kiosk_capture(client, kiosk_headers, ticket)

        assert first.status_code == 201
        assert again.status_code == 404

    async def test_a_spoof_is_refused_and_the_ticket_survives(
        self, client, db, fake_engine, kiosk_headers, face_headers
    ):
        fake_engine.enroll_result = fake_engine.enroll_result.model_copy(
            update={"live": False, "checks": SPOOF, "embeddings": []}
        )
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()
        response = await client.post(
            "/biometric/enroll",
            headers=kiosk_headers,
            data={
                "ticket": ticket,
                "faceChallengeId": challenge["faceChallengeId"],
                "consent": consent.version(),
            },
            files=frames(9),
        )

        assert response.status_code == 422
        assert response.json()["code"] == "not_live"
        assert response.json()["details"]["failed"] == ["anti_spoofing", "actions"]
        # A kiosk is supervised: it hears how far each check was off, for tuning.
        assert set(response.json()["details"]["scores"]) == {
            "antiSpoofing",
            "actions",
            "consistency",
        }
        assert await db.scalar(select(FaceTemplate.id)) is None
        assert (await kiosk_capture(client, kiosk_headers, ticket)).status_code == 200

    async def test_a_poor_capture_says_what_to_fix(
        self, client, fake_engine, kiosk_headers, face_headers
    ):
        fake_engine.enroll_result = EnrollResult(
            usable=False, reasons=["too_dark", "blurred"], model_version=VERSION
        )
        response = await enrol_at_kiosk(client, kiosk_headers, face_headers)

        assert response.status_code == 422
        assert response.json()["code"] == "poor_capture"
        assert response.json()["details"]["reasons"] == ["too_dark", "blurred"]

    async def test_frames_must_match_the_challenge(
        self, client, fake_engine, kiosk_headers, face_headers
    ):
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()
        response = await client.post(
            "/biometric/enroll",
            headers=kiosk_headers,
            data={
                "ticket": ticket,
                "faceChallengeId": challenge["faceChallengeId"],
                "consent": consent.version(),
            },
            files=frames(5),
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_frames"
        assert fake_engine.calls == []

    async def test_frames_must_be_jpeg(
        self, client, fake_engine, kiosk_headers, face_headers
    ):
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()
        response = await client.post(
            "/biometric/enroll",
            headers=kiosk_headers,
            data={
                "ticket": ticket,
                "faceChallengeId": challenge["faceChallengeId"],
                "consent": consent.version(),
            },
            files=[("frames", (f"{i}.png", b"\x89PNG", "image/png")) for i in range(9)],
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_frames"
        assert fake_engine.calls == []

    async def test_the_consent_is_stored_with_the_face(
        self, client, db, fake_engine, kiosk_headers, face_headers
    ):
        assert (await enrol_at_kiosk(client, kiosk_headers, face_headers)).is_success

        rows = list(await db.scalars(select(FaceTemplate)))
        assert {row.consent_version for row in rows} == {consent.version()}
        assert all(row.consented_at is not None for row in rows)

    @pytest.mark.parametrize("given", [None, "an-older-version"])
    async def test_no_consent_to_the_current_text_enrols_nobody(
        self, client, db, fake_engine, kiosk_headers, face_headers, given
    ):
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()
        payload = {"ticket": ticket, "faceChallengeId": challenge["faceChallengeId"]}

        refused = await client.post(
            "/biometric/enroll",
            headers=kiosk_headers,
            data=payload if given is None else {**payload, "consent": given},
            files=frames(9),
        )
        assert refused.status_code == 422
        if given:
            assert refused.json()["code"] == "consent_required"
        assert fake_engine.calls == []
        assert await db.scalar(select(FaceTemplate.id)) is None

        # Asking the person again is the fix, so the capture is still good.
        agreed = await client.post(
            "/biometric/enroll",
            headers=kiosk_headers,
            data={**payload, "consent": consent.version()},
            files=frames(9),
        )
        assert agreed.status_code == 201

    async def test_a_face_challenge_is_good_for_one_capture(
        self, client, fake_engine, kiosk_headers, face_headers
    ):
        fake_engine.enroll_result = EnrollResult(
            usable=False, reasons=["too_dark"], model_version=VERSION
        )
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()
        payload = {
            "ticket": ticket,
            "faceChallengeId": challenge["faceChallengeId"],
            "consent": consent.version(),
        }
        await client.post(
            "/biometric/enroll", headers=kiosk_headers, data=payload, files=frames(9)
        )
        replay = await client.post(
            "/biometric/enroll", headers=kiosk_headers, data=payload, files=frames(9)
        )
        assert replay.status_code == 404
        assert replay.json()["code"] == "face_challenge_invalid"

    async def test_enrolling_again_replaces_the_face(
        self, client, db, fake_engine, kiosk_headers, face_headers
    ):
        await enrol_at_kiosk(client, kiosk_headers, face_headers)
        fake_engine.enroll_result = fake_engine.enroll_result.model_copy(
            update={"embeddings": VECTORS[:1], "qualities": [9.0], "sources": [0]}
        )
        await enrol_at_kiosk(client, kiosk_headers, face_headers)
        assert len(list(await db.scalars(select(FaceTemplate)))) == 1

    async def test_the_audit_log_names_the_kiosk_and_the_person_but_no_ticket(
        self, client, db, fake_engine, kiosk_headers, face_headers, admin_user
    ):
        await enrol_at_kiosk(client, kiosk_headers, face_headers)
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "POST /biometric/enroll")
        )
        assert event is not None
        assert event.actor_client == "kiosk"
        assert event.target == str(admin_user.id)
        assert "ticket" not in str(event.detail)

    async def test_kept_photos_are_encrypted_and_go_with_the_face(
        self,
        client,
        db,
        fake_engine,
        kiosk_headers,
        face_headers,
        storage,
        monkeypatch,
        admin_user,
    ):
        from provider.biometric.deps import face_storage
        from provider.core.app import app

        monkeypatch.setattr(settings, "iden_biometric_keep_images", True)
        app.dependency_overrides[face_storage] = lambda: storage
        await enrol_at_kiosk(client, kiosk_headers, face_headers)

        rows = list(await db.scalars(select(FaceTemplate)))
        keys = [row.image_key for row in rows]
        assert all(keys)
        best = next(row for row in rows if row.quality == 3.0)
        assert best.image_key is not None
        sealed = await storage.get(best.image_key)
        assert sealed is not None and b"frame 0" not in sealed
        assert decrypt_bytes(sealed, context=str(admin_user.id)) == b"\xff\xd8 frame 0"

        await client.delete("/entity/face", headers=face_headers)
        assert [await storage.get(key) for key in keys if key] == [None] * 3


class TestSelfService:
    async def test_status_says_where_the_face_was_enrolled(
        self, client, face_enrolled, face_headers
    ):
        body = (await client.get("/entity/face", headers=face_headers)).json()
        assert body["enrolled"] is True
        assert body["enrolledBy"] == "Biometric Kiosk"
        assert body["samples"] == 3

    async def test_a_person_can_remove_their_face(
        self, client, face_enrolled, face_headers
    ):
        assert (
            await client.delete("/entity/face", headers=face_headers)
        ).status_code == 204
        body = (await client.get("/entity/face", headers=face_headers)).json()
        assert body == {
            "enrolled": False,
            "enrolledAt": None,
            "enrolledBy": None,
            "samples": 0,
        }

    async def test_an_administrator_can_remove_someone_elses(
        self, client, db, face_enrolled, token_for, catalogue, admin_user
    ):
        # The account holds `biometric:enroll`, so only someone who holds it too
        # may change it — see admin.delegation.
        headers = await token_for(
            *[v for v in catalogue["scopes"] if v.startswith(("admin:", "biometric:"))]
        )
        response = await client.delete(
            f"/admin/users/{admin_user.id}/face", headers=headers
        )
        assert response.status_code == 204
        assert await db.scalar(select(FaceTemplate.id)) is None


@pytest.mark.usefixtures("dashboard")
class TestSignIn:
    async def test_face_is_a_second_factor_only(self, client, face_enrolled):
        challenge_id = await begin(client)
        response = await client.post(
            "/api/v1/auth/biometric/challenge", json={"challengeId": challenge_id}
        )
        assert response.status_code == 401

    async def test_an_enrolled_face_alone_does_not_demand_itself(
        self, client, face_enrolled
    ):
        """Someone at a laptop without a camera must still be able to sign in."""
        challenge_id = await begin(client)
        body = (await sign_in(client, challenge_id)).json()
        assert body["status"] == "complete"

    async def test_a_client_asking_for_mfa_face_gets_a_face_step(
        self, client, fake_engine, face_enrolled
    ):
        verifier, challenge = pkce_pair()
        response = await start(client, challenge, acr_values="urn:iden:acr:mfa-face")
        challenge_id = query_of(response)["challenge"]

        password = (await sign_in(client, challenge_id)).json()
        step = (await face_step(client, challenge_id)).json()
        code = query_of(await client.get(step["resumeUrl"]))["code"]
        tokens = (
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
        claims = decode(tokens["id_token"])

        assert password["methods"] == ["face"]
        assert step["status"] == "complete"
        assert claims["acr"] == "urn:iden:acr:mfa-face"
        assert set(claims["amr"]) == {"pwd", "face", "mfa"}
        assert fake_engine.templates_seen and len(fake_engine.templates_seen) == 3

    async def test_a_face_answers_the_second_factor_an_authenticator_demands(
        self, client, db, admin_user, fake_engine, face_enrolled
    ):
        from tests.test_auth_code_flow import enrol

        await enrol(db, admin_user)
        challenge_id = await begin(client)

        password = (await sign_in(client, challenge_id)).json()
        step = (await face_step(client, challenge_id)).json()

        assert password["methods"] == ["face", "otp"]
        assert step["status"] == "complete"

    async def test_a_rejected_face_counts_against_the_account(
        self, client, fake_engine, face_enrolled
    ):
        fake_engine.verify_result = fake_engine.verify_result.model_copy(
            update={"matched": False}
        )
        challenge_id = await begin(client, acr_values="urn:iden:acr:mfa-face")
        await sign_in(client, challenge_id)

        tries = [(await face_step(client, challenge_id)).json() for _ in range(3)]
        assert [t["code"] for t in tries] == ["face_rejected"] * 3
        assert [t["details"]["attemptsLeft"] for t in tries] == [2, 1, 0]
        assert 0 < tries[-1]["details"]["retryAfter"] <= 900
        assert "retryAfter" not in tries[0]["details"]

        # Out of tries, refused before another capture is asked for.
        refused = await client.post(
            "/api/v1/auth/biometric/challenge", json={"challengeId": challenge_id}
        )
        assert refused.status_code == 429
        assert int(refused.headers["retry-after"]) > 0

    async def test_a_match_that_is_not_live_is_not_an_authentication(
        self, client, fake_engine, face_enrolled
    ):
        fake_engine.verify_result = fake_engine.verify_result.model_copy(
            update={"live": False, "checks": SPOOF}
        )
        challenge_id = await begin(client, acr_values="urn:iden:acr:mfa-face")
        await sign_in(client, challenge_id)

        response = await face_step(client, challenge_id)

        assert response.status_code == 401
        # Not said which: an attacker tuning a spoof learns nothing.
        assert response.json()["code"] == "face_rejected"

    async def test_bad_light_does_not_count_as_a_failure(
        self, client, fake_engine, face_enrolled
    ):
        fake_engine.verify_result = VerifyResult(
            usable=False, reasons=["too_dark"], model_version=VERSION
        )
        challenge_id = await begin(client, acr_values="urn:iden:acr:mfa-face")
        await sign_in(client, challenge_id)

        statuses = [
            (await face_step(client, challenge_id)).status_code for _ in range(7)
        ]

        assert statuses == [422] * 7

    async def test_a_face_from_an_earlier_model_must_be_enrolled_again(
        self, client, fake_engine, face_enrolled
    ):
        fake_engine.verify_result = fake_engine.verify_result.model_copy(
            update={"model_version": "test-model-2"}
        )
        challenge_id = await begin(client, acr_values="urn:iden:acr:mfa-face")
        await sign_in(client, challenge_id)

        response = await face_step(client, challenge_id)

        assert response.status_code == 409
        assert response.json()["code"] == "face_enrolment_outdated"

    async def test_without_an_enrolled_face_there_is_nothing_to_capture(
        self, client, admin_user
    ):
        challenge_id = await begin(client)
        await sign_in(client, challenge_id)
        response = await client.post(
            "/api/v1/auth/biometric/challenge", json={"challengeId": challenge_id}
        )
        assert response.status_code == 404
        assert response.json()["code"] == "face_not_enrolled"

    async def test_an_unreachable_engine_is_a_503(
        self, client, face_enrolled, monkeypatch
    ):
        """The client is built once, at import, from the configured URL; changing
        the setting here would leave it pointing at a real engine, if one runs."""
        from provider.biometric import engine_client
        from provider.core.app import app

        app.dependency_overrides.pop(get_engine)
        unreachable = httpx.AsyncClient(base_url="http://127.0.0.1:9")
        monkeypatch.setattr(engine_client, "client", unreachable)
        challenge_id = await begin(client, acr_values="urn:iden:acr:mfa-face")
        await sign_in(client, challenge_id)

        response = await face_step(client, challenge_id)

        assert response.status_code == 503
        assert response.json()["code"] == "engine_unavailable"


class TestChallenges:
    async def test_enrolment_steps_follow_the_actions_drawn(self, redis, admin_user):
        challenge = await challenges.issue(redis, admin_user.id, "enrol")

        assert len(set(challenge.actions)) == 2
        assert challenge.steps == ["center"] * 3 + [
            a for a in challenge.actions for _ in range(3)
        ]

    async def test_sign_in_asks_for_no_movements(self, redis, admin_user):
        challenge = await challenges.issue(redis, admin_user.id, "login")

        assert challenge.steps == ["center"] * 3

    async def test_a_challenge_is_only_for_its_person_and_purpose(
        self, redis, admin_user, member
    ):
        first = await challenges.issue(redis, admin_user.id, "login")
        second = await challenges.issue(redis, admin_user.id, "login")

        assert await challenges.consume(redis, first.id, member.id, "login") is None
        assert (
            await challenges.consume(redis, second.id, admin_user.id, "enrol") is None
        )


class TestReembed:
    async def test_kept_photos_move_to_the_new_model_and_others_are_reported(
        self, db, storage, admin_user, member
    ):
        from provider.core.security import encrypt_bytes
        from scripts.reembed_faces import reembed

        def template(user, key):
            return FaceTemplate(
                user_id=user.id,
                model_version="old-model",
                embedding_encrypted=service.pack([0.0, 1.0, 0.0, 0.0], user.id),
                quality=1.0,
                enrolled_by="kiosk",
                image_key=key,
            )

        await storage.put(
            "faces/a", encrypt_bytes(b"photo", context=str(admin_user.id)), "x"
        )
        db.add_all([template(admin_user, "faces/a"), template(member, None)])
        await db.commit()

        report = await reembed(db, FakeEngine(), storage)

        assert (report.moved, report.without_photos) == (1, 1)
        moved = await db.scalar(
            select(FaceTemplate).where(FaceTemplate.user_id == admin_user.id)
        )
        assert moved is not None and moved.model_version == VERSION
        assert service.unpack(moved.embedding_encrypted, admin_user.id) == (
            pytest.approx([0.9, 0.1, 0.0, 0.0])
        )


async def test_attempts_at_once_cannot_exceed_the_limit(redis):
    """Each capture counts one attempt. Read-modify-write let concurrent
    captures each see the same count, so a ticket could outlast its limit.
    Repeated because the interleaving that breaks it does not happen every time."""
    import asyncio
    import uuid

    from provider.biometric import tickets

    for _ in range(25):
        ticket, _ = await tickets.issue(redis, uuid.uuid7())

        results = await asyncio.gather(
            *(tickets.holder(redis, ticket, attempt=True) for _ in range(10))
        )

        assert sum(r is not None for r in results) == tickets.MAX_ATTEMPTS
