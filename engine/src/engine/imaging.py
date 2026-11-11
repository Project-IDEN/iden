import cv2
import numpy as np

# Every camera IDEN drives sends JPEG. OpenCV would also read PNG, TIFF, WebP and
# more, and a 400 KB PNG can inflate a canvas of hundreds of megabytes.
JPEG_SIGNATURE = b"\xff\xd8\xff"

# Start-of-frame markers, which carry the image's dimensions. C4, C8 and CC
# share the range but are not frames.
_FRAME_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
# Markers that stand alone, with no length after them.
_STANDALONE_MARKERS = frozenset(range(0xD0, 0xDA)) | {0x01}


class InvalidImage(ValueError):
    pass


def declared_size(data: bytes) -> tuple[int, int] | None:
    """The (height, width) a JPEG's frame header declares, without decoding.

    Any decode allocates for the declared canvas first — even OpenCV's reduced
    read, at an eighth of each side — so a few kilobytes claiming 65500×65500
    cost hundreds of megabytes before a size check could run.
    """
    position = 2
    while position + 9 <= len(data):
        if data[position] != 0xFF:
            return None
        marker = data[position + 1]
        if marker == 0xFF:
            position += 1
            continue
        if marker in _STANDALONE_MARKERS:
            position += 2
            continue
        if marker in _FRAME_MARKERS:
            height = int.from_bytes(data[position + 5 : position + 7])
            width = int.from_bytes(data[position + 7 : position + 9])
            return height, width
        position += 2 + int.from_bytes(data[position + 2 : position + 4])
    return None


def decode(data: bytes, max_pixels: int) -> np.ndarray:
    """A BGR image from JPEG bytes, refusing anything that is not one."""
    if not data.startswith(JPEG_SIGNATURE):
        raise InvalidImage("A frame is not a JPEG image.")

    size = declared_size(data)
    if size is None:
        raise InvalidImage("A frame is not an image the engine can read.")
    if size[0] * size[1] > max_pixels:
        raise InvalidImage("A frame is larger than the engine accepts.")

    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidImage("A frame is not an image the engine can read.")
    return image
