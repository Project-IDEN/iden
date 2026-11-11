"""TDS section C: the provider against the real biometric engine — no fake.

Skipped unless the engine answers `GET /health/ready` at IDEN_ENGINE_BASE_URL.
Start it with the engine overlay, then run `uv run pytest -m integration`:

    IDEN_BIOMETRIC_ENABLED=true docker compose -f deploy/docker-compose.yml \
        -f deploy/docker-compose.engine-gpu.yml up -d postgres redis engine

The engine is reached with the token in provider/keys/engine.token, which the
engine overlay mounts as its ENGINE_TOKEN_FILE.

Faces (engine/tests/data/README.md has the sources): `astronaut.jpg` is the
enrolled person, `sunita_williams.jpg` a different one. Both are still
photographs, which settles what can be tested end to end:

- Sign-in sends three frames looking straight ahead and asks for no movement,
  so a still photograph is a valid sign-in capture.
- Enrolment asks for two random actions: head movements, a blink, a smile. A
  still photograph cannot perform them, so a real enrolment needs a real
  capture: `engine/scripts/capture_actions.py` writes `<step>_<n>.jpg`
  (`center_0.jpg` … `smile_2.jpg`, all six actions) to
  engine/tests/data/actions/, and `test_a_real_capture_enrols_encrypted_templates`
  runs. Without them it is skipped, and the faces the sign-in tests compare
  against are seeded through the engine's own `/embed` — the path re-embedding
  after a model upgrade uses — rather than through a fake.
"""

import base64
import io
from pathlib import Path

import httpx
import jwt
import pytest
from PIL import Image
from sqlalchemy import func, select

from provider.biometric import consent, service
from provider.biometric.engine_client import HttpEngine
from provider.core.config import settings
from provider.core.security import decrypt_secret
from provider.shared.models import FaceTemplate
from tests.biometric import new_ticket
from tests.conftest import REDIRECT_URI
from tests.flows import pkce_pair, query_of, sign_in, start

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("admin_user", "dashboard"),
]

DATA = Path(__file__).resolve().parents[2] / "engine" / "tests" / "data"
ENROLLED = DATA / "astronaut.jpg"
STRANGER = DATA / "sunita_williams.jpg"
CAPTURE = DATA / "actions"
CAPTURED_STEPS = (
    "center",
    "turn_left",
    "turn_right",
    "look_up",
    "look_down",
    "blink",
    "smile",
)
MFA_FACE = "urn:iden:acr:mfa-face"


@pytest.fixture(scope="module", autouse=True)
def engine_reachable():
    try:
        ready = httpx.get(f"{settings.iden_engine_base_url}/health/ready", timeout=5)
    except httpx.HTTPError as exc:
        pytest.skip(f"engine unreachable at {settings.iden_engine_base_url}: {exc!r}")
    if ready.status_code != 200:
        pytest.skip(f"engine not ready: {ready.status_code} {ready.text}")


@pytest.fixture(autouse=True)
def biometric_on(monkeypatch):
    monkeypatch.setattr(settings, "iden_biometric_enabled", True)


def files(frames: list[bytes], content_type: str = "image/jpeg"):
    return [
        ("frames", (f"{i}.jpg", data, content_type)) for i, data in enumerate(frames)
    ]


@pytest.fixture
async def seeded_face(db, admin_user):
    """The administrator's face, embedded by the real engine from `astronaut.jpg`."""
    result = await HttpEngine().embed([ENROLLED.read_bytes()])
    assert result.embeddings[0] is not None, "the engine found no face in astronaut.jpg"
    db.add(
        FaceTemplate(
            user_id=admin_user.id,
            model_version=result.model_version,
            embedding_encrypted=service.pack(result.embeddings[0], admin_user.id),
            quality=1.0,
            enrolled_by="tds-seed",
        )
    )
    await db.commit()


async def face_sign_in(client, frames: list[bytes], content_type: str = "image/jpeg"):
    """Password, then a face step with `frames`. Returns (verifier, response)."""
    verifier, challenge = pkce_pair()
    challenge_id = query_of(await start(client, challenge, acr_values=MFA_FACE))[
        "challenge"
    ]
    password = await sign_in(client, challenge_id)
    assert password.json()["status"] == "method_required", password.text
    issued = await client.post(
        "/api/v1/auth/biometric/challenge", json={"challengeId": challenge_id}
    )
    assert issued.status_code == 200, issued.text
    response = await client.post(
        "/api/v1/auth/biometric",
        data={
            "challengeId": challenge_id,
            "faceChallengeId": issued.json()["faceChallengeId"],
        },
        files=files(frames, content_type),
    )
    return verifier, response


