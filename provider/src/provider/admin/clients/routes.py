from uuid import UUID

from fastapi import APIRouter, Depends, Response

from provider.admin.clients import service
from provider.admin.clients.schemas import (
    ClientCreate,
    ClientCreated,
    ClientResponse,
    ClientScopeAssignment,
    ClientUpdate,
    ScopeSummary,
    SecretRotated,
)
from provider.core.auth import require_scope
from provider.core.db import DBSessionDep
from provider.core.schemas import ErrorResponse, Page, PageMeta, PaginationDep

router = APIRouter(prefix="/admin/clients", tags=["admin: clients"])

READ = Depends(require_scope("admin:clients:read"))
WRITE = Depends(require_scope("admin:clients:write"))


def to_response(client) -> ClientResponse:
    return ClientResponse(
        id=client.id,
        client_id=client.client_id,
        name=client.name,
        client_type=client.client_type,
        allowed_grants=client.allowed_grants,
        redirect_uris=client.redirect_uris,
        post_logout_redirect_uris=client.post_logout_redirect_uris,
        backchannel_logout_uri=client.backchannel_logout_uri,
        backchannel_logout_session_required=client.backchannel_logout_session_required,
        skip_consent=client.skip_consent,
        is_system=client.is_system,
        owner_user_id=client.owner_user_id,
        grantable_scopes=[
            ScopeSummary(id=link.scope.id, value=link.scope.value)
            for link in sorted(client.scopes, key=lambda link: link.scope.value)
            if link.grantable
        ],
        granted_scopes=[
            ScopeSummary(id=link.scope.id, value=link.scope.value)
            for link in sorted(client.scopes, key=lambda link: link.scope.value)
            if link.granted
        ],
        created_at=client.created_at,
    )


@router.get(
    "",
    response_model=Page[ClientResponse],
    summary="List OAuth clients",
    description=(
        "Secrets are never returned — only their presence is implied by "
        "`clientType`.\n\n"
        "**Required scope:** `admin:clients:read`"
    ),
    dependencies=[READ],
)
async def list_clients(
    session: DBSessionDep, page: PaginationDep
) -> Page[ClientResponse]:
    clients, total = await service.list_clients(
        session, limit=page.limit, offset=page.offset
    )

    return Page[ClientResponse](
        items=[to_response(client) for client in clients],
        meta=PageMeta(total=total, limit=page.limit, offset=page.offset),
    )


@router.post(
    "",
    response_model=ClientCreated,
    status_code=201,
    summary="Register an OAuth client",
    description=(
        "Registers an application that may request tokens.\n\n"
        "A confidential client's secret is returned **once**, in this response. "
        "It is argon2-hashed on the way in and cannot be recovered — only "
        "rotated. Public clients get no secret and must use PKCE.\n\n"
        "`grantableScopeIds` are what the client may request for a user; "
        "`grantedScopeIds` are what it holds itself for `client_credentials`. "
        "The two are independent.\n\n"
        "**Required scope:** `admin:clients:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Unknown scope ids"},
        409: {"model": ErrorResponse, "description": "client_id already taken"},
        422: {
            "model": ErrorResponse,
            "description": "Authorization code grant without a redirect URI",
        },
    },
    dependencies=[WRITE],
)
async def create_client(body: ClientCreate, session: DBSessionDep) -> ClientCreated:
    client, secret = await service.create_client(session, body)
    return ClientCreated(**to_response(client).model_dump(), client_secret=secret)


@router.get(
    "/{client_id}",
    response_model=ClientResponse,
    summary="Read an OAuth client",
    description="**Required scope:** `admin:clients:read`",
    responses={404: {"model": ErrorResponse, "description": "No such client"}},
    dependencies=[READ],
)
async def read_client(client_id: UUID, session: DBSessionDep) -> ClientResponse:
    return to_response(await service.get_client(session, client_id))


@router.patch(
    "/{client_id}",
    response_model=ClientResponse,
    summary="Update an OAuth client",
    description=(
        "`clientId` and `clientType` are immutable — both are baked into issued "
        "tokens and into however the application is configured.\n\n"
        "**Required scope:** `admin:clients:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such client"},
        422: {
            "model": ErrorResponse,
            "description": "Authorization code grant without a redirect URI",
        },
    },
    dependencies=[WRITE],
)
async def update_client(
    client_id: UUID, body: ClientUpdate, session: DBSessionDep
) -> ClientResponse:
    return to_response(await service.update_client(session, client_id, body))


@router.put(
    "/{client_id}/scopes",
    response_model=ClientResponse,
    summary="Set a client's scopes",
    description=(
        "**Replaces both sets.** A scope listed in neither is removed from the "
        "client entirely.\n\n"
        "**Required scope:** `admin:clients:write`"
    ),
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No such client, or unknown scope ids",
        }
    },
    dependencies=[WRITE],
)
async def set_client_scopes(
    client_id: UUID, body: ClientScopeAssignment, session: DBSessionDep
) -> ClientResponse:
    client = await service.set_client_scopes(
        session, client_id, body.grantable_scope_ids, body.granted_scope_ids
    )
    return to_response(client)


@router.post(
    "/{client_id}/rotate-secret",
    response_model=SecretRotated,
    summary="Rotate a client secret",
    description=(
        "Issues a new secret and returns it **once**. The previous secret stops "
        "working immediately, so deploy the new one before rotating.\n\n"
        "**Required scope:** `admin:clients:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such client"},
        422: {"model": ErrorResponse, "description": "Public clients have no secret"},
    },
    dependencies=[WRITE],
)
async def rotate_secret(client_id: UUID, session: DBSessionDep) -> SecretRotated:
    return SecretRotated(client_secret=await service.rotate_secret(session, client_id))


@router.delete(
    "/{client_id}",
    status_code=204,
    summary="Delete an OAuth client",
    description=(
        "Every token and consent grant belonging to the client goes with it.\n\n"
        "**Required scope:** `admin:clients:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such client"},
        409: {"model": ErrorResponse, "description": "Bootstrap client"},
    },
    dependencies=[WRITE],
)
async def delete_client(client_id: UUID, session: DBSessionDep) -> Response:
    await service.delete_client(session, client_id)
    return Response(status_code=204)
