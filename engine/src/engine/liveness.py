"""The checks that a capture came from a live person, here, now.

Each stops something different. The anti-spoofing model catches prints and
screens. The actions catch a still photograph and a recording made earlier,
since nobody knew which movements would be asked for; the provider asks for
them at enrolment only, so a sign-in has none to check. Consistency catches
swapping faces partway through.

A blink and a smile are actions too, judged on the 106-point landmarks
(`engine.expression`) against the person's own face in the frames looking
straight ahead.
"""

from dataclasses import dataclass

import numpy as np

from engine.expression import Expression
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
    """Every requested movement reached its threshold in at least one frame.

    Passes when none was requested. `performed` holds every requested movement,
    since a capture missing one is not judged at all.
    """
    if not performed:
        return Verdict(True, 0.0)

    reached = []
    for action, poses in performed.items():
        axis, sign = EXPECTED[action]
        limit = rules.turn_delta if axis == "yaw" else rules.pitch_delta
        start = getattr(baseline, axis)
        peak = max((sign * (getattr(pose, axis) - start) for pose in poses), default=0)
        reached.append(peak / limit)

    return Verdict(min(reached) >= 1, float(min(reached)))


def eyes_open(openness: float, baseline: float, rules: Policy) -> bool:
    """Whether these eyes are open, against the person's own open-eye openness."""
    return baseline > 0 and openness >= rules.blink_open_ratio * baseline


def blink(baseline: float, openness: list[float], rules: Policy) -> Verdict:
    """Open, then clearly closed, then open again, in the order of the frames.

    `baseline` is the person's own openness looking straight ahead and
    `openness` the blink step's frames, in capture order. The score is how far
    the weaker of the two halves went, where 1 passes: the closing (the most
    closed frame against `blink_closed_ratio`) and the opening on either side
    of it (against `blink_open_ratio`). A dip that never reopens, or one in the
    first frame, scores 0 for the opening.
    """
    if baseline <= 0 or not openness:
        return Verdict(False, 0.0)
    ratios = [value / baseline for value in openness]
    dip = int(np.argmin(ratios))
    closed = (1 - ratios[dip]) / (1 - rules.blink_closed_ratio)
    reopened = (
        min(max(ratios[:dip], default=0.0), max(ratios[dip + 1 :], default=0.0))
        / rules.blink_open_ratio
    )
    reached = min(closed, reopened)
    return Verdict(reached >= 1, float(reached))


def smile(neutral: Expression, performed: list[Expression], rules: Policy) -> Verdict:
    """The mouth widened and its corners rose, together, by `smile_gain` beyond
    the person's neutral mouth, in at least one of the smile step's frames."""
    if not performed:
        return Verdict(False, 0.0)
    gain = max(
        (e.mouth_width - neutral.mouth_width) + (e.mouth_lift - neutral.mouth_lift)
        for e in performed
    )
    reached = gain / rules.smile_gain
    return Verdict(reached >= 1, float(reached))


def combined(verdicts: list[Verdict]) -> Verdict:
    """Every action passed; the score is the weakest one's. Passes when none
    was asked for."""
    if not verdicts:
        return Verdict(True, 0.0)
    return Verdict(all(v.passed for v in verdicts), min(v.score for v in verdicts))


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
