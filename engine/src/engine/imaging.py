import cv2
import numpy as np

# Every camera IDEN drives sends JPEG. OpenCV would also read PNG, TIFF, WebP and
# more, and its reduced read below only saves memory for JPEG: a 400 KB PNG still
# inflates its whole canvas first, which measured over 400 MB.
JPEG_SIGNATURE = b"\xff\xd8\xff"


class InvalidImage(ValueError):
    pass


def decode(data: bytes, max_pixels: int) -> np.ndarray:
    """A BGR image from JPEG bytes, refusing anything that is not one."""
    if not data.startswith(JPEG_SIGNATURE):
        raise InvalidImage("A frame is not a JPEG image.")

    buffer = np.frombuffer(data, dtype=np.uint8)
    # Read at an eighth of the size before the pixels: a few kilobytes can
    # declare a canvas that costs gigabytes to decode.
    image = cv2.imdecode(buffer, cv2.IMREAD_REDUCED_COLOR_8)
    if image is None:
        raise InvalidImage("A frame is not an image the engine can read.")
    if image.shape[0] * image.shape[1] * 64 > max_pixels:
        raise InvalidImage("A frame is larger than the engine accepts.")

    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidImage("A frame is not an image the engine can read.")
    return image
