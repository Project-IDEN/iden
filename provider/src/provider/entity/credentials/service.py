"""Changing the two things that prove who you are."""

from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from provider.authz.logout import service as logout_service
from provider.core.security import hash_secret, verify_secret
from provider.entity.credentials.errors import EmailTaken, SamePassword, WrongPassword
from provider.shared.models import RefreshToken, User


async def _invalidate_everything_else(
    session: AsyncSession, redis: Redis, user: User, *, keep_session: str | None
) -> int:
    """Revoke every refresh token and end every other session.

    A credential change that leaves the old sessions alive has not really taken
    effect — the whole point is to lock out whoever might have had the old one.
    The session doing the changing survives, because signing someone out of the
    page they are using to secure their account is hostile.
    """
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )

    return await logout_service.end_all_sessions(
        session, redis, user.id, keep=keep_session
    )


async def change_password(
    session: AsyncSession,
    redis: Redis,
    user: User,
    *,
    current: str,
    new: str,
    keep_session: str | None = None,
) -> int:
    if not verify_secret(user.password_hash, current):
        raise WrongPassword
    if verify_secret(user.password_hash, new):
        raise SamePassword

    user.password_hash = hash_secret(new)
    ended = await _invalidate_everything_else(
        session, redis, user, keep_session=keep_session
    )
    await session.commit()
    return ended


async def change_email(
    session: AsyncSession,
    redis: Redis,
    user: User,
    *,
    email: str,
    current: str,
    keep_session: str | None = None,
) -> int:
    if not verify_secret(user.password_hash, current):
        raise WrongPassword

    taken = await session.scalar(
        select(User).where(User.email == email, User.id != user.id)
    )
    if taken:
        raise EmailTaken

    user.email = email
    # The new address is unproven until it is verified. Keeping the old
    # verification would let someone claim an address they cannot read.
    user.email_verified_at = None

    ended = await _invalidate_everything_else(
        session, redis, user, keep_session=keep_session
    )
    await session.commit()
    return ended
