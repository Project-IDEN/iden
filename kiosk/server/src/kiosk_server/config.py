from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    kiosk_env: Literal["dev", "prod"] = "dev"
    kiosk_log_level: str = "info"
    # IDEN's public address, the issuer — where the device pairs and enrols.
    kiosk_issuer: str = "http://localhost:8000"
    # Holds `credentials.json`, the one thing on the device worth stealing. A
    # volume in Docker, so it survives an image update.
    kiosk_data_dir: Path = Path("data")
    # The built kiosk UI. Unset in development, where Vite serves it.
    kiosk_ui_dir: Path | None = None
    kiosk_version: str = "dev"
    # Above the provider's own engine timeout, so its 503 arrives before ours.
    kiosk_timeout: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


settings = Settings()
