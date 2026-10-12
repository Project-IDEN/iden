"""Whether a frame is good enough to judge, and if not, what to tell the person."""

from typing import Literal

import cv2
import numpy as np

from engine.detect import Face
from engine.manifest import Quality
from engine.pose import Pose

Reason = Literal[
    "no_face",
    "multiple_faces",
    "too_small",
    "blurred",
    "too_dark",
    "too_bright",
    "off_angle",
]

# A second face this large next to the main one is a second person in view, not
# a poster on the far wall.
SECOND_FACE_RATIO = 0.25


def face_count_reason(faces: list[Face]) -> Reason | None:
    if not faces:
        return "no_face"
    if len(faces) > 1 and faces[1].area >= faces[0].area * SECOND_FACE_RATIO:
        return "multiple_faces"
    return None


def sharpness(aligned: np.ndarray) -> float:
    gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def brightness(aligned: np.ndarray) -> float:
    # The centre of the crop, which is face; the corners are background.
    centre = aligned[24:96, 24:88]
    return float(cv2.cvtColor(centre, cv2.COLOR_BGR2GRAY).mean())


def assess(
    aligned: np.ndarray, pose: Pose, rules: Quality, *, frontal: bool
) -> list[Reason]:
    """Every problem with this face, most actionable first."""
    reasons: list[Reason] = []
    if pose.eye_distance < rules.min_eye_distance:
        reasons.append("too_small")
    level = brightness(aligned)
    if level < rules.min_brightness:
        reasons.append("too_dark")
    elif level > rules.max_brightness:
        reasons.append("too_bright")
    if sharpness(aligned) < rules.min_sharpness:
        reasons.append("blurred")
    if frontal and abs(pose.yaw) > rules.max_frontal_yaw:
        reasons.append("off_angle")
    return reasons


def score(aligned: np.ndarray, pose: Pose) -> float:
    """A single number to rank usable frames by: sharp, large and frontal."""
    return float(
        np.log1p(sharpness(aligned)) * min(pose.eye_distance / 80, 1.5) - abs(pose.yaw)
    )
