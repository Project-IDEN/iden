from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from provider.admin.roles import service
from provider.admin.roles.schemas import (
    RoleCreate,
    RoleResponse,
    RoleScopeAssignment,
    RoleUpdate,
    ScopeSummary,
)
from provider.core.auth import AccessToken, require_scope
from provider.core.db import DBSessionDep
from provider.core.schemas import ErrorResponse, Page, PageMeta, PaginationDep

router = APIRouter(prefix="/admin/roles", tags=["admin: roles"])

READ = Depends(require_scope("admin:roles:read"))
WRITE = Depends(require_scope("admin:roles:write"))

# Taken as a parameter where the handler confers scopes: what may be granted
# is bounded by the caller's own token — see `admin.delegation`.
WriteToken = Annotated[AccessToken, Depends(require_scope("admin:roles:write"))]

DELEGATION_NOTE = (
    "\\n\\n**You cannot grant what you do not hold.** Any `admin:` or `biometric:` "
    "scope in what this would confer must already be in the caller's own token, "
    "or the request is refused with `403 cannot_delegate`."
)


def to_response(role) -> RoleResponse:
    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        scopes=[
            ScopeSummary(
                id=s.id,
                value=s.value,
                description=s.description,
                audience=s.api.audience,
            )
            for s in sorted(role.scopes, key=lambda s: s.value)
        ],
        created_at=role.created_at,
    )


@router.get(
    "",
    response_model=Page[RoleResponse],
    summary="List roles",
    description="**Required scope:** `admin:roles:read`",
    dependencies=[READ],
)
async def list_roles(session: DBSessionDep, page: PaginationDep) -> Page[RoleResponse]:
    roles, total = await service.list_roles(
        session, limit=page.limit, offset=page.offset
    )

    return Page[RoleResponse](
        items=[to_response(role) for role in roles],
        meta=PageMeta(total=total, limit=page.limit, offset=page.offset),
    )


@router.post(
    "",
    response_model=RoleResponse,
    status_code=201,
    summary="Create a role",
    description=(
        "A role is a named bundle of scopes — a job function. Roles are global: "
        "one role may bundle scopes from several APIs, because a real job rarely "
        "stops at one system's boundary.\n\n"
        "Assign it to users with `PUT /admin/users/{id}/roles`, or to a whole "
        "group with `PUT /admin/groups/{id}/roles`.\n\n"
        "**Required scope:** `admin:roles:write`"
    ),
    responses={
        404: {
            "model": ErrorResponse,
            "description": "One or more scope ids do not exist",
        },
        409: {"model": ErrorResponse, "description": "Name already taken"},
        403: {
            "model": ErrorResponse,
            "description": "Would confer a scope the caller does not hold",
        },
    },
)
async def create_role(
    body: RoleCreate, session: DBSessionDep, token: WriteToken
) -> RoleResponse:
    return to_response(
        await service.create_role(session, body, caller_scopes=token.scopes)
    )


@router.get(
    "/{role_id}",
    response_model=RoleResponse,
    summary="Read a role",
    description="**Required scope:** `admin:roles:read`",
    responses={404: {"model": ErrorResponse, "description": "No such role"}},
    dependencies=[READ],
)
async def read_role(role_id: UUID, session: DBSessionDep) -> RoleResponse:
    return to_response(await service.get_role(session, role_id))


@router.patch(
    "/{role_id}",
    response_model=RoleResponse,
    summary="Rename or describe a role",
    description=(
        "Scopes are set separately, via `PUT /admin/roles/{id}/scopes`.\n\n"
        "**Required scope:** `admin:roles:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such role"},
        409: {
            "model": ErrorResponse,
            "description": "Name taken, or the role is system-defined",
        },
    },
    dependencies=[WRITE],
)
async def update_role(
    role_id: UUID, body: RoleUpdate, session: DBSessionDep
) -> RoleResponse:
    return to_response(await service.update_role(session, role_id, body))


@router.put(
    "/{role_id}/scopes",
    response_model=RoleResponse,
    summary="Set a role's scopes",
    description=(
        "**Replaces the entire set.** Scopes not listed are removed from the "
        "role. Set semantics rather than add/remove pairs, so the request is "
        "idempotent and a dashboard can submit whatever the user selected "
        "without diffing first.\n\n"
        "Takes effect at the next token issuance, not immediately — outstanding "
        "access tokens live until they expire.\n\n"
        "**Required scope:** `admin:roles:write`" + DELEGATION_NOTE
    ),
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No such role, or unknown scope ids",
        },
        409: {
            "model": ErrorResponse,
            "description": "System role, or would leave no administrator",
        },
        403: {
            "model": ErrorResponse,
            "description": "Would confer a scope the caller does not hold",
        },
    },
)
async def set_role_scopes(
    role_id: UUID, body: RoleScopeAssignment, session: DBSessionDep, token: WriteToken
) -> RoleResponse:
    return to_response(
        await service.set_role_scopes(
            session, role_id, body.scope_ids, caller_scopes=token.scopes
        )
    )


@router.delete(
    "/{role_id}",
    status_code=204,
    summary="Delete a role",
    description=(
        "Refused with `409` while the role is still assigned to users or groups. "
        "Pass `force=true` to revoke it from all of them.\n\n"
        "**Required scope:** `admin:roles:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such role"},
        409: {
            "model": ErrorResponse,
            "description": (
                "System role, still assigned, or would leave no administrator"
            ),
        },
    },
    dependencies=[WRITE],
)
async def delete_role(
    role_id: UUID,
    session: DBSessionDep,
    force: bool = Query(
        False, description="Delete even though the role is still assigned."
    ),
) -> Response:
    await service.delete_role(session, role_id, force=force)
    return Response(status_code=204)
