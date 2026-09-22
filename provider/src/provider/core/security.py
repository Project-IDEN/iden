"""Every credential IDEN holds, and how it is held.

What IDEN must later do with one decides the treatment:

- *compared* only (password, client secret) — argon2id, never recoverable
- *looked up by value* (authorization code, refresh token, session id) — SHA-256,
  a lookup key rather than a password
- *read back* (TOTP secret, to recompute a code) — encrypted under a key held
  outside the database
"""

import base64
import hashlib
import secrets
from functools import cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from provider.core.config import settings

# OWASP-recommended argon2id parameters.
_hasher = PasswordHasher(time_cost=1, memory_cost=64 * 1024, parallelism=4)


def hash_secret(secret: str) -> str:
    """Hash a user password or client secret. Salted, so the digest differs every call."""
    return _hasher.hash(secret)


def verify_secret(hashed: str | None, secret: str) -> bool:
    # `None` is a public client's absent `client_secret_hash`: nothing to verify
    # against, so nothing can match.
    if hashed is None:
        return False
    try:
        return _hasher.verify(hashed, secret)
    except VerifyMismatchError, VerificationError:
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


def generate_token(nbytes: int = 32) -> str:
    """A URL-safe random string for authorization codes, refresh tokens, and client secrets."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """
    Deterministic digest for tokens that must be *looked up* by value —
    authorization codes, refresh tokens, session ids.

    Argon2 salts every hash, so an argon2 digest cannot be used as a lookup key.
    These values are already high-entropy random strings, so they are not
    brute-forceable the way a password is and SHA-256 is sufficient.
    """
    return hashlib.sha256(token.encode()).hexdigest()


# --------------------------------------------------------------------------
# Secrets that have to be recoverable
#
# Stored in the clear, one SELECT on totp_credentials is a working second factor
# for every enrolled account — and the realistic route to that is a backup or a
# replica, not a compromised host. The passwords in the same dump are argon2, so
# this was the weakest thing in it. AES-256-GCM under a key beside the signing
# keys makes a dump inert.
# --------------------------------------------------------------------------

# `v1:<base64(nonce || ciphertext || tag)>`. Versioned so the format is
# self-describing, and so a value that is not encrypted at all is refused rather
# than read as cleartext.
_SECRET_VERSION = "v1"
_NONCE_BYTES = 12


class EncryptionKeyError(RuntimeError):
    """The key that protects recoverable secrets is missing or unusable."""


def generate_encryption_key() -> bytes:
    """A new 256-bit key, as written to disk by `scripts.gen_keys`."""
    return AESGCM.generate_key(bit_length=256)


@cache
def _cipher() -> AESGCM:
    """The key, read once.

    Cached and failing like the signing keys: a deployment that never generated
    one finds out at the first enrolment, with the fixing command named.
    """
    path: Path = settings.totp_key_path
    try:
        material = path.read_bytes()
    except OSError as exc:
        raise EncryptionKeyError(
            f"No secret-encryption key at {path}. "
            "Run: uv run python -m scripts.gen_keys"
        ) from exc

    key = base64.b64decode(material.strip(), validate=True)
    if len(key) != 32:
        raise EncryptionKeyError(
            f"{path} is not a 256-bit key: expected 32 bytes, found {len(key)}."
        )
    return AESGCM(key)


def encrypt_secret(plaintext: str, *, context: str) -> str:
    """Encrypt a secret that must later be read back.

    `context` is authenticated but not encrypted: the id of whoever the secret
    belongs to, so a ciphertext cannot be moved onto another account.
    """
    nonce = secrets.token_bytes(_NONCE_BYTES)
    sealed = _cipher().encrypt(nonce, plaintext.encode(), context.encode())
    return f"{_SECRET_VERSION}:{base64.b64encode(nonce + sealed).decode()}"


def decrypt_secret(stored: str, *, context: str) -> str:
    """The plaintext behind `encrypt_secret`.

    Raises rather than returning anything on failure: the caller is about to
    verify a second factor, where the only safe outcomes are the real secret or a
    loud refusal.
    """
    version, _, encoded = stored.partition(":")
    if version != _SECRET_VERSION or not encoded:
        raise EncryptionKeyError(
            f"Stored secret is not in a format this version understands: {version!r}."
        )

    raw = base64.b64decode(encoded, validate=True)
    nonce, sealed = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    try:
        return _cipher().decrypt(nonce, sealed, context.encode()).decode()
    except InvalidTag as exc:
        raise EncryptionKeyError(
            "Stored secret does not decrypt under the current key: it was "
            "written under a different one, or the row was altered."
        ) from exc
