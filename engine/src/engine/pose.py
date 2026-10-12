"""Head pose from the five landmarks — proxies, not angles.

Good enough to tell "turned left" from "facing the camera", which is all the
challenge needs, and free: no extra model.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Pose:
    # Nose offset from the eyes' midpoint over the distance between the eyes.
    # Positive when the person turns to *their* left: facing the camera, their
    # left is the right of an unmirrored picture.
    yaw: float
    # Where the nose sits between the eye line (0) and the mouth line (1).
    # Smaller when looking up, larger when looking down.
    pitch: float
    eye_distance: float


def estimate(landmarks: np.ndarray) -> Pose:
    left_eye, right_eye, nose, mouth_left, mouth_right = landmarks.astype(np.float64)
    eyes = (left_eye + right_eye) / 2

    # Undo the head's tilt first, so a tilted head does not read as turned.
    dx, dy = right_eye - left_eye
    roll = np.arctan2(dy, dx)
    rotation = np.array(
        [[np.cos(-roll), -np.sin(-roll)], [np.sin(-roll), np.cos(-roll)]]
    )
    nose_r = rotation @ (nose - eyes)
    mouth_r = rotation @ ((mouth_left + mouth_right) / 2 - eyes)

    eye_distance = float(np.hypot(dx, dy))
    mouth_drop = mouth_r[1] if mouth_r[1] > 1e-6 else 1e-6
    return Pose(
        yaw=float(nose_r[0] / eye_distance) if eye_distance else 0.0,
        pitch=float(nose_r[1] / mouth_drop),
        eye_distance=eye_distance,
    )
