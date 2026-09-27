"""Changing your password.

The address is not changeable here or anywhere: it is fixed when the account is
created, because it names a mailbox on the organization's domain.
"""

from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from provider.authz.logout import service as logout_service
from provider.core.security import hash_secret_async, verify_secret_async
from provider.entity.credentials.errors import SamePassword, WrongPassword
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
    if not await verify_secret_async(user.password_hash, current):
        raise WrongPassword
    if await verify_secret_async(user.password_hash, new):
        raise SamePassword

    user.password_hash = await hash_secret_async(new)
    ended = await _invalidate_everything_else(
        session, redis, user, keep_session=keep_session
    )
    await session.commit()
    return ended
