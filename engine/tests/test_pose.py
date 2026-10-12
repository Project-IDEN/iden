import numpy as np
import pytest

from engine.align import TEMPLATE
from engine.pose import estimate


def _rotated(points: np.ndarray, degrees: float) -> np.ndarray:
    angle = np.radians(degrees)
    matrix = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    centre = points.mean(axis=0)
    return (points - centre) @ matrix.T + centre


def test_a_frontal_face_has_no_yaw():
    pose = estimate(TEMPLATE)
    assert abs(pose.yaw) < 0.02
    assert 0.4 < pose.pitch < 0.6


def test_nose_towards_the_right_of_the_picture_is_a_turn_to_their_left():
    turned = TEMPLATE.copy()
    turned[2, 0] += 10
    assert estimate(turned).yaw > 0.2


def test_nose_closer_to_the_eyes_is_looking_up():
    up = TEMPLATE.copy()
    up[2, 1] -= 6
    assert estimate(up).pitch < estimate(TEMPLATE).pitch - 0.1


@pytest.mark.parametrize("degrees", [-25, 15, 30])
def test_tilting_the_head_is_not_turning_it(degrees):
    pose = estimate(_rotated(TEMPLATE, degrees))
    assert abs(pose.yaw) < 0.02
    assert pose.pitch == pytest.approx(estimate(TEMPLATE).pitch, abs=0.01)
