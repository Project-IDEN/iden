"""Password recovery.

In the AuthZ module rather than the Entity RS because a locked-out person has
no token, so no self-service route can help them. Without this, every forgotten
password is an administrator's support ticket.
"""

from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from provider.authz.logout import service as logout_service
from provider.authz.recovery.errors import InvalidResetToken
from provider.core import notifier
from provider.core.config import settings
from provider.core.security import generate_token, hash_secret, hash_token
from provider.shared.models import RefreshToken, User

TOKEN_TTL = 900


def _key(token: str) -> str:
    # Hashed like every other credential: a Redis dump must not yield a working
    # reset link.
    return f"password_reset:{hash_token(token)}"


async def request_reset(session: AsyncSession, redis: Redis, email: str) -> None:
    """Send a reset link, if there is anyone to send it to.

    Says nothing about whether the address exists — the endpoint answers the
    same way either way. A different response for an unknown address turns this
    into a way to discover who has an account.
    """
    user = await session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        return

    token = generate_token()
    await redis.set(_key(token), str(user.id), ex=TOKEN_TTL)

    link = f"{settings.iden_auth_ui_base_url}/auth/reset?token={token}"
    await notifier.send(
        to=user.email,
        subject="Reset your password",
        body=f"Use this link within 15 minutes: {link}",
    )


async def confirm_reset(
    session: AsyncSession, redis: Redis, token: str, new_password: str
) -> None:
    """Spend the token and set the password.

    Deleted before the password is written, so a token cannot be used twice
    even if two requests arrive together.
    """
    raw = await redis.getdel(_key(token))
    if raw is None:
        raise InvalidResetToken

    user = await session.get(User, UUID(str(raw)))
    if user is None or not user.is_active:
        raise InvalidResetToken

    user.password_hash = hash_secret(new_password)

    # Whoever prompted the reset may be the reason it was needed. Everything
    # issued before this moment stops working.
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await logout_service.end_all_sessions(session, redis, user.id)
    await session.commit()
