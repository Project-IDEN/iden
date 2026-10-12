import numpy as np

from engine import quality
from engine.detect import Face
from engine.pose import Pose
from tests.conftest import MANIFEST

RULES = MANIFEST.quality
FRONT = Pose(yaw=0.0, pitch=0.7, eye_distance=60)


def _face(size: float) -> Face:
    return Face(np.array([0, 0, size, size]), 0.9, np.zeros((5, 2)))


def _textured(level: int) -> np.ndarray:
    rng = np.random.default_rng(0)
    noise = rng.integers(-40, 40, (112, 112, 1))
    return np.clip(level + noise, 0, 255).repeat(3, axis=2).astype(np.uint8)


def test_face_count():
    assert quality.face_count_reason([]) == "no_face"
    assert quality.face_count_reason([_face(100)]) is None
    assert quality.face_count_reason([_face(100), _face(80)]) == "multiple_faces"
    # Someone small in the background is not a second person in view.
    assert quality.face_count_reason([_face(100), _face(30)]) is None


def test_a_good_frame_has_no_reasons():
    assert quality.assess(_textured(128), FRONT, RULES, frontal=True) == []


def test_dark_bright_blurred_small_and_turned_frames_say_so():
    assert "too_dark" in quality.assess(_textured(20), FRONT, RULES, frontal=True)
    assert "too_bright" in quality.assess(_textured(240), FRONT, RULES, frontal=True)
    flat = np.full((112, 112, 3), 128, dtype=np.uint8)
    assert "blurred" in quality.assess(flat, FRONT, RULES, frontal=True)
    small = Pose(yaw=0.0, pitch=0.7, eye_distance=20)
    assert "too_small" in quality.assess(_textured(128), small, RULES, frontal=True)
    turned = Pose(yaw=0.5, pitch=0.7, eye_distance=60)
    assert "off_angle" in quality.assess(_textured(128), turned, RULES, frontal=True)
    assert "off_angle" not in quality.assess(
        _textured(128), turned, RULES, frontal=False
    )
