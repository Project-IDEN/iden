"""Every action on a real capture of a live person.

Skipped until a consenting team member has run `scripts.capture_actions`,
which writes `<step>_<n>.jpg` (three frames each for `center` and the six
actions) to tests/data/actions/. The folder is git-ignored: the photos stay on
that person's machine.
"""

from itertools import combinations
from pathlib import Path

import cv2
import numpy as np
import pytest

from engine import pipeline
from tests.conftest import ROOT, needs_models

ACTIONS_DIR = ROOT / "tests" / "data" / "actions"
ACTIONS = ("turn_left", "turn_right", "look_up", "look_down", "blink", "smile")
CENTRE = ["center"] * 3


def _path(step: str, n: int) -> Path:
    return ACTIONS_DIR / f"{step}_{n}.jpg"


def _captured(*steps: str) -> bool:
    return all(_path(step, n).is_file() for step in steps for n in range(3))


needs_capture = pytest.mark.skipif(
    not _captured("center", *ACTIONS),
    reason=f"no capture in {ACTIONS_DIR}; run `uv run python -m scripts.capture_actions`",
)


def frames(step: str, order: tuple[int, ...] = (0, 1, 2)) -> list[np.ndarray]:
    images = []
    for n in order:
        image = cv2.imread(str(_path(step, n)))
        assert image is not None, _path(step, n)
        images.append(image)
    return images


def enrol(models, *parts: tuple[str, list[np.ndarray]]):
    steps = CENTRE + [step for step, shown in parts for _ in shown]
    images = frames("center") + [image for _, shown in parts for image in shown]
    return pipeline.enroll(models, images, steps)


@needs_models
@needs_capture
@pytest.mark.parametrize("action", ACTIONS)
def test_each_action_is_seen(models, action):
    result = enrol(models, (action, frames(action)))

    assert result.checks is not None, result.reasons
    assert result.checks.actions, result.checks
    assert result.checks.consistent, result.checks


@needs_models
@needs_capture
@pytest.mark.parametrize("pair", list(combinations(ACTIONS, 2)))
def test_any_two_actions_enrol(models, pair):
    """Every challenge the provider can draw, on the same capture."""
    first, second = pair
    result = enrol(models, (first, frames(first)), (second, frames(second)))

    assert result.live, result.checks
    assert 0 < len(result.embeddings) <= 3
    # Templates come from the frames looking ahead only.
    assert set(result.sources) <= {0, 1, 2}


@needs_models
@needs_capture
def test_a_blink_out_of_order_is_not_a_blink(models):
    """Closed first, then open twice: nothing shows the eyes were open before."""
    result = enrol(models, ("blink", frames("blink", (1, 0, 2))))

    assert result.checks is not None
    assert not result.checks.actions


@needs_models
@needs_capture
def test_open_eyes_alone_are_not_a_blink(models):
    result = enrol(models, ("blink", frames("center")))

    assert result.checks is not None
    assert not result.checks.actions


@needs_models
@needs_capture
def test_a_straight_face_is_not_a_smile(models):
    result = enrol(models, ("smile", frames("center")))

    assert result.checks is not None
    assert not result.checks.actions


@needs_models
@needs_capture
def test_a_smile_is_not_a_blink_nor_a_blink_a_smile(models):
    assert not enrol(models, ("blink", frames("smile"))).live
    assert not enrol(models, ("smile", frames("blink"))).live
