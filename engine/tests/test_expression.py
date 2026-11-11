"""Blink and smile, on synthetic 106-point faces: no model, no photo.

`face()` draws the only points the measures read — each eye's outline, the
mouth and the lips' inner outline — at sizes a test chooses, so a test can say
"eyes a fifth as open as at rest" and know exactly what the engine sees.
"""

import math

import numpy as np
import pytest

from engine import expression, liveness, pipeline
from engine.expression import Expression
from engine.landmarks import IMAGE_LEFT_EYE, IMAGE_RIGHT_EYE, INNER_LIPS, MOUTH
from tests.conftest import MANIFEST

RULES = MANIFEST.policy
IOD = 64.0
# Nine points round each eye, the four extremes among them, so an eye's
# outline is exactly `openness` times as high as it is wide.
EYE_ANGLES = [k * math.pi / 4 for k in range(8)] + [math.pi / 8]


def face(
    openness: float = 0.35,
    eye_width: float = 28.0,
    mouth_width: float = 0.85,
    lift: float = 0.0,
    roll: float = 0.0,
) -> np.ndarray:
    """A face's 106 points. `mouth_width` and `lift` are in inter-ocular
    distances; `lift` raises the mouth's corners above its centre."""
    points = np.zeros((106, 2))
    for group, cx in ((IMAGE_LEFT_EYE, -IOD / 2), (IMAGE_RIGHT_EYE, IOD / 2)):
        for index, angle in zip(group, EYE_ANGLES, strict=True):
            points[index] = (
                cx + eye_width / 2 * math.cos(angle),
                openness * eye_width / 2 * math.sin(angle),
            )

    half = mouth_width * IOD / 2
    mouth_y = 0.9 * IOD
    outer = [i for i in MOUTH if i not in INNER_LIPS]
    left_corner, right_corner, *lips = outer
    points[left_corner] = (-half, mouth_y - lift * IOD)
    points[right_corner] = (half, mouth_y - lift * IOD)
    for k, index in enumerate(lips):
        x = -0.7 * half + 1.4 * half * (k // 2) / max(len(lips) // 2 - 1, 1)
        points[index] = (x, mouth_y + (6 if k % 2 else -6))
    for k, index in enumerate(INNER_LIPS):
        x = -0.6 * half + 1.2 * half * (k // 2) / max(len(INNER_LIPS) // 2 - 1, 1)
        points[index] = (x, mouth_y + (2 if k % 2 else -2))

    # Somewhere in a 640×480 picture, tilted by `roll`.
    cos, sin = math.cos(roll), math.sin(roll)
    return points @ np.array([[cos, sin], [-sin, cos]]) + (320, 240)


def eyes(*openness: float, eye_width: float = 28.0) -> list[float]:
    return [
        expression.measure(face(o, eye_width=eye_width)).eye_openness for o in openness
    ]


class TestMeasure:
    def test_the_measures_read_back_what_was_drawn(self):
        measured = expression.measure(face(0.3, mouth_width=0.9, lift=0.05))
        assert measured.eye_openness == pytest.approx(0.3, rel=0.01)
        assert measured.mouth_width == pytest.approx(0.9, rel=0.05)
        assert measured.mouth_lift == pytest.approx(0.05, abs=0.01)

    def test_a_tilted_head_reads_the_same(self):
        level = expression.measure(face(0.3, lift=0.04))
        tilted = expression.measure(face(0.3, lift=0.04, roll=0.35))
        assert tilted.eye_openness == pytest.approx(level.eye_openness, rel=0.01)
        assert tilted.mouth_width == pytest.approx(level.mouth_width, rel=0.01)
        assert tilted.mouth_lift == pytest.approx(level.mouth_lift, abs=0.005)

    def test_the_neutral_face_is_the_median_so_one_blink_does_not_move_it(self):
        at_rest = [expression.measure(face(o)) for o in (0.35, 0.05, 0.34)]
        assert expression.neutral(at_rest).eye_openness == pytest.approx(0.34, rel=0.02)


class TestBlink:
    def test_open_then_closed_then_open_passes(self):
        verdict = liveness.blink(0.35, eyes(0.34, 0.06, 0.33), RULES)
        assert verdict.passed
        assert verdict.score >= 1

    def test_no_dip_fails(self):
        verdict = liveness.blink(0.35, eyes(0.35, 0.33, 0.34), RULES)
        assert not verdict.passed

    def test_a_dip_that_never_reopens_fails(self):
        assert not liveness.blink(0.35, eyes(0.34, 0.06, 0.05), RULES).passed
        assert not liveness.blink(0.35, eyes(0.34, 0.33, 0.05), RULES).passed

    def test_a_dip_in_the_first_frame_fails(self):
        """Eyes already shut when the step began: nothing shows they were open
        before, so the frames could be a photo of closed eyes then open ones."""
        assert not liveness.blink(0.35, eyes(0.05, 0.34, 0.35), RULES).passed

    def test_the_order_of_the_frames_counts(self):
        assert liveness.blink(0.35, eyes(0.34, 0.06, 0.34), RULES).passed
        assert not liveness.blink(0.35, eyes(0.06, 0.34, 0.34), RULES).passed

    def test_half_closed_is_not_a_blink(self):
        assert not liveness.blink(0.35, eyes(0.35, 0.25, 0.35), RULES).passed

    def test_small_eyes_are_judged_against_their_own_baseline(self):
        """0.18 is a squint for most people, but open for these eyes; closing
        them to 0.05 is a blink."""
        small = 0.18
        assert liveness.blink(small, eyes(0.18, 0.05, 0.17), RULES).passed
        assert liveness.eyes_open(eyes(0.17)[0], small, RULES)

    def test_large_eyes_are_judged_against_their_own_baseline(self):
        """For eyes open at 0.45, 0.3 is only narrowed, and 0.18 is closed."""
        large = 0.45
        assert not liveness.blink(large, eyes(0.45, 0.3, 0.45), RULES).passed
        assert liveness.blink(large, eyes(0.45, 0.18, 0.44), RULES).passed

    def test_the_same_eyes_score_the_same_whatever_their_size(self):
        small = liveness.blink(0.35, eyes(0.34, 0.06, 0.33, eye_width=18), RULES)
        large = liveness.blink(0.35, eyes(0.34, 0.06, 0.33, eye_width=40), RULES)
        assert small.score == pytest.approx(large.score, rel=0.01)

    def test_nothing_to_judge_fails(self):
        assert not liveness.blink(0.35, [], RULES).passed
        assert not liveness.blink(0.0, eyes(0.34, 0.06, 0.33), RULES).passed


def mouth(width: float, lift: float = 0.0) -> Expression:
    return expression.measure(face(mouth_width=width, lift=lift))


class TestSmile:
    def test_a_smile_passes(self):
        neutral = mouth(0.85)
        verdict = liveness.smile(neutral, [neutral, mouth(0.97, 0.03)], RULES)
        assert verdict.passed

    def test_a_neutral_mouth_only_fails(self):
        neutral = mouth(0.85)
        verdict = liveness.smile(neutral, [mouth(0.85)] * 3, RULES)
        assert not verdict.passed
        assert verdict.score == pytest.approx(0, abs=0.05)

    def test_a_faint_smile_is_not_enough(self):
        neutral = mouth(0.85)
        assert not liveness.smile(neutral, [mouth(0.88, 0.01)], RULES).passed

    def test_raised_corners_count_as_well_as_width(self):
        neutral = mouth(0.85)
        assert liveness.smile(neutral, [mouth(0.85, 0.12)], RULES).passed

    def test_a_wide_mouth_is_judged_against_its_own_neutral(self):
        """A mouth 1.0 wide is a broad smile on a narrow mouth, but this
        person's mouth is that wide at rest."""
        assert liveness.smile(mouth(0.85), [mouth(1.0)], RULES).passed
        assert not liveness.smile(mouth(1.0), [mouth(1.0)], RULES).passed
        assert liveness.smile(mouth(1.0), [mouth(1.13, 0.02)], RULES).passed

    def test_nothing_to_judge_fails(self):
        assert not liveness.smile(mouth(0.85), [], RULES).passed


class TestCombined:
    def test_every_action_must_pass_and_the_weakest_scores(self):
        good, bad = liveness.Verdict(True, 1.4), liveness.Verdict(False, 0.3)
        assert liveness.combined([good, good]).passed
        verdict = liveness.combined([good, bad])
        assert not verdict.passed
        assert verdict.score == 0.3

    def test_nothing_asked_for_passes(self):
        assert liveness.combined([]) == liveness.Verdict(True, 0.0)


class TestOpenEyedFrames:
    def test_anti_spoofing_frames_leave_out_closed_eyes(self):
        """Only the frontal frames whose eyes are open are judged by
        anti-spoofing and kept as templates."""
        centre = []
        for openness in (0.35, 0.05, 0.34):
            seen = pipeline.Seen(
                face=None,  # pyright: ignore[reportArgumentType]
                pose=None,  # pyright: ignore[reportArgumentType]
                aligned=np.zeros(0),
                expression=expression.measure(face(openness)),
            )
            centre.append((pipeline.Frame("center", np.zeros(0), seen, []), seen))
        neutral = expression.neutral([s.expression for _, s in centre if s.expression])

        kept = pipeline.open_eyed(centre, neutral, RULES)

        assert [s.expression.eye_openness for _, s in kept if s.expression] == [
            pytest.approx(0.35, rel=0.01),
            pytest.approx(0.34, rel=0.01),
        ]
