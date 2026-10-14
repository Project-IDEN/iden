import cv2
import numpy as np
import pytest

from engine.imaging import InvalidImage, decode

MAX_PIXELS = 4_000_000


def _encode(extension: str, width: int, height: int) -> bytes:
    _, encoded = cv2.imencode(extension, np.zeros((height, width, 3), np.uint8))
    return encoded.tobytes()


def test_a_jpeg_is_decoded():
    assert decode(_encode(".jpg", 640, 480), MAX_PIXELS).shape == (480, 640, 3)


@pytest.mark.parametrize("extension", [".png", ".bmp", ".tiff", ".webp"])
def test_anything_but_jpeg_is_refused(extension):
    with pytest.raises(InvalidImage):
        decode(_encode(extension, 64, 64), MAX_PIXELS)


def test_a_jpeg_too_large_is_refused():
    with pytest.raises(InvalidImage):
        decode(_encode(".jpg", 4000, 3000), MAX_PIXELS)
