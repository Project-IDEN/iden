"""Face enrolment at a kiosk, and face as a second factor at sign-in.

The engine is replaced by a fake that returns whatever verdict a test sets: the
engine's own judgement is tested in engine/, and what matters here is what the
provider does with one.
"""

import jwt
import pytest
from sqlalchemy import select

from provider.biometric import challenges, service
from provider.biometric.engine_client import (
    Checks,
    EmbedResult,
    EnrollResult,
    VerifyResult,
    get_engine,
)
from provider.core import notifier
from provider.core.config import settings
from provider.core.security import decrypt_bytes
from provider.shared.models import AuditEvent, ClientScope, FaceTemplate
from tests.conftest import REDIRECT_URI
from tests.flows import pkce_pair, query_of, sign_in, start

VERSION = "test-model-1"
LIVE = Checks(
    anti_spoofing=True,
    anti_spoofing_score=0.97,
    actions=True,
    flash=True,
    flash_score=1.0,
    consistent=True,
)
SPOOF = LIVE.model_copy(update={"anti_spoofing": False, "flash": False})
VECTORS = [[0.1, 0.2, 0.3, 0.4], [0.2, 0.1, 0.4, 0.3], [0.3, 0.3, 0.2, 0.2]]


@pytest.fixture(autouse=True)
def biometric_on(monkeypatch):
    # Autouse, so it runs before `catalogue` seeds the scopes the flag adds.
    monkeypatch.setattr(settings, "iden_biometric_enabled", True)


class FakeEngine:
    def __init__(self) -> None:
        self.enroll_result = EnrollResult(
            usable=True,
            reasons=[],
            checks=LIVE,
            live=True,
            model_version=VERSION,
            embeddings=VECTORS,
            qualities=[3.0, 2.0, 1.0],
            sources=[0, 2, 1],
        )
        self.verify_result = VerifyResult(
            usable=True,
            reasons=[],
            checks=LIVE,
            live=True,
            model_version=VERSION,
            matched=True,
            similarity=0.83,
        )
        self.calls: list[tuple[str, int, list[str]]] = []
        self.templates_seen: list[list[float]] = []

    async def enroll(self, frames, steps):
        self.calls.append(("enroll", len(frames), steps))
        return self.enroll_result

    async def verify(self, frames, steps, templates):
        self.calls.append(("verify", len(frames), steps))
        self.templates_seen = templates
        return self.verify_result

    async def embed(self, frames):
        return EmbedResult(model_version=VERSION, embeddings=[])


@pytest.fixture
def fake_engine(client):
    from provider.core.app import app

    fake = FakeEngine()
    app.dependency_overrides[get_engine] = lambda: fake
    return fake


@pytest.fixture
def mail(monkeypatch):
    sent: list[dict] = []

    async def capture(**message):
        sent.append(message)

    monkeypatch.setattr(notifier, "send", capture)
    return sent


@pytest.fixture
async def kiosk_headers(client, db, kiosk, scope_of):
    kiosk_client, secret = kiosk
    db.add(
        ClientScope(
            client_id=kiosk_client.id,
            scope_id=scope_of("biometric:enroll").id,
            grantable=False,
            granted=True,
        )
    )
    await db.commit()
    response = await client.post(
        "/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "kiosk",
            "client_secret": secret,
            "scope": "biometric:enroll",
        },
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def face_headers(token_for):
    return await token_for("entity:face:read", "entity:face:write")


def frames(count: int) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("frames", (f"{i}.jpg", b"\xff\xd8 frame %d" % i, "image/jpeg"))
        for i in range(count)
    ]


async def new_ticket(client, face_headers) -> str:
    response = await client.post("/entity/face/ticket", headers=face_headers)
    assert response.status_code == 201
    return response.json()["ticket"]


async def kiosk_capture(client, kiosk_headers, ticket: str):
    response = await client.post(
        "/biometric/enroll/challenge", headers=kiosk_headers, json={"ticket": ticket}
    )
    return response


