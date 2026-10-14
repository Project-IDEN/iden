from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from provider.admin.scopes import service
from provider.admin.scopes.schemas import ScopeCreate, ScopeResponse, ScopeUpdate
from provider.core.auth import require_scope
from provider.core.db import DBSessionDep
from provider.core.schemas import ErrorResponse, Page, PageMeta, PaginationDep
from provider.shared.models import Scope

router = APIRouter(tags=["admin: scopes"])

READ = Depends(require_scope("admin:scopes:read"))
WRITE = Depends(require_scope("admin:scopes:write"))


def to_response(scope: Scope) -> ScopeResponse:
    return ScopeResponse(
        id=scope.id,
        api_id=scope.api_id,
        api_name=scope.api.name,
        audience=scope.api.audience,
        value=scope.value,
        description=scope.description,
        is_system=scope.is_system,
        created_at=scope.created_at,
    )


@router.get(
    "/admin/apis/{api_id}/scopes",
    response_model=Page[ScopeResponse],
    summary="List an API's scopes",
    description="The permissions this API defines.\n\n**Required scope:** `admin:scopes:read`",
    responses={404: {"model": ErrorResponse, "description": "No such API"}},
    dependencies=[READ],
)
async def list_scopes(
    api_id: UUID, session: DBSessionDep, page: PaginationDep
) -> Page[ScopeResponse]:
    scopes, total = await service.list_scopes(
        session, api_id, limit=page.limit, offset=page.offset
    )

    return Page[ScopeResponse](
        items=[to_response(scope) for scope in scopes],
        meta=PageMeta(total=total, limit=page.limit, offset=page.offset),
    )


@router.post(
    "/admin/apis/{api_id}/scopes",
    response_model=ScopeResponse,
    status_code=201,
    summary="Define a scope",
    description=(
        "Defines a new permission under this API. It can then be bundled into a "
        "role, granted directly to a user, or allowed to a client.\n\n"
        "Scope values are **globally unique**: a token carries them as bare "
        "strings and the audience is resolved from the value, so two APIs cannot "
        "share one. Namespacing by API — `attendance:records:read` — keeps them "
        "distinct.\n\n"
        "**Required scope:** `admin:scopes:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such API"},
        409: {"model": ErrorResponse, "description": "Scope value already defined"},
    },
    dependencies=[WRITE],
)
async def create_scope(
    api_id: UUID, body: ScopeCreate, session: DBSessionDep
) -> ScopeResponse:
    scope = await service.create_scope(session, api_id, body)
    return to_response(scope)


@router.get(
    "/admin/scopes/{scope_id}",
    response_model=ScopeResponse,
    summary="Read a scope",
    description="**Required scope:** `admin:scopes:read`",
    responses={404: {"model": ErrorResponse, "description": "No such scope"}},
    dependencies=[READ],
)
async def read_scope(scope_id: UUID, session: DBSessionDep) -> ScopeResponse:
    return to_response(await service.get_scope(session, scope_id))


@router.patch(
    "/admin/scopes/{scope_id}",
    response_model=ScopeResponse,
    summary="Update a scope's description",
    description=(
        "Only the description may change. **The value is immutable**: it is "
        "already embedded in issued tokens and in every role that bundles it, so "
        "renaming would revoke access without appearing to. Define a new scope "
        "and retire this one.\n\n"
        "**Required scope:** `admin:scopes:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such scope"},
        409: {"model": ErrorResponse, "description": "System scope"},
    },
    dependencies=[WRITE],
)
async def update_scope(
    scope_id: UUID, body: ScopeUpdate, session: DBSessionDep
) -> ScopeResponse:
    return to_response(await service.update_scope(session, scope_id, body))


@router.delete(
    "/admin/scopes/{scope_id}",
    status_code=204,
    summary="Delete a scope",
    description=(
        "Refused with `409` while the scope is still granted to a role, user, or "
        "client — deleting it revokes access from everyone holding it. Pass "
        "`force=true` once that is the intent.\n\n"
        "**Required scope:** `admin:scopes:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such scope"},
        409: {"model": ErrorResponse, "description": "System scope, or still granted"},
    },
    dependencies=[WRITE],
)
async def delete_scope(
    scope_id: UUID,
    session: DBSessionDep,
    force: bool = Query(
        False, description="Delete even though the scope is still granted."
    ),
) -> Response:
    await service.delete_scope(session, scope_id, force=force)
    return Response(status_code=204)
