"""Settings that are easy to set wrongly."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from provider.core.config import Settings


class TestTotpKeyPath:
    def test_unset_falls_back_to_the_signing_key_directory(self):
        settings = Settings(iden_signing_key_dir=Path("/keys"))

        assert settings.totp_key_path == Path("/keys/totp.key")

    def test_blank_is_treated_as_unset(self):
        """`IDEN_TOTP_KEY_FILE=` is what the example file suggests, and every
        other setting here is a string whose empty value means "leave it".

        Parsed literally it is `Path(".")`, which is truthy — so `totp_key_path`
        would resolve to a directory and enrolment would fail on a message about
        a missing key.
        """
        settings = Settings(
            iden_signing_key_dir=Path("/keys"),
            iden_totp_key_file="",  # pyright: ignore[reportArgumentType]
        )

        assert settings.iden_totp_key_file is None
        assert settings.totp_key_path == Path("/keys/totp.key")

    def test_an_explicit_path_wins(self):
        settings = Settings(
            iden_signing_key_dir=Path("/keys"),
            iden_totp_key_file=Path("/secrets/totp.key"),
        )

        assert settings.totp_key_path == Path("/secrets/totp.key")


SAFE_PROD: dict[str, Any] = {
    "iden_env": "prod",
    "iden_issuer": "https://iden.example.org",
    "iden_auth_ui_base_url": "https://iden.example.org",
    "iden_database_url": "postgresql+asyncpg://iden:s3cret-db@postgres:5432/iden",
    "iden_redis_url": "redis://:s3cret-redis@redis:6379/0",
    "iden_s3_endpoint_url": "http://seaweedfs:8333",
    "iden_s3_secret_key": "s3cret-blob",
    "iden_forwarded_allow_ips": "172.31.250.0/24",
}


class TestUnsafeDeployment:
    """Compose substitutes the published default for an empty value, so a
    forgotten line in deploy/.env becomes a password anyone can read."""

    def test_a_safe_production_configuration_starts(self):
        assert Settings(**SAFE_PROD).iden_env == "prod"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("iden_issuer", "http://iden.example.org"),
            ("iden_auth_ui_base_url", "http://iden.example.org"),
            ("iden_database_url", "postgresql+asyncpg://iden:iden@postgres:5432/iden"),
            ("iden_database_url", "postgresql+asyncpg://iden@postgres:5432/iden"),
            ("iden_redis_url", "redis://:iden@redis:6379/0"),
            ("iden_redis_url", "redis://redis:6379/0"),
            ("iden_s3_secret_key", "idensecret"),
            ("iden_s3_secret_key", ""),
            ("iden_forwarded_allow_ips", "*"),
        ],
    )
    def test_production_refuses(self, field, value):
        with pytest.raises(ValidationError, match="unsafe configuration"):
            Settings(**{**SAFE_PROD, field: value})

    def test_the_blob_secret_is_not_needed_without_a_store(self):
        settings = Settings(
            **{**SAFE_PROD, "iden_s3_endpoint_url": "", "iden_s3_secret_key": ""}
        )

        assert not settings.blob_storage_configured

    def test_development_refuses_an_https_issuer(self):
        """That is a real deployment, which dev would serve with a non-Secure
        cookie and the admin API documented at /docs."""
        with pytest.raises(ValidationError, match="IDEN_ENV=prod"):
            Settings(iden_env="dev", iden_issuer="https://iden.example.org")

    def test_development_accepts_the_published_defaults(self):
        settings = Settings(
            iden_env="dev",
            iden_issuer="http://localhost:8000",
            iden_database_url="postgresql+asyncpg://iden:iden@localhost:5432/iden",
        )

        assert settings.iden_env == "dev"
