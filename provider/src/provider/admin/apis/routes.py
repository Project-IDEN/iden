from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from provider.admin.apis import service
from provider.admin.apis.schemas import ApiCreate, ApiResponse, ApiUpdate
from provider.core.auth import require_scope
from provider.core.db import DBSessionDep
from provider.core.schemas import ErrorResponse, Page, PageMeta, PaginationDep
from provider.shared.models import ResourceApi

router = APIRouter(prefix="/admin/apis", tags=["admin: apis"])

READ = Depends(require_scope("admin:apis:read"))
WRITE = Depends(require_scope("admin:apis:write"))


def to_response(api: ResourceApi, scope_count: int) -> ApiResponse:
    return ApiResponse(
        id=api.id,
        name=api.name,
        audience=api.audience,
        description=api.description,
        is_system=api.is_system,
        scope_count=scope_count,
        created_at=api.created_at,
    )


@router.get(
    "",
    response_model=Page[ApiResponse],
    summary="List resource APIs",
    description=(
        "Every backend that trusts IDEN, including IDEN's own `admin` and "
        "`entity` APIs.\n\n"
        "**Required scope:** `admin:apis:read`"
    ),
    dependencies=[READ],
)
async def list_apis(session: DBSessionDep, page: PaginationDep) -> Page[ApiResponse]:
    apis, counts, total = await service.list_apis(
        session, limit=page.limit, offset=page.offset
    )

    return Page[ApiResponse](
        items=[to_response(api, counts.get(api.id, 0)) for api in apis],
        meta=PageMeta(total=total, limit=page.limit, offset=page.offset),
    )


@router.post(
    "",
    response_model=ApiResponse,
    status_code=201,
    summary="Register a resource API",
    description=(
        "Registers a backend that will accept IDEN's access tokens, and fixes "
        "the `aud` value its tokens will carry.\n\n"
        "Scopes are then defined under it via `POST /admin/apis/{id}/scopes`.\n\n"
        "**Required scope:** `admin:apis:write`"
    ),
    responses={
        409: {"model": ErrorResponse, "description": "Name or audience already in use"}
    },
    dependencies=[WRITE],
)
async def create_api(body: ApiCreate, session: DBSessionDep) -> ApiResponse:
    api = await service.create_api(session, body)
    return to_response(api, 0)


@router.get(
    "/{api_id}",
    response_model=ApiResponse,
    summary="Read a resource API",
    description="**Required scope:** `admin:apis:read`",
    responses={404: {"model": ErrorResponse, "description": "No such API"}},
    dependencies=[READ],
)
async def read_api(api_id: UUID, session: DBSessionDep) -> ApiResponse:
    api = await service.get_api(session, api_id)
    return to_response(api, await service.count_scopes(session, api_id))


@router.patch(
    "/{api_id}",
    response_model=ApiResponse,
    summary="Update a resource API",
    description=(
        "Only `name` and `description` may change. **The audience is immutable**: "
        "access tokens already issued carry the old value, and resource servers "
        "validate against it, so changing it would silently break every live "
        "token. Register a new API instead.\n\n"
        "**Required scope:** `admin:apis:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such API"},
        409: {
            "model": ErrorResponse,
            "description": "Name taken, or the API is system-defined",
        },
    },
    dependencies=[WRITE],
)
async def update_api(
    api_id: UUID, body: ApiUpdate, session: DBSessionDep
) -> ApiResponse:
    api = await service.update_api(session, api_id, body)
    return to_response(api, await service.count_scopes(session, api_id))


@router.delete(
    "/{api_id}",
    status_code=204,
    summary="Delete a resource API",
    description=(
        "Deletes the API and every scope defined under it.\n\n"
        "Refused with `409` when those scopes are still granted to a role, user, "
        "or client, because deleting would silently strip permissions from "
        "whoever held them. Pass `force=true` once that is the intent.\n\n"
        "**Required scope:** `admin:apis:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such API"},
        409: {
            "model": ErrorResponse,
            "description": "System API, or its scopes are still in use",
        },
    },
    dependencies=[WRITE],
)
async def delete_api(
    api_id: UUID,
    session: DBSessionDep,
    force: bool = Query(
        False, description="Delete even though the scopes are still granted."
    ),
) -> Response:
    await service.delete_api(session, api_id, force=force)
    return Response(status_code=204)
