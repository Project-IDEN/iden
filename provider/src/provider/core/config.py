from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application
    iden_env: Literal["dev", "prod"] = "dev"
    iden_log_level: str = "info"
    # Each router declares its own prefix (/oauth2, /admin, /entity, /api/v1/auth).
    # This is only for deployments that mount the whole app under a sub-path, and
    # must stay empty otherwise: OIDC requires /.well-known/* at the host root.
    iden_api_prefix: str = ""
    iden_allowed_admin_origins: list[str] = []
    # Addresses whose `X-Forwarded-For` is believed, comma-separated; CIDRs are
    # accepted. Empty trusts nobody, which is right when nothing sits in front:
    # the socket peer is then the only honest answer.
    #
    # Behind a proxy this is the one place that decides whose claim about the
    # caller's address is accepted, and both the rate limiter and the audit log
    # rest on the answer. Name the proxy. Never `*`, which accepts the header
    # from anyone and makes every per-address limit and every audited address
    # forgeable.
    iden_forwarded_allow_ips: str = ""

    # Issuer
    iden_issuer: str = "http://localhost:8000"
    iden_auth_ui_base_url: str = "http://localhost:4000"

    # Branding. The same IDEN_ORG_NAME the two frontends read, so the name in
    # the sign-in lockup and the name in someone's authenticator app are one
    # setting rather than two that can disagree.
    iden_org_name: str = ""

    # Storage
    iden_database_url: str = "postgresql+asyncpg://iden:iden@localhost:5432/iden"
    iden_redis_url: str = "redis://localhost:6379/0"

    # Blob storage, over the S3 API. Empty endpoint means no store is attached
    # and profile photos are simply unavailable — every other feature works, so
    # a deployment that does not want a third service does not have to run one.
    iden_s3_endpoint_url: str = ""
    iden_s3_access_key: str = ""
    iden_s3_secret_key: str = ""
    iden_s3_bucket: str = "iden"
    iden_s3_region: str = "us-east-1"
    # Refused before the file is decoded. Generous for a photo, small enough
    # that an upload cannot be used to make the provider hold a large buffer.
    iden_avatar_max_bytes: int = 5_242_880

    # Crypto
    iden_signing_key_dir: Path = Path("keys")
    iden_signing_algorithm: str = "RS256"

    # Lifetimes (seconds)
    # This one is quoted to the user: revoking a session cannot reach an access
    # token already issued, so the dashboard's sessions screen tells them the
    # revoked device stops working "within ten minutes". Change this and that
    # sentence is wrong.
    iden_access_token_ttl: int = 600
    iden_id_token_ttl: int = 600
    iden_refresh_token_ttl: int = 2_592_000
    iden_auth_code_ttl: int = 60
    iden_session_ttl: int = 86_400
    iden_challenge_ttl: int = 600
    # How long a spent refresh token keeps returning the tokens it was already
    # exchanged for. Two browser tabs refreshing at once, or one request that
    # timed out and was retried, are indistinguishable from theft without it.
    # Long enough to cover a stalled request; short enough that a stolen token
    # is unlikely to be spent inside it.
    iden_refresh_grace_period: int = 30

    # Rate limiting. Off only for load tests against a deployment you own —
    # with it off, `/api/v1/auth/login` is both a brute-force target and a way
    # to exhaust the machine's CPU, since argon2 is expensive for the server.
    iden_rate_limit_enabled: bool = True

    # Developer self-service. How many applications one person may register
    # before an administrator has to get involved — a cap, not a policy: a
    # showcase with fifty participants should not let one of them fill the
    # clients table.
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
