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


def _chroma(boost: str) -> np.ndarray:
    base = np.array([0.30, 0.33, 0.37])  # BGR proportions of skin under room light
    base[{"blue": 0, "green": 1, "red": 2}[boost]] += 0.03
    return base / base.sum()


def test_flash_passes_when_the_face_reflects_the_colours_shown():
    shown = ["red", "green", "blue", "red"]
    verdict = liveness.flash([(c, _chroma(c)) for c in shown], RULES)
    assert verdict.passed
    assert verdict.score == 1


def test_flash_fails_when_the_reflection_does_not_follow():
    shown = ["red", "green", "blue", "red"]
    reflected = ["blue", "red", "green", "green"]
    observed = [(c, _chroma(r)) for c, r in zip(shown, reflected, strict=True)]
    assert not liveness.flash(observed, RULES).passed


def test_flash_fails_when_nothing_changes():
    observed = [(c, np.array([0.3, 0.33, 0.37])) for c in ["red", "green", "blue"]]
    assert not liveness.flash(observed, RULES).passed


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
