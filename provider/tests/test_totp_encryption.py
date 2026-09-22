"""TOTP secrets are encrypted at rest.

A TOTP secret cannot be hashed — verifying a code means recomputing it from the
secret — so the usual answer for a stored credential does not apply. Left in the
clear, one `SELECT` on `totp_credentials` is a working second factor for every
enrolled account, and the realistic way someone gets that is a backup or a
replica rather than a compromised host. The passwords in the same dump are
argon2, so this was the weakest thing in it.
"""

import base64

import pyotp
import pytest
from sqlalchemy import select

from provider.core.security import (
    EncryptionKeyError,
    decrypt_secret,
    encrypt_secret,
    generate_encryption_key,
)
from provider.shared.models import TotpCredential

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")


class TestTheCipher:
    def test_a_secret_survives_a_round_trip(self):
        secret = pyotp.random_base32()
        sealed = encrypt_secret(secret, context="owner")

        assert decrypt_secret(sealed, context="owner") == secret

    def test_the_ciphertext_does_not_contain_the_secret(self):
        secret = pyotp.random_base32()
        sealed = encrypt_secret(secret, context="owner")

        assert secret not in sealed
        assert secret.encode() not in base64.b64decode(sealed.partition(":")[2])

    def test_the_same_secret_encrypts_differently_every_time(self):
        """A fresh nonce per call. Otherwise equal ciphertexts would reveal
        which accounts share a secret — and a reused nonce breaks GCM outright."""
        secret = pyotp.random_base32()

        assert encrypt_secret(secret, context="owner") != encrypt_secret(
            secret, context="owner"
        )

    def test_a_ciphertext_cannot_be_moved_to_another_owner(self):
        """The owner's id is authenticated. Without that, anyone who could write
        to the table could paste a second factor they control onto someone
        else's row."""
        sealed = encrypt_secret(pyotp.random_base32(), context="alice")

        with pytest.raises(EncryptionKeyError):
            decrypt_secret(sealed, context="mallory")

    def test_a_tampered_ciphertext_is_refused(self):
        sealed = encrypt_secret(pyotp.random_base32(), context="owner")
        prefix, _, encoded = sealed.partition(":")
        raw = bytearray(base64.b64decode(encoded))
        raw[-1] ^= 0xFF

        with pytest.raises(EncryptionKeyError):
            decrypt_secret(
                f"{prefix}:{base64.b64encode(bytes(raw)).decode()}", context="owner"
            )

    def test_a_cleartext_value_is_refused_rather_than_read(self):
        """There is no fallback to reading the column as a plain secret. One
        would be a way to strip the encryption and have it still work."""
        with pytest.raises(EncryptionKeyError):
            decrypt_secret(pyotp.random_base32(), context="owner")

    def test_a_secret_written_under_another_key_does_not_decrypt(self, monkeypatch):
        sealed = encrypt_secret(pyotp.random_base32(), context="owner")

        from provider.core import security

        other = security.AESGCM(generate_encryption_key())
        monkeypatch.setattr(security, "_cipher", lambda: other)

        with pytest.raises(EncryptionKeyError):
            decrypt_secret(sealed, context="owner")


class TestEnrolment:
    async def test_what_lands_in_the_database_is_not_usable(
        self, client, db, entity_headers, member
    ):
        """The point of the whole exercise: someone reading the table cannot
        generate codes from what they find."""
        body = (await client.post("/entity/totp/enroll", headers=entity_headers)).json()

        stored = await db.scalar(
            select(TotpCredential).where(TotpCredential.user_id == member.id)
        )
        assert stored is not None

        # The secret is not in the column, in any form.
        assert body["secret"] not in stored.secret_encrypted
        sealed = base64.b64decode(stored.secret_encrypted.partition(":")[2])
        assert body["secret"].encode() not in sealed

        # And the column is not itself a working secret: someone who read the
        # table and fed what they found to an authenticator gets nothing.
        assert (
            decrypt_secret(stored.secret_encrypted, context=str(member.id))
            == body["secret"]
        )
        with pytest.raises(EncryptionKeyError):
            decrypt_secret(stored.secret_encrypted, context=str(member.id) + "x")

    async def test_the_code_from_the_returned_secret_still_confirms(
        self, client, entity_headers
    ):
        """Encryption is invisible to the person enrolling. The secret they
        scanned is the secret that verifies."""
        body = (await client.post("/entity/totp/enroll", headers=entity_headers)).json()

        response = await client.post(
            "/entity/totp/confirm",
            json={"code": pyotp.TOTP(body["secret"]).now()},
            headers=entity_headers,
        )

        assert response.status_code == 200
        assert response.json()["enrolled"] is True

    async def test_re_enrolling_replaces_the_stored_ciphertext(
        self, client, db, entity_headers, member
    ):
        first = (
            await client.post("/entity/totp/enroll", headers=entity_headers)
        ).json()["secret"]
        stored_first = await db.scalar(
            select(TotpCredential.secret_encrypted).where(
                TotpCredential.user_id == member.id
            )
        )

        second = (
            await client.post("/entity/totp/enroll", headers=entity_headers)
        ).json()["secret"]
        stored_second = await db.scalar(
            select(TotpCredential.secret_encrypted).where(
                TotpCredential.user_id == member.id
            )
        )

        assert first != second
        assert stored_first != stored_second
