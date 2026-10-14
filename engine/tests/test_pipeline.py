"""Against the real models, on a public-domain portrait."""

import cv2
import numpy as np

from engine import pipeline
from engine.detect import detect
from tests.conftest import needs_models

STEPS = (
    ["center"] * 3
    + ["turn_left"] * 3
    + ["look_up"] * 3
    + ["flash:red", "flash:green", "flash:blue", "flash:red"]
)


def _tinted(image: np.ndarray, colour: str) -> np.ndarray:
    channel = {"blue": 0, "green": 1, "red": 2}[colour]
    tinted = image.astype(np.float32)
    tinted[:, :, channel] *= 1.12
    return np.clip(tinted, 0, 255).astype(np.uint8)


@needs_models
def test_a_photograph_is_usable_but_not_live(models, face_image):
    result = pipeline.enroll(models, [face_image] * len(STEPS), STEPS)
    assert result.usable
    assert result.checks is not None
    assert not result.checks.actions
    assert not result.live
    assert result.embeddings == []


@needs_models
def test_flash_frames_that_reflect_the_colours_pass_the_flash_check(models, face_image):
    frames = [
        _tinted(face_image, step.split(":")[1])
        if step.startswith("flash")
        else face_image
        for step in STEPS
    ]
    result = pipeline.enroll(models, frames, STEPS)
    assert result.checks is not None and result.checks.flash


@needs_models
def test_the_same_face_matches_and_another_does_not(models, face_image):
    analysis = pipeline.analyse(models, [face_image] * 3, ["center"] * 3)
    assert analysis.reference is not None
    template = analysis.reference.tolist()

    altered = cv2.convertScaleAbs(cv2.flip(face_image, 1), alpha=0.9, beta=10)
    same = pipeline.verify(models, [altered] * 3, ["center"] * 3, [template])
    assert same.matched and same.similarity > 0.8

    stranger = np.random.default_rng(1).standard_normal(512)
    other = pipeline.verify(models, [altered] * 3, ["center"] * 3, [stranger.tolist()])
    assert not other.matched


@needs_models
def test_an_empty_frame_asks_for_a_face(models):
    blank = np.full((480, 640, 3), 90, dtype=np.uint8)
    result = pipeline.enroll(models, [blank] * 3, ["center"] * 3)
    assert not result.usable
    assert result.reasons == ["no_face"]


@needs_models
def test_stored_photos_can_be_embedded_again(models, face_image):
    blank = np.full((480, 640, 3), 90, dtype=np.uint8)
    result = pipeline.embed_stills(models, [face_image, blank])
    first, second = result.embeddings
    assert first is not None and len(first) == 512
    assert second is None


@needs_models
def test_a_face_that_fills_the_picture_is_found(models, face_image):
    faces = detect(models.detector, face_image, [640], 0.5)
    x1, y1, x2, y2 = faces[0].box.astype(int)
    close_up = cv2.resize(face_image[y1:y2, x1:x2], (640, 640))
    found = detect(models.detector, close_up, models.manifest.detector.input_sizes, 0.5)
    assert len(found) == 1