async def enrol_at_kiosk(client, kiosk_headers, face_headers):
    ticket = await new_ticket(client, face_headers)
    challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()
    return await client.post(
        "/biometric/enroll",
        headers=kiosk_headers,
        data={"ticket": ticket, "faceChallengeId": challenge["faceChallengeId"]},
        files=frames(len(challenge["steps"])),
    )


@pytest.fixture
async def enrolled(client, fake_engine, kiosk_headers, face_headers, mail):
    response = await enrol_at_kiosk(client, kiosk_headers, face_headers)
    assert response.status_code == 201, response.text


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
        assert len(body["steps"]) == 3 + 2 * 3 + 4
        assert body["flashSlotMs"] > 0

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
    async def test_enrolment_stores_encrypted_embeddings_and_tells_the_person(
        self, client, db, fake_engine, kiosk_headers, face_headers, mail, admin_user
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
        assert mail and mail[0]["to"] == admin_user.email

    async def test_the_engine_is_asked_for_exactly_the_challenge(
        self, client, fake_engine, kiosk_headers, face_headers, mail
    ):
        await enrol_at_kiosk(client, kiosk_headers, face_headers)
        kind, count, steps = fake_engine.calls[0]
        assert kind == "enroll"
        assert count == len(steps) == 13

    async def test_a_ticket_enrols_once(
        self, client, fake_engine, kiosk_headers, face_headers, mail
    ):
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()
        payload = {"ticket": ticket, "faceChallengeId": challenge["faceChallengeId"]}
        first = await client.post(
            "/biometric/enroll", headers=kiosk_headers, data=payload, files=frames(13)
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
            data={"ticket": ticket, "faceChallengeId": challenge["faceChallengeId"]},
            files=frames(13),
        )

        assert response.status_code == 422
        assert response.json()["code"] == "not_live"
        assert response.json()["details"]["failed"] == ["anti_spoofing", "flash"]
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
            data={"ticket": ticket, "faceChallengeId": challenge["faceChallengeId"]},
            files=frames(5),
        )
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_frames"
        assert fake_engine.calls == []

    async def test_a_face_challenge_is_good_for_one_capture(
        self, client, fake_engine, kiosk_headers, face_headers
    ):
        fake_engine.enroll_result = EnrollResult(
            usable=False, reasons=["too_dark"], model_version=VERSION
        )
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()
        payload = {"ticket": ticket, "faceChallengeId": challenge["faceChallengeId"]}
        await client.post(
            "/biometric/enroll", headers=kiosk_headers, data=payload, files=frames(13)
        )
        replay = await client.post(
            "/biometric/enroll", headers=kiosk_headers, data=payload, files=frames(13)
        )
        assert replay.status_code == 404
        assert replay.json()["code"] == "face_challenge_invalid"

    async def test_enrolling_again_replaces_the_face(
        self, client, db, fake_engine, kiosk_headers, face_headers, mail
    ):
        await enrol_at_kiosk(client, kiosk_headers, face_headers)
        fake_engine.enroll_result = fake_engine.enroll_result.model_copy(
            update={"embeddings": VECTORS[:1], "qualities": [9.0], "sources": [0]}
        )
        await enrol_at_kiosk(client, kiosk_headers, face_headers)
        assert len(list(await db.scalars(select(FaceTemplate)))) == 1

    async def test_the_audit_log_names_the_kiosk_and_the_person_but_no_ticket(
        self, client, db, fake_engine, kiosk_headers, face_headers, mail, admin_user
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
        mail,
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
        self, client, enrolled, face_headers
    ):
        body = (await client.get("/entity/face", headers=face_headers)).json()
        assert body["enrolled"] is True
        assert body["enrolledBy"] == "Biometric Kiosk"
        assert body["samples"] == 3

    async def test_a_person_can_remove_their_face(self, client, enrolled, face_headers):
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
        self, client, db, enrolled, token_for, catalogue, admin_user
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


async def begin(client, **params) -> str:
    _, challenge = pkce_pair()
    return query_of(await start(client, challenge, **params))["challenge"]


