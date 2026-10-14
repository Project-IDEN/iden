"""Against the real models, on a public-domain portrait."""

import cv2
import numpy as np

from engine import pipeline
from engine.detect import detect
from tests.conftest import needs_models

STEPS = ["center"] * 3 + ["turn_left"] * 3 + ["look_up"] * 3


@needs_models
def test_a_photograph_is_usable_but_not_live(models, face_image):
    result = pipeline.enroll(models, [face_image] * len(STEPS), STEPS)
    assert result.usable
    assert result.checks is not None
    assert not result.checks.actions
    assert not result.live
    assert result.embeddings == []


@needs_models
def test_a_movement_frame_without_a_face_is_not_fatal(models, face_image):
    blank = np.full_like(face_image, 90)
    frames = [face_image] * len(STEPS)
    frames[3] = blank
    assert pipeline.enroll(models, frames, STEPS).usable

    frames[4] = frames[5] = blank
    result = pipeline.enroll(models, frames, STEPS)
    assert not result.usable
    assert result.reasons == ["no_face"]


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
