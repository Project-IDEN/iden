from pathlib import Path

import cv2
import numpy as np
import pytest

from engine import manifest, runtime

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = manifest.load(ROOT / "models.toml")


def _models_present() -> bool:
    return all(
        (ROOT / "models" / model.file).is_file() for model in MANIFEST.model_files()
    )


needs_models = pytest.mark.skipif(
    not _models_present(),
    reason="model files absent; run `uv run python -m scripts.fetch_models`",
)


@pytest.fixture(scope="session")
def models() -> runtime.Models:
    return runtime.load(MANIFEST, ROOT / "models", "cpu")


@pytest.fixture(scope="session")
def face_image() -> np.ndarray:
    image = cv2.imread(str(ROOT / "tests" / "data" / "astronaut.jpg"))
    assert image is not None
    return image
