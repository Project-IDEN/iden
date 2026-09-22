from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from provider.admin.groups import service
from provider.admin.groups.schemas import (
    GroupCreate,
    GroupResponse,
    GroupRoleAssignment,
    GroupUpdate,
    MemberAssignment,
    MemberSummary,
    RoleSummary,
)
from provider.core.auth import AccessToken, require_scope
from provider.core.db import DBSessionDep
from provider.core.schemas import ErrorResponse, Page, PageMeta, PaginationDep

router = APIRouter(prefix="/admin/groups", tags=["admin: groups"])

READ = Depends(require_scope("admin:groups:read"))
WRITE = Depends(require_scope("admin:groups:write"))

# Taken as a parameter where the handler confers scopes: a group's roles reach
# every member, so assigning them is granting — see `admin.delegation`.
WriteToken = Annotated[AccessToken, Depends(require_scope("admin:groups:write"))]

DELEGATION_NOTE = (
    "\\n\\n**You cannot grant what you do not hold.** Any `admin:` or `biometric:` "
    "scope in what this would confer must already be in the caller's own token, "
    "or the request is refused with `403 cannot_delegate`."
)


def to_response(group, members: int) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        roles=[
            RoleSummary(id=r.id, name=r.name, description=r.description)
            for r in sorted(group.roles, key=lambda r: r.name)
        ],
        member_count=members,
        created_at=group.created_at,
    )


@router.get(
    "",
    response_model=Page[GroupResponse],
    summary="List groups",
    description="**Required scope:** `admin:groups:read`",
    dependencies=[READ],
)
async def list_groups(
    session: DBSessionDep, page: PaginationDep
) -> Page[GroupResponse]:
    groups, total = await service.list_groups(
        session, limit=page.limit, offset=page.offset
    )

    counts = await service.member_counts(session, [group.id for group in groups])

    return Page[GroupResponse](
        items=[to_response(group, counts.get(group.id, 0)) for group in groups],
        meta=PageMeta(total=total, limit=page.limit, offset=page.offset),
    )


@router.post(
    "",
    response_model=GroupResponse,
    status_code=201,
    summary="Create a group",
    description=(
        "Groups model the organization — departments, teams, cohorts. Membership "
        "is flat: groups do not nest, because recursive resolution is hard to "
        "explain and harder to audit.\n\n"
        "**Required scope:** `admin:groups:write`"
    ),
    responses={409: {"model": ErrorResponse, "description": "Name already taken"}},
    dependencies=[WRITE],
)
async def create_group(body: GroupCreate, session: DBSessionDep) -> GroupResponse:
    return to_response(await service.create_group(session, body), 0)


@router.get(
    "/{group_id}",
    response_model=GroupResponse,
    summary="Read a group",
    description="**Required scope:** `admin:groups:read`",
    responses={404: {"model": ErrorResponse, "description": "No such group"}},
    dependencies=[READ],
)
async def read_group(group_id: UUID, session: DBSessionDep) -> GroupResponse:
    group = await service.get_group(session, group_id)
    return to_response(group, await service.member_count(session, group_id))


@router.patch(
    "/{group_id}",
    response_model=GroupResponse,
    summary="Rename or describe a group",
    description="**Required scope:** `admin:groups:write`",
    responses={
        404: {"model": ErrorResponse, "description": "No such group"},
        409: {"model": ErrorResponse, "description": "Name already taken"},
    },
    dependencies=[WRITE],
)
async def update_group(
    group_id: UUID, body: GroupUpdate, session: DBSessionDep
) -> GroupResponse:
    group = await service.update_group(session, group_id, body)
    return to_response(group, await service.member_count(session, group_id))


@router.put(
    "/{group_id}/roles",
    response_model=GroupResponse,
    summary="Set a group's roles",
    description=(
        "**Replaces the entire set.** Every member inherits these roles, which is "
        "how one change reaches a whole department.\n\n"
        "Refused with `409` when the group is the last source of "
        "`admin:grants:write` for an active user.\n\n"
        "**Required scope:** `admin:groups:write`" + DELEGATION_NOTE
    ),
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No such group, or unknown role ids",
        },
        409: {"model": ErrorResponse, "description": "Would leave no administrator"},
        403: {
            "model": ErrorResponse,
            "description": "Would confer a scope the caller does not hold",
        },
    },
)
async def set_group_roles(
    group_id: UUID, body: GroupRoleAssignment, session: DBSessionDep, token: WriteToken
) -> GroupResponse:
    group = await service.set_group_roles(
        session, group_id, body.role_ids, caller_scopes=token.scopes
    )
    return to_response(group, await service.member_count(session, group_id))


@router.get(
    "/{group_id}/members",
    response_model=Page[MemberSummary],
    summary="List a group's members",
    description="**Required scope:** `admin:groups:read`",
    responses={404: {"model": ErrorResponse, "description": "No such group"}},
    dependencies=[READ],
)
async def list_members(
    group_id: UUID, session: DBSessionDep, page: PaginationDep
) -> Page[MemberSummary]:
    members, total = await service.list_members(
        session, group_id, limit=page.limit, offset=page.offset
    )

    return Page[MemberSummary](
        items=[MemberSummary.model_validate(m) for m in members],
        meta=PageMeta(total=total, limit=page.limit, offset=page.offset),
    )


@router.post(
    "/{group_id}/members",
    status_code=204,
    summary="Add members",
    description=(
        "Idempotent — users already in the group are ignored rather than "
        "rejected.\n\n"
        "**Required scope:** `admin:groups:write`"
    ),
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No such group, or unknown user ids",
        },
        403: {
            "model": ErrorResponse,
            "description": "Would confer a scope the caller does not hold",
        },
    },
)
async def add_members(
    group_id: UUID, body: MemberAssignment, session: DBSessionDep, token: WriteToken
) -> Response:
    await service.add_members(
        session, group_id, body.user_ids, caller_scopes=token.scopes
    )
    return Response(status_code=204)


@router.delete(
    "/{group_id}/members/{user_id}",
    status_code=204,
    summary="Remove a member",
    description=(
        "Removes the membership only — the user is untouched.\n\n"
        "**Required scope:** `admin:groups:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such group"},
        409: {"model": ErrorResponse, "description": "Would leave no administrator"},
    },
    dependencies=[WRITE],
)
async def remove_member(
    group_id: UUID, user_id: UUID, session: DBSessionDep
) -> Response:
    await service.remove_member(session, group_id, user_id)
    return Response(status_code=204)


@router.delete(
    "/{group_id}",
    status_code=204,
    summary="Delete a group",
    description=(
        "Removes the group, its role bindings, and its memberships. **Users are "
        "not deleted** — they simply lose whatever the group granted them.\n\n"
        "**Required scope:** `admin:groups:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such group"},
        409: {"model": ErrorResponse, "description": "Would leave no administrator"},
    },
    dependencies=[WRITE],
)
async def delete_group(group_id: UUID, session: DBSessionDep) -> Response:
    await service.delete_group(session, group_id)
    return Response(status_code=204)
