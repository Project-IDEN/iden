"""The checks that a capture came from a live person, here, now.

Each stops something different. The anti-spoofing model catches prints and
screens. The actions catch a still photograph and a recording made earlier,
since nobody knew which movements would be asked for. Consistency catches
swapping faces partway through.
"""

from dataclasses import dataclass

import numpy as np

from engine.manifest import Liveness, Policy
from engine.pose import Pose

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
