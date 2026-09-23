from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application
    iden_env: Literal["dev", "prod"] = "dev"
    iden_log_level: str = "info"
    # Only for mounting the whole app under a sub-path; each router declares its
    # own prefix. Empty otherwise — OIDC requires /.well-known/* at the host root.
    iden_api_prefix: str = ""
    iden_allowed_admin_origins: list[str] = []
    # Addresses whose `X-Forwarded-For` is believed; CIDRs accepted. Empty trusts
    # nobody, right when nothing sits in front. Behind a proxy this decides whose
    # claim about the caller's address is accepted, and both the rate limiter and
    # the audit log rest on it. Name the proxy; never `*`.
    iden_forwarded_allow_ips: str = ""

    # Issuer
    iden_issuer: str = "http://localhost:8000"
    iden_auth_ui_base_url: str = "http://localhost:4000"

    # The same IDEN_ORG_NAME the frontends read, so the sign-in lockup and an
    # authenticator app entry are one setting rather than two that can disagree.
    iden_org_name: str = ""

    # Storage
    iden_database_url: str = "postgresql+asyncpg://iden:iden@localhost:5432/iden"
    iden_redis_url: str = "redis://localhost:6379/0"

    # Empty endpoint means no store is attached and profile photos are
    # unavailable; every other feature works.
    iden_s3_endpoint_url: str = ""
    iden_s3_access_key: str = ""
    iden_s3_secret_key: str = ""
    iden_s3_bucket: str = "iden"
    iden_s3_region: str = "us-east-1"
    # Refused before the file is decoded.
    iden_avatar_max_bytes: int = 5_242_880

    # Crypto
    iden_signing_key_dir: Path = Path("keys")
    iden_signing_algorithm: str = "RS256"
    # Encrypts secrets IDEN reads back rather than compares — TOTP secrets, so
    # far. Defaults to `totp.key` beside the signing keys, which are already
    # mounted read-only, kept out of the image and on the backup list. A file
    # rather than an environment variable, which `docker inspect` can read.
    #
    # Losing it is not recoverable: every enrolled authenticator stops verifying
    # until an administrator clears the enrolment. Back it up with the keys.
    iden_totp_key_file: Path | None = None

    # Lifetimes (seconds)
    # Quoted to the user: the sessions screen says a revoked device stops working
    # "within ten minutes". Change this and that sentence is wrong.
    iden_access_token_ttl: int = 600
    iden_id_token_ttl: int = 600
    iden_refresh_token_ttl: int = 2_592_000
    iden_auth_code_ttl: int = 60
    iden_session_ttl: int = 86_400
    iden_challenge_ttl: int = 600
    # How long a spent refresh token keeps returning what it was exchanged for.
    # Without it, two tabs refreshing at once look exactly like theft.
    iden_refresh_grace_period: int = 30

    # Off only for load tests against a deployment you own: with it off,
    # `/api/v1/auth/login` is a brute-force target and a way to burn the CPU.
    iden_rate_limit_enabled: bool = True

    # A cap, not a policy: a showcase with fifty participants should not let one
    # of them fill the clients table.
    iden_developer_max_clients: int = 5

    # Bootstrap
    iden_bootstrap_admin_email: str = "admin@localhost"
    iden_bootstrap_admin_password: str = ""

    # Biometric extension
    iden_biometric_enabled: bool = False
    iden_engine_base_url: str = "http://engine:8000"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    @field_validator("iden_totp_key_file", mode="before")
    @classmethod
    def blank_means_unset(cls, value: object) -> object:
        """An empty value is no value.

        Every other setting here is a `str` with an `""` default, so writing
        `IDEN_TOTP_KEY_FILE=` in a `.env` — which is what the example file
        suggests — looks like leaving it alone. Without this it parses to
        `Path(".")`, which is truthy, so `totp_key_path` resolves to a directory
        and enrolment fails on a message about a missing key.
        """
        return value or None

    @property
    def totp_key_path(self) -> Path:
        return self.iden_totp_key_file or self.iden_signing_key_dir / "totp.key"

    @property
    def blob_storage_configured(self) -> bool:
        return bool(self.iden_s3_endpoint_url)

    @property
    def organization_name(self) -> str:
        """Who people think they are signing in to. IDEN when nothing is set."""
        return self.iden_org_name or "IDEN"

    @property
    def admin_audience(self) -> str:
        return f"{self.iden_issuer}/admin"

    @property
    def entity_audience(self) -> str:
        return f"{self.iden_issuer}/entity"

    @property
    def developer_audience(self) -> str:
        return f"{self.iden_issuer}/developer"

    @property
    def biometric_audience(self) -> str:
        return f"{self.iden_issuer}/biometric"


settings = Settings()
