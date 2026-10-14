from typing import Annotated

from fastapi import Depends, UploadFile

from provider.biometric.errors import BadFrames, BiometricDisabled
from provider.core.config import settings
from provider.core.storage import Storage, get_storage

# Nine frames are asked for; this is the ceiling, not the expectation.
MAX_FRAMES = 16
# A 640×480 JPEG from a browser is 40–80 KB.
MAX_FRAME_BYTES = 300_000
FRAME_TYPES = {"image/jpeg"}


def require_biometric() -> None:
    """404 while the module is off, as though the route did not exist."""
    if not settings.iden_biometric_enabled:
        raise BiometricDisabled


def face_storage() -> Storage | None:
    """Blob storage when this deployment has any. Only enrolment photos use it,
    and only when they are kept."""
    return get_storage() if settings.blob_storage_configured else None


FaceStorageDep = Annotated[Storage | None, Depends(face_storage)]


async def read_frames(frames: list[UploadFile]) -> list[bytes]:
    if not 0 < len(frames) <= MAX_FRAMES:
        raise BadFrames(f"Send between 1 and {MAX_FRAMES} frames.")

    data = []
    for frame in frames:
        if frame.content_type not in FRAME_TYPES:
            raise BadFrames("Frames must be JPEG images.")
        content = await frame.read(MAX_FRAME_BYTES + 1)
        if len(content) > MAX_FRAME_BYTES:
            raise BadFrames("A frame is larger than the capture allows.")
        data.append(content)
    return data
