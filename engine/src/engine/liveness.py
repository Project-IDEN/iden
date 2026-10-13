"""The checks that a capture came from a live person, here, now.

Each stops something different. The anti-spoofing models catch prints and
screens. The actions catch a still photograph and a recording made earlier,
since nobody knew which movements would be asked for. The flash catches a
replay held up to the camera, which cannot reflect colours chosen a moment ago.
Consistency catches swapping faces partway through.
"""

from dataclasses import dataclass

import numpy as np

from engine.detect import Face
from engine.manifest import Liveness, Policy
from engine.pose import Pose
from engine.steps import CHANNEL

# Sign of the pose change each action produces, and on which axis.
EXPECTED = {
    "turn_left": ("yaw", 1),
    "turn_right": ("yaw", -1),
    "look_up": ("pitch", -1),
    "look_down": ("pitch", 1),
}


@dataclass(frozen=True)
class Verdict:
    passed: bool
    score: float
    # Flash only: the largest chroma change seen, which must also clear a bar.
    spread: float = 0.0


def anti_spoofing(probabilities: list[float], rules: Policy) -> Verdict:
    if not probabilities:
        return Verdict(False, 0.0)
    live = [p >= rules.live_threshold for p in probabilities]
    return Verdict(
        sum(live) / len(live) >= rules.live_fraction, float(np.mean(probabilities))
    )


def actions(
    baseline: Pose, performed: dict[str, list[Pose]], rules: Liveness
) -> Verdict:
    """Every requested movement reached its threshold in at least one frame."""
    if not performed:
        return Verdict(False, 0.0)

    reached = []
    for action, poses in performed.items():
        axis, sign = EXPECTED[action]
        limit = rules.turn_delta if axis == "yaw" else rules.pitch_delta
        start = getattr(baseline, axis)
        peak = max((sign * (getattr(pose, axis) - start) for pose in poses), default=0)
        reached.append(peak / limit)

    return Verdict(min(reached) >= 1, float(min(reached)))


def face_chroma(image: np.ndarray, face: Face) -> np.ndarray:
    """Mean colour of the middle of the face as proportions summing to one."""
    x1, y1, x2, y2 = face.box
    width, height = x2 - x1, y2 - y1
    top, bottom = int(y1 + height * 0.25), int(y2 - height * 0.25)
    left, right = int(x1 + width * 0.25), int(x2 - width * 0.25)
    region = image[max(top, 0) : max(bottom, 1), max(left, 0) : max(right, 1)]
    mean = region.reshape(-1, 3).mean(axis=0) + 1e-6
    return mean / mean.sum()


def flash(observed: list[tuple[str, np.ndarray]], rules: Liveness) -> Verdict:
    """Whether the face's colour cast followed the colours shown.

    Measured relative to the average over the sequence, so skin tone and room
    lighting cancel out and only the change remains.
    """
    if len(observed) < 2:
        return Verdict(False, 0.0)

    chromas = np.stack([chroma for _, chroma in observed])
    shifts = chromas - chromas.mean(axis=0)
    hits = [
        int(np.argmax(shift)) == CHANNEL[colour]
        for (colour, _), shift in zip(observed, shifts, strict=True)
    ]
    score = sum(hits) / len(hits)
    spread = float(np.abs(shifts).max())
    return Verdict(
        score >= rules.flash_min_score and spread >= rules.flash_min_spread,
        score,
        spread,
    )


def consistency(
    reference: np.ndarray,
    frontal: list[np.ndarray],
    turned: list[np.ndarray],
    rules: Liveness,
) -> Verdict:
    """Every frame shows the same person as the reference embedding."""
    frontal_scores = [float(vector @ reference) for vector in frontal]
    turned_scores = [float(vector @ reference) for vector in turned]
    passed = all(s >= rules.consistency_frontal for s in frontal_scores) and all(
        s >= rules.consistency_turned for s in turned_scores
    )
    return Verdict(passed, min(frontal_scores + turned_scores, default=0.0))
