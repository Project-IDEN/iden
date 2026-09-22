from uuid import UUID

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.admin import delegation, lockout
from provider.admin.groups.errors import (
    GroupNameTaken,
    GroupNotFound,
    UnknownRoles,
    UnknownUsers,
)
from provider.admin.groups.schemas import GroupCreate, GroupUpdate
from provider.shared.models import Group, Role, User, user_groups


async def resolve_roles(session: AsyncSession, role_ids: list[UUID]) -> list[Role]:
    if not role_ids:
        return []

    roles = list(await session.scalars(select(Role).where(Role.id.in_(role_ids))))
    if len(roles) != len(set(role_ids)):
        found = {role.id for role in roles}
        raise UnknownRoles(missing=[str(i) for i in set(role_ids) - found])

    return roles


async def list_groups(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[Group], int]:
    total = await session.scalar(select(func.count(Group.id))) or 0
    groups = list(
        await session.scalars(
            select(Group).order_by(Group.name).limit(limit).offset(offset)
        )
    )
    return groups, total


async def get_group(session: AsyncSession, group_id: UUID) -> Group:
    group = await session.get(Group, group_id)
    if group is None:
        raise GroupNotFound
    return group


async def member_count(session: AsyncSession, group_id: UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(user_groups)
        .where(user_groups.c.group_id == group_id)
    )
    return count or 0


async def member_counts(
    session: AsyncSession, group_ids: list[UUID]
) -> dict[UUID, int]:
    """Counts for a page of groups in one query, rather than one query each."""
    if not group_ids:
        return {}

    rows = await session.execute(
        select(user_groups.c.group_id, func.count())
        .where(user_groups.c.group_id.in_(group_ids))
        .group_by(user_groups.c.group_id)
    )
    return {group_id: count for group_id, count in rows}


async def create_group(session: AsyncSession, data: GroupCreate) -> Group:
    if await session.scalar(select(Group).where(Group.name == data.name)):
        raise GroupNameTaken

    group = Group(name=data.name, description=data.description)
    session.add(group)
    await session.commit()
    # Refreshed so its relationships are loaded: on a new object they are unset,
    # and reading one in the response would trigger a lazy load, which fails
    # inside async code.
    await session.refresh(group)
    return group


async def update_group(
    session: AsyncSession, group_id: UUID, data: GroupUpdate
) -> Group:
    group = await get_group(session, group_id)

    if data.name is not None and data.name != group.name:
        if await session.scalar(select(Group).where(Group.name == data.name)):
            raise GroupNameTaken
        group.name = data.name

    if data.description is not None:
        group.description = data.description

    await session.commit()
    return group


async def set_group_roles(
    session: AsyncSession,
    group_id: UUID,
    role_ids: list[UUID],
    *,
    caller_scopes: set[str],
) -> Group:
    """A group's roles reach every member, present and future."""
    group = await get_group(session, group_id)
    group.roles = await resolve_roles(session, role_ids)
    delegation.refuse_undelegatable(
        caller_scopes, delegation.scopes_of_roles(group.roles)
    )
    await lockout.refuse_if_last(session)
    await session.commit()
    return group


async def list_members(
    session: AsyncSession, group_id: UUID, *, limit: int, offset: int
) -> tuple[list[User], int]:
    await get_group(session, group_id)

    total = await member_count(session, group_id)
    members = list(
        await session.scalars(
            select(User)
            .join(user_groups, user_groups.c.user_id == User.id)
            .where(user_groups.c.group_id == group_id)
            .order_by(User.email)
            .limit(limit)
            .offset(offset)
        )
    )
    return members, total


async def add_members(
    session: AsyncSession,
    group_id: UUID,
    user_ids: list[UUID],
    *,
    caller_scopes: set[str],
) -> None:
    """Membership confers whatever the group's roles carry — including on the
    caller, if they add themselves. Same rule as assigning a role directly."""
    group = await get_group(session, group_id)
    delegation.refuse_undelegatable(
        caller_scopes, delegation.scopes_of_roles(group.roles)
    )

    found = set(await session.scalars(select(User.id).where(User.id.in_(user_ids))))
    if len(found) != len(set(user_ids)):
        raise UnknownUsers(missing=[str(i) for i in set(user_ids) - found])

    existing = set(
        await session.scalars(
            select(user_groups.c.user_id).where(user_groups.c.group_id == group_id)
        )
    )
    new = found - existing
    if new:
        await session.execute(
            insert(user_groups),
            [{"user_id": user_id, "group_id": group_id} for user_id in new],
        )

    await session.commit()


async def remove_member(session: AsyncSession, group_id: UUID, user_id: UUID) -> None:
    await get_group(session, group_id)
    await session.execute(
        delete(user_groups).where(
            user_groups.c.group_id == group_id, user_groups.c.user_id == user_id
        )
    )
    await lockout.refuse_if_last(session)
    await session.commit()


async def delete_group(session: AsyncSession, group_id: UUID) -> None:
    """Removes the group, its role bindings, and its memberships — never its users."""
    group = await get_group(session, group_id)
    await session.delete(group)
    await lockout.refuse_if_last(session)
    await session.commit()
