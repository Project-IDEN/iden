import numpy as np

from engine import quality
from engine.align import TEMPLATE
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


PICTURE = np.zeros((480, 640, 3), dtype=np.uint8)
CENTRED = Face(np.array([236, 156, 404, 324]), 0.9, TEMPLATE * 1.5 + [236, 156])


def _assess(aligned, pose=FRONT, face=CENTRED, frontal=True):
    return quality.assess(PICTURE, face, aligned, pose, RULES, frontal=frontal)


def test_face_count():
    assert quality.face_count_reason([]) == "no_face"
    assert quality.face_count_reason([_face(100)]) is None
    assert quality.face_count_reason([_face(100), _face(80)]) == "multiple_faces"
    # Someone small in the background is not a second person in view.
    assert quality.face_count_reason([_face(100), _face(30)]) is None


def test_a_good_frame_has_no_reasons():
    assert _assess(_textured(128)) == []


def test_dark_bright_blurred_small_and_turned_frames_say_so():
    assert "too_dark" in _assess(_textured(20))
    assert "too_bright" in _assess(_textured(240))
    assert "blurred" in _assess(np.full((112, 112, 3), 128, dtype=np.uint8))
    small = Pose(yaw=0.0, pitch=0.7, eye_distance=20)
    assert "too_small" in _assess(_textured(128), small)
    turned = Pose(yaw=0.5, pitch=0.7, eye_distance=60)
    assert "off_angle" in _assess(_textured(128), turned)
    assert "off_angle" not in _assess(_textured(128), turned, frontal=False)


def test_a_face_at_the_edge_of_the_picture_is_out_of_frame():
    edge = Face(np.array([0, 156, 168, 324]), 0.9, TEMPLATE * 1.5 + [-60, 156])
    assert "out_of_frame" in _assess(_textured(128), face=edge)
    assert "out_of_frame" not in _assess(_textured(128), face=edge, frontal=False)
