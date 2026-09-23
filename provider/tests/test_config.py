"""Settings that are easy to set wrongly."""

from pathlib import Path

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