class TestC1Enrolment:
    async def test_a_still_photograph_cannot_enrol(
        self, client, db, admin_user, kiosk_headers, face_headers, mail
    ):
        """Enrolling from nine copies of one still photo is refused 422 not_live by the real engine and stores no template."""
        ticket = await new_ticket(client, face_headers)
        challenge = (
            await client.post(
                "/biometric/enroll/challenge",
                headers=kiosk_headers,
                json={"ticket": ticket},
            )
        ).json()

        response = await client.post(
            "/biometric/enroll",
            headers=kiosk_headers,
            data={
                "ticket": ticket,
                "faceChallengeId": challenge["faceChallengeId"],
                "consent": consent.version(),
            },
            files=files([ENROLLED.read_bytes()] * len(challenge["steps"])),
        )

        assert response.status_code == 422, response.text
        assert response.json()["code"] == "not_live"
        assert "actions" in response.json()["details"]["failed"]
        stored = await db.scalar(
            select(func.count())
            .select_from(FaceTemplate)
            .where(FaceTemplate.user_id == admin_user.id)
        )
        assert stored == 0

    @pytest.mark.skipif(
        not all(
            (CAPTURE / f"{step}_{n}.jpg").is_file()
            for step in CAPTURED_STEPS
            for n in range(3)
        ),
        reason=f"no capture of every action in {CAPTURE}",
    )
    async def test_a_real_capture_enrols_encrypted_templates(
        self, client, db, admin_user, kiosk_headers, face_headers, mail
    ):
        """A real capture following the challenge enrols through /biometric and stores only AES-GCM-encrypted 512-d embeddings."""
        ticket = await new_ticket(client, face_headers)
        challenge = (
            await client.post(
                "/biometric/enroll/challenge",
                headers=kiosk_headers,
                json={"ticket": ticket},
            )
        ).json()
        seen: dict[str, int] = {}
        frames = []
        for step in challenge["steps"]:
            index = seen.get(step, 0)
            seen[step] = index + 1
            frames.append((CAPTURE / f"{step}_{index}.jpg").read_bytes())

        response = await client.post(
            "/biometric/enroll",
            headers=kiosk_headers,
            data={
                "ticket": ticket,
                "faceChallengeId": challenge["faceChallengeId"],
                "consent": consent.version(),
            },
            files=files(frames),
        )

        assert response.status_code == 201, response.text
        rows = list(
            await db.scalars(
                select(FaceTemplate).where(FaceTemplate.user_id == admin_user.id)
            )
        )
        assert rows and len(rows) == response.json()["samples"]
        for row in rows:
            assert row.embedding_encrypted.startswith("v1:")
            raw = base64.b64decode(
                decrypt_secret(row.embedding_encrypted, context=str(admin_user.id))
            )
            assert len(raw) == 512 * 4


class TestC2SameFace:
    async def test_the_enrolled_face_signs_in(self, client, seeded_face):
        """Three frames of the enrolled person pass the real engine, and the token's amr contains face at acr mfa-face."""
        verifier, response = await face_sign_in(client, [ENROLLED.read_bytes()] * 3)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "complete"
        code = query_of(await client.get(response.json()["resumeUrl"]))["code"]
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
        claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
        assert "face" in claims["amr"]
        assert claims["acr"] == MFA_FACE


class TestC3DifferentFace:
    async def test_another_persons_face_is_rejected(self, client, seeded_face):
        """Three frames of a different person are rejected 401 face_rejected, with one attempt counted."""
        _, response = await face_sign_in(client, [STRANGER.read_bytes()] * 3)

        assert response.status_code == 401, response.text
        assert response.json()["code"] == "face_rejected"
        assert response.json()["details"]["attemptsLeft"] == 2


class TestC4NotAJpeg:
    async def test_a_non_jpeg_frame_is_a_4xx(self, client, seeded_face):
        """A PNG sent as image/jpeg is refused by the real engine and answered 422 invalid_frames, not a 5xx."""
        out = io.BytesIO()
        Image.open(ENROLLED).resize((256, 256)).save(out, format="PNG")
        png = out.getvalue()

        _, response = await face_sign_in(client, [png] * 3)

        assert 400 <= response.status_code < 500, response.text
        assert response.json()["code"] == "invalid_frames"
