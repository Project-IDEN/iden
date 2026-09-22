from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.admin import delegation, lockout
from provider.admin.roles.errors import (
    RoleInUse,
    RoleNameTaken,
    RoleNotFound,
    SystemRoleImmutable,
    UnknownScopes,
)
from provider.admin.roles.schemas import RoleCreate, RoleUpdate
from provider.shared.models import Role, Scope, group_roles, user_roles


async def resolve_scopes(session: AsyncSession, scope_ids: list[UUID]) -> list[Scope]:
    """Load scopes by id, refusing the whole request if any is unknown.

    Partial application would leave the caller believing a role holds a scope it
    does not.
    """
    if not scope_ids:
        return []

    scopes = list(await session.scalars(select(Scope).where(Scope.id.in_(scope_ids))))
    if len(scopes) != len(set(scope_ids)):
        found = {scope.id for scope in scopes}
        raise UnknownScopes(missing=[str(i) for i in set(scope_ids) - found])

    return scopes


async def list_roles(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[Role], int]:
    total = await session.scalar(select(func.count(Role.id))) or 0
    roles = list(
        await session.scalars(
            select(Role).order_by(Role.name).limit(limit).offset(offset)
        )
    )
    return roles, total


async def get_role(session: AsyncSession, role_id: UUID) -> Role:
    role = await session.get(Role, role_id)
    if role is None:
        raise RoleNotFound
    return role


async def create_role(
    session: AsyncSession, data: RoleCreate, *, caller_scopes: set[str]
) -> Role:
    if await session.scalar(select(Role).where(Role.name == data.name)):
        raise RoleNameTaken

    role = Role(name=data.name, description=data.description)
    role.scopes = await resolve_scopes(session, data.scope_ids)
    delegation.refuse_undelegatable(caller_scopes, role.scopes)
    session.add(role)
    await session.commit()
    await session.refresh(role)
    return role


async def update_role(session: AsyncSession, role_id: UUID, data: RoleUpdate) -> Role:
    role = await get_role(session, role_id)
    if role.is_system:
        raise SystemRoleImmutable

    if data.name is not None and data.name != role.name:
        if await session.scalar(select(Role).where(Role.name == data.name)):
            raise RoleNameTaken
        role.name = data.name

    if data.description is not None:
        role.description = data.description

    await session.commit()
    return role


async def set_role_scopes(
    session: AsyncSession,
    role_id: UUID,
    scope_ids: list[UUID],
    *,
    caller_scopes: set[str],
) -> Role:
    """Replace the scope set wholesale — a set operation, so it is idempotent.

    Editing what a role means confers on everybody already holding it, which is
    why the delegation rule applies here and not only where a role is assigned.
    Without it, adding `admin:grants:write` to a role you are already in is a
    one-request promotion.
    """
    role = await get_role(session, role_id)
    if role.is_system:
        raise SystemRoleImmutable

    role.scopes = await resolve_scopes(session, scope_ids)
    delegation.refuse_undelegatable(caller_scopes, role.scopes)
    await lockout.refuse_if_last(session)
    await session.commit()
    return role


async def role_in_use(session: AsyncSession, role_id: UUID) -> bool:
    return bool(
        await session.scalar(
            select(func.count())
            .select_from(user_roles)
            .where(user_roles.c.role_id == role_id)
        )
        or await session.scalar(
            select(func.count())
            .select_from(group_roles)
            .where(group_roles.c.role_id == role_id)
        )
    )


async def delete_role(session: AsyncSession, role_id: UUID, *, force: bool) -> None:
    role = await get_role(session, role_id)
    if role.is_system:
        raise SystemRoleImmutable

    if not force and await role_in_use(session, role_id):
        raise RoleInUse

    await session.delete(role)
    await lockout.refuse_if_last(session)
    await session.commit()
