from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    engine_env: Literal["dev", "prod"] = "dev"
    engine_log_level: str = "info"

    # The shared secret the provider presents. A file rather than a variable,
    # which `docker inspect` can read. Empty is accepted only in development.
    engine_token_file: Path | None = None

    engine_model_dir: Path = Path("models")
    engine_manifest: Path = Path("models.toml")
    # `auto` uses CUDA when onnxruntime-gpu can see a GPU and the CPU otherwise;
    # `cuda` refuses to start without one, so a misconfigured GPU host fails
    # loudly instead of quietly running twenty times slower.
    engine_device: Literal["auto", "cuda", "cpu"] = "auto"
    engine_workers: int = 1

    # A capture is 9 frames; this is the ceiling, not the expectation.
    engine_max_frames: int = 16
    engine_max_frame_bytes: int = 400_000
    # Decoded pixels, not file size: a small PNG can declare a huge canvas.
    engine_max_pixels: int = 4_000_000

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    @field_validator("engine_token_file", mode="before")
    @classmethod
    def blank_means_unset(cls, value: object) -> object:
        """Compose passes an unset variable as an empty string, which would
        otherwise parse to `Path(".")` and read as set."""
        return value or None

    def token(self) -> str | None:
        if self.engine_token_file is None:
            return None
        return self.engine_token_file.read_text().strip() or None


settings = Settings()
