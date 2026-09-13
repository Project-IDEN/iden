import secrets
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from provider.admin import lockout
from provider.admin.users.errors import (
    EmailTaken,
    UnknownRoles,
    UnknownScopes,
    UsernameTaken,
    UserNotFound,
)
from provider.admin.users.schemas import UserCreate, UserUpdate
from provider.authz.logout import service as logout_service
from provider.authz.services.token_service import now
from provider.core.security import hash_secret
from provider.shared.models import (
    Group,
    RefreshToken,
    Role,
    Scope,
    User,
    user_groups,
    user_roles,
)


async def _resolve(session: AsyncSession, model, ids: list[UUID], error):
    if not ids:
        return []

    rows = list(await session.scalars(select(model).where(model.id.in_(ids))))
    if len(rows) != len(set(ids)):
        found = {row.id for row in rows}
        raise error(missing=[str(i) for i in set(ids) - found])

    return rows


async def list_users(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    group_id: UUID | None = None,
    role_id: UUID | None = None,
    is_active: bool | None = None,
) -> tuple[list[User], int]:
    query = select(User)
    count = select(func.count(User.id))

    if search:
        pattern = f"%{search.lower()}%"
        condition = func.lower(User.email).like(pattern) | func.lower(
            User.username
        ).like(pattern)
        query, count = query.where(condition), count.where(condition)

    if group_id is not None:
        query = query.join(user_groups, user_groups.c.user_id == User.id).where(
            user_groups.c.group_id == group_id
        )
        count = count.join(user_groups, user_groups.c.user_id == User.id).where(
            user_groups.c.group_id == group_id
        )

    if role_id is not None:
        query = query.join(user_roles, user_roles.c.user_id == User.id).where(
            user_roles.c.role_id == role_id
        )
        count = count.join(user_roles, user_roles.c.user_id == User.id).where(
            user_roles.c.role_id == role_id
        )

    if is_active is not None:
        query, count = (
            query.where(User.is_active == is_active),
            count.where(User.is_active == is_active),
        )

    total = await session.scalar(count) or 0
    users = list(
        await session.scalars(query.order_by(User.email).limit(limit).offset(offset))
    )
    return users, total


async def get_user(session: AsyncSession, user_id: UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise UserNotFound
    return user


async def create_user(
    session: AsyncSession, data: UserCreate
) -> tuple[User, str | None]:
    """Returns the user and, when one was generated, the cleartext password.

    Generated once and never stored — the caller must show it to the operator
    immediately or it is gone.
    """
    if await session.scalar(select(User).where(User.email == data.email)):
        raise EmailTaken
    if await session.scalar(select(User).where(User.username == data.username)):
        raise UsernameTaken

    password = data.password or secrets.token_urlsafe(18)
    generated = None if data.password else password

    user = User(
        email=data.email,
        username=data.username,
        display_name=data.display_name,
        password_hash=hash_secret(password),
    )
    user.roles = await _resolve(session, Role, data.role_ids, UnknownRoles)
    user.groups = await _resolve(session, Group, data.group_ids, UnknownRoles)

    session.add(user)
    await session.commit()
    # See create_group: relationships on a new object must be loaded before the
    # response reads them.
    await session.refresh(user)
    return user, generated


async def update_user(
    session: AsyncSession, redis: Redis, user_id: UUID, data: UserUpdate
) -> User:
    user = await get_user(session, user_id)

    if data.email is not None and data.email != user.email:
        if await session.scalar(select(User).where(User.email == data.email)):
            raise EmailTaken
        user.email = data.email

    if data.username is not None and data.username != user.username:
        if await session.scalar(select(User).where(User.username == data.username)):
            raise UsernameTaken
        user.username = data.username

    if data.display_name is not None:
        user.display_name = data.display_name

    if data.is_active is not None:
        user.is_active = data.is_active
        # Deactivation has to reach existing sessions and refresh tokens, or the
        # account stays usable until they expire on their own.
        if not data.is_active:
            await revoke_everything(session, redis, user_id)
            await lockout.refuse_if_last(session)

    await session.commit()
    return user


async def set_roles(session: AsyncSession, user_id: UUID, role_ids: list[UUID]) -> User:
    user = await get_user(session, user_id)
    user.roles = await _resolve(session, Role, role_ids, UnknownRoles)
    await lockout.refuse_if_last(session)
    await session.commit()
    return user


async def set_direct_scopes(
    session: AsyncSession, user_id: UUID, scope_ids: list[UUID]
) -> User:
    user = await get_user(session, user_id)
    user.scopes = await _resolve(session, Scope, scope_ids, UnknownScopes)
    await lockout.refuse_if_last(session)
    await session.commit()
    return user


async def revoke_everything(session: AsyncSession, redis: Redis, user_id: UUID) -> None:
    """Drop every session and refresh token this user holds."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now())
    )
    await logout_service.end_all_sessions(session, redis, user_id)


async def reset_password(
    session: AsyncSession, redis: Redis, user_id: UUID, password: str | None
) -> str | None:
    user = await get_user(session, user_id)

    new_password = password or secrets.token_urlsafe(18)
    generated = None if password else new_password
    user.password_hash = hash_secret(new_password)

    await revoke_everything(session, redis, user_id)
    await session.commit()
    return generated


async def delete_user(session: AsyncSession, redis: Redis, user_id: UUID) -> None:
    user = await get_user(session, user_id)
    await revoke_everything(session, redis, user_id)
    await session.delete(user)
    await lockout.refuse_if_last(session)
    await session.commit()
