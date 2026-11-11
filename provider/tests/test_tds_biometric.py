"""TDS sections A4, B10 and B11 (face step): the face second factor, with the fake engine."""

import pytest

from provider.core.config import settings
from tests.biometric import begin, face_step, frames
from tests.flows import sign_in

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

MFA_FACE = "urn:iden:acr:mfa-face"


@pytest.fixture(autouse=True)
def biometric_on(monkeypatch):
    # Before `catalogue` seeds the scopes the flag adds, as in test_biometric.
    monkeypatch.setattr(settings, "iden_biometric_enabled", True)


class TestA4VerifyWithoutAFace:
    """`biometric.service.verify` finding no templates."""

    async def test_a_face_removed_mid_sign_in_is_404_face_not_enrolled(
        self, client, face_enrolled, face_headers
    ):
        """If the face is removed after the face challenge was issued, the capture is refused with 404 face_not_enrolled, not a 500."""
        challenge_id = await begin(client, acr_values=MFA_FACE)
        await sign_in(client, challenge_id)
        issued = await client.post(
            "/api/v1/auth/biometric/challenge", json={"challengeId": challenge_id}
        )
        assert issued.status_code == 200, issued.text

        removed = await client.delete("/entity/face", headers=face_headers)
        assert removed.status_code == 204

        response = await client.post(
            "/api/v1/auth/biometric",
            data={
                "challengeId": challenge_id,
                "faceChallengeId": issued.json()["faceChallengeId"],
            },
            files=frames(len(issued.json()["steps"])),
        )

        assert response.status_code == 404
        assert response.json()["code"] == "face_not_enrolled"


class TestWB3FrameCountAtSignIn:
    """`biometric.service.verify` → `_matches_challenge`, reached from sign-in rather than enrolment."""

    async def test_too_few_frames_at_sign_in_is_422_invalid_frames(
        self, client, fake_engine, face_enrolled
    ):
        """WB-3 P2: during face sign-in, uploading 2 frames for a 3-step challenge is refused with 422 invalid_frames before the engine is asked."""
        challenge_id = await begin(client, acr_values=MFA_FACE)
        await sign_in(client, challenge_id)
        fake_engine.calls.clear()

        response = await face_step(client, challenge_id, count=2)

        assert response.status_code == 422
        assert response.json()["code"] == "invalid_frames"
        assert response.json()["message"] == "Expected 3 frames, received 2."
        assert fake_engine.calls == []


class TestB10QualityBeforeVersion:
    async def test_a_poor_capture_is_reported_before_an_outdated_enrolment(
        self, client, fake_engine, face_enrolled
    ):
        """A bad-quality capture under a changed model version is answered 422 poor_capture (what the person can fix) rather than 409."""
        fake_engine.verify_result = fake_engine.verify_result.model_copy(
            update={
                "model_version": "test-model-2",
                "usable": False,
                "reasons": ["too_dark"],
                "live": False,
                "matched": False,
            }
        )
        challenge_id = await begin(client, acr_values=MFA_FACE)
        await sign_in(client, challenge_id)

        response = await face_step(client, challenge_id)

        assert response.status_code == 422, (
            f"{response.status_code} {response.json().get('code')}"
        )
        assert response.json()["code"] == "poor_capture"


class TestB11CookieAfterFace:
    async def test_the_face_step_refreshes_the_session_cookie(
        self, client, fake_engine, face_enrolled
    ):
        """After a successful face step the response re-sets iden_session with Max-Age equal to the sliding session TTL."""
        challenge_id = await begin(client, acr_values=MFA_FACE)
        await sign_in(client, challenge_id)

        response = await face_step(client, challenge_id)

        assert response.status_code == 200, response.text
        cookie = response.headers.get("set-cookie", "")
        assert "iden_session=" in cookie, (
            f"no Set-Cookie for iden_session after face: {cookie!r}"
        )
        assert f"Max-Age={settings.iden_session_ttl}" in cookie
