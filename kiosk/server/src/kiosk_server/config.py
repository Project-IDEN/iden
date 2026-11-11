import ipaddress
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _stays_local(host: str) -> bool:
    """Loopback or a private address: traffic that never leaves a network the
    deployment controls, such as a laptop on the same LAN for a demonstration."""
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private


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

    @model_validator(mode="after")
    def https_in_prod(self) -> Self:
        """The kiosk sends its client secret and people's faces to the issuer."""
        issuer = urlsplit(self.kiosk_issuer)
        if (
            self.kiosk_env == "prod"
            and issuer.scheme != "https"
            and not _stays_local(issuer.hostname or "")
        ):
            raise ValueError(
                "KIOSK_ISSUER must be https:// in prod, unless it is a loopback or "
                "private-network address: the kiosk sends its secret and faces there."
            )
        return self


settings = Settings()
