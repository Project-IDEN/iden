import numpy as np

from engine import liveness
from tests.conftest import MANIFEST

RULES = MANIFEST.liveness
POLICY = MANIFEST.policy
FRONT = liveness.Pose(yaw=0.0, pitch=0.7, eye_distance=60)


def pose(yaw=0.0, pitch=0.7):
    return liveness.Pose(yaw=yaw, pitch=pitch, eye_distance=60)


def test_actions_pass_when_every_movement_is_made():
    performed = {
        "turn_left": [pose(0.02), pose(0.25), pose(0.3)],
        "look_down": [pose(pitch=0.72), pose(pitch=0.85)],
    }
    assert liveness.actions(FRONT, performed, RULES).passed


def test_a_movement_in_the_wrong_direction_fails():
    performed = {"turn_left": [pose(-0.3)], "look_up": [pose(pitch=0.5)]}
    assert not liveness.actions(FRONT, performed, RULES).passed


def test_a_still_face_fails_the_actions():
    performed = {"turn_right": [pose()] * 3, "look_up": [pose()] * 3}
    verdict = liveness.actions(FRONT, performed, RULES)
    assert not verdict.passed
    assert verdict.score == 0


def test_a_small_nod_is_not_a_movement():
    performed = {"look_down": [pose(pitch=0.78)], "turn_left": [pose(0.12)]}
    assert not liveness.actions(FRONT, performed, RULES).passed


def test_anti_spoofing_needs_most_frames_live():
    assert liveness.anti_spoofing([0.9, 0.8, 0.95], POLICY).passed
    assert not liveness.anti_spoofing([0.9, 0.1, 0.2], POLICY).passed
    assert not liveness.anti_spoofing([], POLICY).passed


def test_consistency_catches_a_different_face():
    reference = np.eye(4)[0]
    same = np.array([0.9, 0.43, 0.0, 0.0])
    other = np.eye(4)[1]
    assert liveness.consistency(reference, [same], [same], RULES).passed
    assert not liveness.consistency(reference, [same, other], [], RULES).passed
