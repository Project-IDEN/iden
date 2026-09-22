"""Enrolling and removing an authenticator app."""

from datetime import UTC, datetime

import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.core.config import settings
from provider.core.security import decrypt_secret, encrypt_secret
from provider.entity.totp.errors import AlreadyEnrolled, NotEnrolling, WrongCode
from provider.shared.models import TotpCredential, User


def _label_safe(issuer: str) -> str:
    """Strip what would split an `otpauth` label into the wrong pieces.

    The label is `issuer:account`, and an authenticator app reads everything
    before the first colon as the issuer — so a colon or a slash inside the
    issuer arrives as two mangled halves. That is what the issuer URL did:
    `https://iden.live` showed up as "https: //iden.live". The organization
    name is operator-supplied, so it gets the same treatment.
    """
    return " ".join(issuer.replace(":", " ").replace("/", " ").split())


async def _credential(session: AsyncSession, user: User) -> TotpCredential | None:
    return await session.scalar(
        select(TotpCredential).where(TotpCredential.user_id == user.id)
    )


async def status(session: AsyncSession, user: User) -> TotpCredential | None:
    credential = await _credential(session, user)
    return credential if credential and credential.confirmed_at else None


async def begin(session: AsyncSession, user: User) -> tuple[str, str]:
    """Create an unconfirmed credential and return (secret, otpauth URI).

    Enrollment is two-step on purpose: the credential does not count until a
    generated code comes back, so a mis-scanned QR code cannot lock someone out
    of their own account.
    """
    credential = await _credential(session, user)
    if credential and credential.confirmed_at:
        raise AlreadyEnrolled

    secret = pyotp.random_base32()
    if credential is None:
        credential = TotpCredential(user_id=user.id)
        session.add(credential)
    # An abandoned enrollment is simply overwritten: it never counted.
    credential.secret_encrypted = encrypt_secret(secret, context=str(user.id))
    await session.commit()

    uri = pyotp.TOTP(secret).provisioning_uri(
        name=user.email, issuer_name=_label_safe(settings.organization_name)
    )
    return secret, uri


async def confirm(session: AsyncSession, user: User, code: str) -> TotpCredential:
    credential = await _credential(session, user)
    if credential is None or credential.confirmed_at:
        raise NotEnrolling

    secret = decrypt_secret(credential.secret_encrypted, context=str(user.id))
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        raise WrongCode

    credential.confirmed_at = datetime.now(UTC)
    await session.commit()
    return credential


async def remove(session: AsyncSession, user: User) -> None:
    credential = await _credential(session, user)
    if credential is not None:
        await session.delete(credential)
        await session.commit()
