"""How open the eyes are and how the mouth sits, from the 106 landmarks.

Every measure is a ratio, so it does not depend on how far the person stands
from the camera, and each is only ever compared with the same person's own
value in the frames looking straight ahead: eyes and mouths differ in size, so
an absolute "closed" or "smiling" would be wrong for many people.
"""

from dataclasses import dataclass

import numpy as np

from engine.landmarks import IMAGE_LEFT_EYE, IMAGE_RIGHT_EYE, INNER_LIPS, MOUTH


@dataclass(frozen=True)
class Expression:
    # Height of an eye's outline over its width, averaged over both eyes:
    # about a third open, near zero closed.
    eye_openness: float
    # Corner to corner, in inter-ocular distances.
    mouth_width: float
    # How far the corners sit above the lips' centre, in inter-ocular
    # distances; it rises with a smile.
    mouth_lift: float


def _level(points: np.ndarray, origin: np.ndarray, roll: float) -> np.ndarray:
    """`points` relative to `origin`, rotated so the eye line is horizontal."""
    cos, sin = np.cos(-roll), np.sin(-roll)
    rotation = np.array([[cos, -sin], [sin, cos]])
    return (points - origin) @ rotation.T


def _openness(eye: np.ndarray) -> float:
    width = float(np.ptp(eye[:, 0]))
    return float(np.ptp(eye[:, 1])) / width if width > 0 else 0.0


def measure(points: np.ndarray) -> Expression:
    points = points.astype(np.float64)
    left = points[list(IMAGE_LEFT_EYE)]
    right = points[list(IMAGE_RIGHT_EYE)]
    left_centre, right_centre = left.mean(axis=0), right.mean(axis=0)
    dx, dy = right_centre - left_centre
    distance = float(np.hypot(dx, dy))
    if distance == 0:
        return Expression(0.0, 0.0, 0.0)
    # Undo the head's tilt, so a tilted head does not read as a squint.
    roll = float(np.arctan2(dy, dx))
    origin = (left_centre + right_centre) / 2

    openness = (
        _openness(_level(left, origin, roll)) + _openness(_level(right, origin, roll))
    ) / 2

    mouth = _level(points[list(MOUTH)], origin, roll)
    corners = mouth[[int(np.argmin(mouth[:, 0])), int(np.argmax(mouth[:, 0]))]]
    centre = _level(points[list(INNER_LIPS)], origin, roll).mean(axis=0)
    width = float(corners[1, 0] - corners[0, 0])
    # Picture y grows downwards, so corners above the centre are a positive lift.
    lift = float(centre[1] - corners[:, 1].mean())
    return Expression(openness, width / distance, lift / distance)


def neutral(expressions: list[Expression]) -> Expression:
    """The person's own face at rest: the median of each measure, so one frame
    caught mid-blink does not move it."""
    if not expressions:
        return Expression(0.0, 0.0, 0.0)
    return Expression(
        eye_openness=float(np.median([e.eye_openness for e in expressions])),
        mouth_width=float(np.median([e.mouth_width for e in expressions])),
        mouth_lift=float(np.median([e.mouth_lift for e in expressions])),
    )
