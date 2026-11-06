"""TDS sections A4, B10 and B11 (face step): the face second factor, with the fake engine.

The fake engine and the enrolment fixtures are the ones `test_biometric.py`
already uses, imported rather than copied so both files exercise the same
setup.
"""

import pytest

from provider.core.config import settings
from tests import test_biometric as shared
from tests.flows import sign_in
from tests.test_biometric import begin, face_step, frames

# The fixtures `test_biometric.py` drives the fake engine with, bound here so
# pytest finds them in this module too.
enrolled = shared.enrolled
face_headers = shared.face_headers
fake_engine = shared.fake_engine
kiosk_headers = shared.kiosk_headers
mail = shared.mail

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

MFA_FACE = "urn:iden:acr:mfa-face"


@pytest.fixture(autouse=True)
def biometric_on(monkeypatch):
    # Before `catalogue` seeds the scopes the flag adds, as in test_biometric.
    monkeypatch.setattr(settings, "iden_biometric_enabled", True)


class TestA4VerifyWithoutAFace:
    """`biometric/service.py:152` — `verify` finding no templates."""

    async def test_a_face_removed_mid_sign_in_is_404_face_not_enrolled(
        self, client, enrolled, face_headers
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


class TestB10QualityBeforeVersion:
    async def test_a_poor_capture_is_reported_before_an_outdated_enrolment(
        self, client, fake_engine, enrolled
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
        self, client, fake_engine, enrolled
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
