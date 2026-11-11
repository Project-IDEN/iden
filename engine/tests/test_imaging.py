import cv2
import numpy as np
import pytest

from engine import imaging
from engine.imaging import InvalidImage, declared_size, decode

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


@pytest.mark.parametrize("progressive", [0, 1])
def test_the_declared_size_is_read_from_the_header(progressive):
    _, encoded = cv2.imencode(
        ".jpg",
        np.zeros((480, 640, 3), np.uint8),
        [cv2.IMWRITE_JPEG_PROGRESSIVE, progressive],
    )
    assert declared_size(encoded.tobytes()) == (480, 640)


def test_a_bomb_is_refused_before_anything_is_decoded(monkeypatch):
    """A few kilobytes declaring 65500×65500. Any decode — even the reduced
    read — allocates for the declared canvas first."""
    data = bytearray(_encode(".jpg", 64, 64))
    frame = data.index(b"\xff\xc0")
    data[frame + 5 : frame + 9] = (65500).to_bytes(2) * 2

    def decoded(*_):
        raise AssertionError("decoded before the size was checked")

    monkeypatch.setattr(imaging.cv2, "imdecode", decoded)
    with pytest.raises(InvalidImage, match="larger"):
        decode(bytes(data), MAX_PIXELS)


def test_a_jpeg_with_no_frame_header_is_refused():
    with pytest.raises(InvalidImage):
        decode(b"\xff\xd8\xff\xe0\x00\x10" + b"\x00" * 14, MAX_PIXELS)
