"""The device's client secret, on disk.

Written once, at pairing, readable by its owner alone, and replaced whole so a
power cut mid-write leaves the old file rather than half of a new one.
"""

import os
from pathlib import Path

from pydantic import ValidationError

from kiosk_server.config import settings
from kiosk_server.logging import logger
from kiosk_server.schemas import Credentials


def _path() -> Path:
    return settings.kiosk_data_dir / "credentials.json"


def load() -> Credentials | None:
    """The saved credentials, or None when there are none worth using.

    An unreadable file is treated as unpaired rather than raised: raising here
    stops the server at startup, and the screen then says "Starting up…"
    forever, where pairing again would have fixed it.
    """
    path = _path()
    if not path.exists():
        return None
    try:
        return Credentials.model_validate_json(path.read_text())
    except ValidationError:
        logger.error("Credentials file is unreadable; this kiosk must be paired again")
        path.unlink()
        return None


def save(credentials: Credentials) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(credentials.model_dump_json())
        file.flush()
        os.fsync(file.fileno())
    partial.replace(path)
    # The rename is durable only once the directory is: without this, a power
    # cut can leave the new name pointing at nothing.
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def forget() -> None:
    _path().unlink(missing_ok=True)
