import cv2
import numpy as np


class InvalidImage(ValueError):
    pass


def decode(data: bytes, max_pixels: int) -> np.ndarray:
    """A BGR image from JPEG or PNG bytes, refusing anything that is not one."""
    buffer = np.frombuffer(data, dtype=np.uint8)
    # Read the header before the pixels: a few kilobytes can declare a canvas
    # that costs gigabytes to decode.
    image = cv2.imdecode(buffer, cv2.IMREAD_REDUCED_COLOR_8)
    if image is None:
        raise InvalidImage("A frame is not an image the engine can read.")
    if image.shape[0] * image.shape[1] * 64 > max_pixels:
        raise InvalidImage("A frame is larger than the engine accepts.")

    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidImage("A frame is not an image the engine can read.")
    return image
