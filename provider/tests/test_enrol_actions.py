"""The enrolment challenge's actions: two of six, a blink and a smile among them.

Sign-in is checked here too, only to show it did not change: it still asks
for no action at all.
"""

import secrets

import pytest

from provider.biometric import challenges, consent
from provider.core.config import settings
from tests.biometric import SPOOF, begin, frames, kiosk_capture, new_ticket
from tests.flows import sign_in

POOL = {"turn_left", "turn_right", "look_up", "look_down", "blink", "smile"}
DRAWS = 300


@pytest.fixture(autouse=True)
def biometric_on(monkeypatch):
    monkeypatch.setattr(settings, "iden_biometric_enabled", True)


@pytest.fixture
def blink_and_smile(monkeypatch):
    """The next enrolment challenges draw `blink` then `smile`."""
    monkeypatch.setattr(
        challenges._random, "sample", lambda population, k: ["blink", "smile"]
    )


class TestTheDraw:
    def test_the_pool_is_the_four_movements_a_blink_and_a_smile(self):
        assert set(challenges.ACTIONS) == POOL
        assert len(challenges.ACTIONS) == len(POOL)

    def test_the_actions_are_drawn_from_the_system_random_source(self):
        assert isinstance(challenges._random, secrets.SystemRandom)

    async def test_always_two_distinct_actions_from_the_pool(self, redis, admin_user):
        drawn = [
            (await challenges.issue(redis, admin_user.id, "enrol")).actions
            for _ in range(DRAWS)
        ]

        for actions in drawn:
            assert len(actions) == 2
            assert len(set(actions)) == 2
            assert set(actions) <= POOL
        # Every action comes up, and so does a blink with a smile: the new pair
        # needs no movement at all.
        assert set().union(*drawn) == POOL
        assert any(set(actions) == {"blink", "smile"} for actions in drawn)

    async def test_the_centre_step_is_always_first(self, redis, admin_user):
        for _ in range(50):
            challenge = await challenges.issue(redis, admin_user.id, "enrol")
            assert challenge.steps[:3] == ["center"] * 3
            assert "center" not in challenge.steps[3:]
            assert challenge.steps[3:] == [
                action for action in challenge.actions for _ in range(3)
            ]

    async def test_the_actions_survive_the_round_trip_through_redis(
        self, redis, admin_user, blink_and_smile
    ):
        issued = await challenges.issue(redis, admin_user.id, "enrol")
        read = await challenges.consume(redis, issued.id, admin_user.id, "enrol")

        assert read is not None
        assert read.actions == ["blink", "smile"]
        assert read.steps == ["center"] * 3 + ["blink"] * 3 + ["smile"] * 3


class TestSignInIsUnchanged:
    async def test_a_sign_in_challenge_never_has_an_action(self, redis, admin_user):
        for _ in range(50):
            challenge = await challenges.issue(redis, admin_user.id, "login")
            assert challenge.actions == []
            assert challenge.steps == ["center"] * 3

    @pytest.mark.usefixtures("admin_user", "dashboard")
    async def test_the_sign_in_api_asks_for_three_frames_straight_ahead(
        self, client, face_enrolled, blink_and_smile
    ):
        challenge_id = await begin(client, acr_values="urn:iden:acr:mfa-face")
        await sign_in(client, challenge_id)

        issued = await client.post(
            "/api/v1/auth/biometric/challenge", json={"challengeId": challenge_id}
        )

        assert issued.status_code == 200, issued.text
        assert issued.json()["steps"] == ["center"] * 3


async def _enrol(client, kiosk_headers, ticket, challenge, count):
    return await client.post(
        "/biometric/enroll",
        headers=kiosk_headers,
        data={
            "ticket": ticket,
            "faceChallengeId": challenge["faceChallengeId"],
            "consent": consent.version(),
        },
        files=frames(count),
    )


class TestTheKioskApi:
    async def test_the_kiosk_is_asked_for_a_blink_and_a_smile(
        self, client, kiosk_headers, face_headers, blink_and_smile
    ):
        ticket = await new_ticket(client, face_headers)
        response = await kiosk_capture(client, kiosk_headers, ticket)

        assert response.status_code == 200, response.text
        assert response.json()["steps"] == (
            ["center"] * 3 + ["blink"] * 3 + ["smile"] * 3
        )

    async def test_the_engine_is_sent_the_new_step_names(
        self, client, fake_engine, kiosk_headers, face_headers, mail, blink_and_smile
    ):
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()

        response = await _enrol(client, kiosk_headers, ticket, challenge, 9)

        assert response.status_code == 201, response.text
        assert fake_engine.calls == [
            ("enroll", 9, ["center"] * 3 + ["blink"] * 3 + ["smile"] * 3)
        ]

    @pytest.mark.parametrize("count", [8, 10])
    async def test_a_wrong_frame_count_for_a_blink_or_smile_is_invalid_frames(
        self, client, fake_engine, kiosk_headers, face_headers, blink_and_smile, count
    ):
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()

        response = await _enrol(client, kiosk_headers, ticket, challenge, count)

        assert response.status_code == 422
        assert response.json()["code"] == "invalid_frames"
        assert fake_engine.calls == []

    async def test_a_missed_blink_is_refused_like_a_missed_movement(
        self, client, fake_engine, kiosk_headers, face_headers, blink_and_smile
    ):
        """The engine reports a blink or smile it did not see as a failed `actions`
        check, so the kiosk hears the same 422 not_live as for a head movement."""
        fake_engine.enroll_result = fake_engine.enroll_result.model_copy(
            update={
                "live": False,
                "checks": SPOOF.model_copy(update={"anti_spoofing": True}),
                "embeddings": [],
            }
        )
        ticket = await new_ticket(client, face_headers)
        challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()

        response = await _enrol(client, kiosk_headers, ticket, challenge, 9)

        assert response.status_code == 422
        assert response.json()["code"] == "not_live"
        assert response.json()["details"]["failed"] == ["actions"]
        # The ticket is still good for another attempt.
        assert (await kiosk_capture(client, kiosk_headers, ticket)).status_code == 200