async def face_step(client, challenge_id: str, count: int | None = None):
    issued = await client.post(
        "/api/v1/auth/biometric/challenge", json={"challengeId": challenge_id}
    )
    assert issued.status_code == 200, issued.text
    body = issued.json()
    return await client.post(
        "/api/v1/auth/biometric",
        data={"challengeId": challenge_id, "faceChallengeId": body["faceChallengeId"]},
        files=frames(count or len(body["steps"])),
    )


@pytest.mark.usefixtures("dashboard")
class TestSignIn:
    async def test_face_is_a_second_factor_only(self, client, enrolled):
        challenge_id = await begin(client)
        response = await client.post(
            "/api/v1/auth/biometric/challenge", json={"challengeId": challenge_id}
        )
        assert response.status_code == 401

    async def test_an_enrolled_face_alone_does_not_demand_itself(
        self, client, enrolled
    ):
        """Someone at a laptop without a camera must still be able to sign in."""
        challenge_id = await begin(client)
        body = (await sign_in(client, challenge_id)).json()
        assert body["status"] == "complete"

    async def test_a_client_asking_for_mfa_face_gets_a_face_step(
        self, client, fake_engine, enrolled
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
        self, client, db, admin_user, fake_engine, enrolled
    ):
        from tests.test_auth_code_flow import enrol

        await enrol(db, admin_user)
        challenge_id = await begin(client)

        password = (await sign_in(client, challenge_id)).json()
        step = (await face_step(client, challenge_id)).json()

        assert password["methods"] == ["face", "otp"]
        assert step["status"] == "complete"

    async def test_a_rejected_face_counts_against_the_account(
        self, client, fake_engine, enrolled
    ):
        fake_engine.verify_result = fake_engine.verify_result.model_copy(
            update={"matched": False}
        )
        challenge_id = await begin(client, acr_values="urn:iden:acr:mfa-face")
        await sign_in(client, challenge_id)

        statuses = [
            (await face_step(client, challenge_id)).status_code for _ in range(6)
        ]

        assert statuses == [401] * 5 + [429]

    async def test_a_match_that_is_not_live_is_not_an_authentication(
        self, client, fake_engine, enrolled
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
        self, client, fake_engine, enrolled
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
        self, client, fake_engine, enrolled
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

    async def test_an_unreachable_engine_is_a_503(self, client, enrolled, monkeypatch):
        from provider.core.app import app

        app.dependency_overrides.pop(get_engine)
        monkeypatch.setattr(settings, "iden_engine_base_url", "http://127.0.0.1:9")
        challenge_id = await begin(client, acr_values="urn:iden:acr:mfa-face")
        await sign_in(client, challenge_id)

        response = await face_step(client, challenge_id)

        assert response.status_code == 503
        assert response.json()["code"] == "engine_unavailable"


class TestChallenges:
    async def test_steps_follow_the_actions_and_colours_drawn(self, redis, admin_user):
        challenge = await challenges.issue(redis, admin_user.id, "login")
        steps = challenge.steps

        assert steps[:3] == ["center"] * 3
        assert steps[3:9] == [a for a in challenge.actions for _ in range(3)]
        assert steps[9:] == [f"flash:{c}" for c in challenge.colours]

    async def test_colours_change_every_slot_and_all_appear(self, redis, admin_user):
        for _ in range(50):
            colours = (await challenges.issue(redis, admin_user.id, "login")).colours
            assert set(colours) == {"red", "green", "blue"}
            assert all(a != b for a, b in zip(colours, colours[1:], strict=False))

    async def test_a_challenge_is_only_for_its_person_and_purpose(
        self, redis, admin_user, member
    ):
        first = await challenges.issue(redis, admin_user.id, "login")
        second = await challenges.issue(redis, admin_user.id, "login")

        assert await challenges.consume(redis, first.id, member.id, "login") is None
        assert (
            await challenges.consume(redis, second.id, admin_user.id, "enrol") is None
        )
