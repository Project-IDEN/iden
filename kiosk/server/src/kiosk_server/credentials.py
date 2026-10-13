"""The device's client secret, on disk.

Written once, at pairing, readable by its owner alone, and replaced whole so a
power cut mid-write leaves the old file rather than half of a new one.
"""

import os
from pathlib import Path

from kiosk_server.config import settings
from kiosk_server.schemas import Credentials


def _path() -> Path:
    return settings.kiosk_data_dir / "credentials.json"


def load() -> Credentials | None:
    path = _path()
    return Credentials.model_validate_json(path.read_text()) if path.exists() else None


def save(credentials: Credentials) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write(credentials.model_dump_json())
    partial.replace(path)


def forget() -> None:
    _path().unlink(missing_ok=True)
