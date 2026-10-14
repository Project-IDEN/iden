from datetime import UTC, datetime
from uuid import UUID

import pyotp
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.authz.login.errors import (
    InactiveUser,
    InvalidCredentials,
    InvalidTotpCode,
    TotpNotEnrolled,
)
from provider.biometric import service as face
from provider.core.config import settings
from provider.core.security import (
    decrypt_secret,
    hash_secret,
    verify_secret_async,
)
from provider.shared.enums import AmrMethod
from provider.shared.models import TotpCredential, User

# Verifying against this when no user matches keeps the response time of an
# unknown email indistinguishable from a wrong password, so the endpoint cannot
# be used to enumerate accounts.
_DUMMY_HASH = hash_secret("iden-timing-equalizer")


async def authenticate_password(
    session: AsyncSession, email: str, password: str
) -> User:
    user = await session.scalar(select(User).where(User.email == email))

    if user is None:
        await verify_secret_async(_DUMMY_HASH, password)
        raise InvalidCredentials

    if not await verify_secret_async(user.password_hash, password):
        raise InvalidCredentials

    if not user.is_active:
        raise InactiveUser

    user.last_login_at = datetime.now(UTC)
    return user


# A code is good for one sign-in (RFC 6238 Section 5.2), remembered for as long as
# `valid_window=1` could accept it: its own step and the one either side.
USED_CODE_SECONDS = 90


async def verify_totp(
    session: AsyncSession, redis: Redis, user: User, code: str
) -> None:
    credential = await session.scalar(
        select(TotpCredential).where(
            TotpCredential.user_id == user.id, TotpCredential.confirmed_at.is_not(None)
        )
    )
    if credential is None:
        raise TotpNotEnrolled

    # A failure to decrypt raises rather than returning: the only safe outcomes
    # when the key is wrong are the real secret or a loud refusal, never a value
    # that might compare equal.
    secret = decrypt_secret(credential.secret_encrypted, context=str(user.id))

    # valid_window=1 accepts the adjacent 30s step, covering ordinary clock drift
    # between the phone and the server (RFC 6238 Section 6).
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        raise InvalidTotpCode
    # Otherwise a code read over someone's shoulder, or relayed by a phishing
    # page, signs a second browser in alongside the first.
    used = f"totp-used:{user.id}:{code}"
    if not await redis.set(used, 1, nx=True, ex=USED_CODE_SECONDS):
        raise InvalidTotpCode


async def enrolled_methods(session: AsyncSession, user_id: UUID) -> set[str]:
    """The methods this person could sign in with right now.

    The highest level they can reach is derived from this, which is what lets a
    request for more than that be refused instead of shown a form they cannot
    complete.
    """
    methods = {AmrMethod.PWD.value}
    if await has_confirmed_totp(session, user_id):
        methods.add(AmrMethod.OTP.value)
    if settings.iden_biometric_enabled and await face.is_enrolled(session, user_id):
        methods.add(AmrMethod.FACE.value)
    return methods


async def has_confirmed_totp(session: AsyncSession, user_id: UUID) -> bool:
    """Whether this person has finished setting up an authenticator.

    Unconfirmed enrollments do not count. A credential exists from the moment
    someone opens the QR code, and treating that as a second factor would lock
    out anyone who walked away from the screen.
    """
    return (
        await session.scalar(
            select(TotpCredential.id).where(
                TotpCredential.user_id == user_id,
                TotpCredential.confirmed_at.is_not(None),
            )
        )
    ) is not None
