"""Generate the key material IDEN needs: a signing keypair and a secret key.

Production deployments should mount keys from a secret store instead.

Both are generated here rather than in two commands because a deployment needs
both and a half-provisioned key directory fails later, at the first sign-in that
touches the missing one.
"""

import base64
import sys
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from provider.core.config import settings
from provider.core.security import generate_encryption_key


def signing_key() -> None:
    key_dir = settings.iden_signing_key_dir
    key_dir.mkdir(parents=True, exist_ok=True)

    # Filename stem becomes the kid; date-stamping makes the newest key sort last,
    # which is how core.crypto picks the active one.
    path = key_dir / f"iden-{datetime.now(UTC):%Y%m%d}.pem"
    if path.exists():
        print(f"Signing key already exists: {path}")
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    path.write_bytes(
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    )
    path.chmod(0o600)

    print(f"Wrote signing key: {path} (kid: {path.stem})")


def secret_key() -> None:
    """The key that encrypts TOTP secrets at rest.

    Never regenerated over an existing file. Replacing it would leave every
    enrolled authenticator undecryptable, which locks those people out of their
    own accounts — so overwriting is the one thing this must not do quietly.
    """
    path = settings.totp_key_path
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        print(f"Secret-encryption key already exists: {path}")
        return

    path.write_bytes(base64.b64encode(generate_encryption_key()))
    path.chmod(0o600)

    print(f"Wrote secret-encryption key: {path}")


def main() -> None:
    signing_key()
    secret_key()


if __name__ == "__main__":
    sys.exit(main())
