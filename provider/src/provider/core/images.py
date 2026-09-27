"""Turning an uploaded file into an avatar.

Nothing a browser hands over is stored as it arrived. Decoding and re-encoding
is what proves the bytes are actually an image rather than something wearing an
image's name, and it discards the metadata a phone camera buries in a JPEG —
GPS coordinates included.
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from provider.core.errors import ValidationError

AVATAR_SIZE = 512
AVATAR_CONTENT_TYPE = "image/webp"

# A ceiling on decoded pixels, not on file size. A few kilobytes of PNG can
# declare a 30,000 x 30,000 canvas that costs gigabytes to decompress, and the
# upload size limit does not see it coming.
MAX_PIXELS = 40_000_000


class InvalidImage(ValidationError):
    code = "invalid_image"
    message = "That file is not an image IDEN can read."


def to_avatar(data: bytes) -> bytes:
    """A square 512px WebP, however the original arrived."""
    try:
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > MAX_PIXELS:
            raise InvalidImage("That image is too large to process.")

        # Phone cameras record the sensor's orientation rather than rotating
        # the pixels, so skipping this shows a portrait photo on its side.
        image = ImageOps.exif_transpose(image) or image
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        image = ImageOps.fit(
            image, (AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS
        )
    except Image.DecompressionBombError as exc:
        # Pillow's own ceiling, checked inside `open` for a canvas more than
        # twice its default limit — before the check above can run.
        raise InvalidImage("That image is too large to process.") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImage from exc

    out = io.BytesIO()
    image.save(out, format="WEBP", quality=82)
    return out.getvalue()
