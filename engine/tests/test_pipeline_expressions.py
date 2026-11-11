"""Blink and smile through the whole pipeline, against the real models.

A still photograph cannot blink or smile on cue, so where a test needs a live
blink, the eyes and mouth the 106-point model reads are replaced
(`pipeline._measure`) and everything else — detection, embeddings,
anti-spoofing, consistency — runs for real on the portrait.
"""

import numpy as np
import pytest

from engine import expression, pipeline
from engine.expression import Expression
from tests.conftest import needs_models

BLINK_SMILE = ["center"] * 3 + ["blink"] * 3 + ["smile"] * 3
OPEN = Expression(eye_openness=0.35, mouth_width=0.85, mouth_lift=0.0)
SHUT = Expression(eye_openness=0.05, mouth_width=0.85, mouth_lift=0.0)
SMILING = Expression(eye_openness=0.33, mouth_width=1.0, mouth_lift=0.04)


def read_as(monkeypatch, per_frame: list[Expression]):
    """The 106-point model reads `per_frame[i]` in the i-th frame with a face."""

    def measure(models, seen):
        for (_, s), shown in zip(seen, per_frame, strict=True):
            s.expression = shown

    monkeypatch.setattr(pipeline, "_measure", measure)


def spy(monkeypatch, name: str) -> list[int]:
    """Count the frames each call of `pipeline.<name>` was given."""
    calls: list[int] = []
    real = getattr(pipeline, name)

    def wrapper(session, frames):
        calls.append(len(frames))
        return real(session, frames)

    monkeypatch.setattr(pipeline, name, wrapper)
    return calls


@needs_models
def test_the_106_points_land_on_the_eyes_and_mouth(models, face_image):
    """On the portrait: eyes open and level, a mouth about an eye-distance wide."""
    face = pipeline.inspect(models, "center", face_image).seen
    assert face is not None
    (points,) = pipeline.landmarks(models.landmarker, [(face_image, face.face.box)])
    measured = expression.measure(points)

    assert points.shape == (106, 2)
    assert 0.15 < measured.eye_openness < 0.6
    assert 0.6 < measured.mouth_width < 1.4


@needs_models
def test_a_photograph_cannot_blink_or_smile(models, face_image):
    result = pipeline.enroll(models, [face_image] * 9, BLINK_SMILE)

    assert result.usable
    assert result.checks is not None
    assert not result.checks.actions
    assert not result.live
    assert result.embeddings == []


@needs_models
def test_a_blink_and_a_smile_pass_and_closed_eyes_are_never_judged(
    models, face_image, monkeypatch
):
    """The second frame looking ahead caught a blink: anti-spoofing sees the
    other two only, and no template comes from it."""
    read_as(
        monkeypatch,
        [OPEN, SHUT, OPEN] + [OPEN, SHUT, OPEN] + [OPEN, SMILING, SMILING],
    )
    judged = spy(monkeypatch, "live_probability")

    result = pipeline.enroll(models, [face_image] * 9, BLINK_SMILE)

    assert result.checks is not None
    assert result.checks.actions, result.checks
    assert result.live, result.checks
    assert judged == [2]
    assert result.sources and 1 not in result.sources
    assert set(result.sources) <= {0, 2}


@needs_models
def test_a_blink_that_never_reopens_fails_the_actions(models, face_image, monkeypatch):
    read_as(
        monkeypatch,
        [OPEN] * 3 + [OPEN, SHUT, SHUT] + [OPEN, SMILING, SMILING],
    )

    result = pipeline.enroll(models, [face_image] * 9, BLINK_SMILE)

    assert result.checks is not None
    assert not result.checks.actions
    assert not result.live


@needs_models
def test_every_frame_is_still_checked_for_the_same_face(
    models, face_image, monkeypatch
):
    """Consistency covers the blink and smile frames too: someone else in the
    peak-smile frame fails it, however well the blink and smile went."""
    read_as(monkeypatch, [OPEN] * 3 + [OPEN, SHUT, OPEN] + [OPEN, SMILING, SMILING])
    frames = [face_image] * 9
    assert pipeline.enroll(models, frames, BLINK_SMILE).live

    stranger = np.random.default_rng(7).standard_normal(512).astype(np.float32)
    real_embed = pipeline.embed

    def someone_else_smiles(*args):
        vectors = np.array(real_embed(*args))
        vectors[7] = stranger / np.linalg.norm(stranger)
        return vectors

    monkeypatch.setattr(pipeline, "embed", someone_else_smiles)
    result = pipeline.enroll(models, frames, BLINK_SMILE)

    assert result.checks is not None
    assert result.checks.actions
    assert not result.checks.consistent
    assert not result.live


@needs_models
def test_sign_in_reads_no_106_points(models, face_image, monkeypatch):
    """Sign-in asks for three frames looking ahead: the 106-point model does not
    run, and anti-spoofing judges all three, as it always has."""
    read = spy(monkeypatch, "landmarks")
    judged = spy(monkeypatch, "live_probability")
    analysis = pipeline.analyse(models, [face_image] * 3, ["center"] * 3)
    assert analysis.reference is not None

    result = pipeline.verify(
        models, [face_image] * 3, ["center"] * 3, [analysis.reference.tolist()]
    )

    assert result.matched
    assert read == []
    assert judged == [3, 3]


@needs_models
def test_enrolment_with_head_movements_reads_the_eyes_too(
    models, face_image, monkeypatch
):
    read = spy(monkeypatch, "landmarks")
    steps = ["center"] * 3 + ["turn_left"] * 3 + ["look_up"] * 3

    result = pipeline.enroll(models, [face_image] * 9, steps)

    assert read == [9]
    assert result.checks is not None and not result.checks.actions


@pytest.mark.parametrize("step", ["blink", "smile"])
@needs_models
def test_a_blink_or_smile_step_without_a_face_asks_for_one(models, face_image, step):
    blank = np.full_like(face_image, 90)
    steps = ["center"] * 3 + [step] * 3 + ["turn_left"] * 3
    frames = [face_image] * 3 + [blank] * 3 + [face_image] * 3

    result = pipeline.enroll(models, frames, steps)

    assert not result.usable
    assert result.reasons == ["no_face"]
