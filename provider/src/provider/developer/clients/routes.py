from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from provider.core.auth import CurrentUserDep, require_scope
from provider.core.config import settings
from provider.core.db import DBSessionDep
from provider.core.schemas import ErrorResponse
from provider.developer.clients import service
from provider.developer.clients.schemas import (
    ApplicationCreate,
    ApplicationCreated,
    ApplicationList,
    ApplicationResponse,
    ApplicationUpdate,
    SecretRotated,
)
from provider.shared.models import Client

router = APIRouter(prefix="/developer/clients", tags=["developer: applications"])

READ = Depends(require_scope("developer:clients:read"))
WRITE = Depends(require_scope("developer:clients:write"))

# Repeated in every description because it is the question a developer arrives
# with, and /docs is where they arrive.
SELF_SERVICE_NOTE = (
    "Self-service registration. An application registered here always uses the "
    "authorization code flow with PKCE, always shows the consent screen, and "
    "can request the OpenID Connect scopes — `openid`, `profile`, `email`, "
    "`offline_access` — which is everything **Continue with IDEN** needs. Any "
    "scope beyond those, and the `client_credentials` grant, are an "
    "administrator's decision."
)


def to_response(client: Client) -> ApplicationResponse:
    return ApplicationResponse(
        id=client.id,
        client_id=client.client_id,
        name=client.name,
        # The column is written only through `ClientType`, and the schema
        # keeps the two spellings in the docs.
        client_type=cast(Literal["public", "confidential"], client.client_type),
        allowed_grants=client.allowed_grants,
        redirect_uris=client.redirect_uris,
        post_logout_redirect_uris=client.post_logout_redirect_uris,
        grantable_scopes=service.visible_scopes(client),
        has_secret=client.client_secret_hash is not None,
        created_at=client.created_at,
    )


@router.get(
    "",
    response_model=ApplicationList,
    summary="List the applications you registered",
    description=(
        f"{SELF_SERVICE_NOTE}\n\n"
        "Only your own applications. Anything registered by an administrator, "
        "or by anyone else, is not visible here.\n\n"
        "**Required scope:** `developer:clients:read`"
    ),
    dependencies=[READ],
)
async def list_applications(
    user: CurrentUserDep, session: DBSessionDep
) -> ApplicationList:
    clients = await service.list_applications(session, user)
    return ApplicationList(
        applications=[to_response(client) for client in clients],
        remaining=max(0, settings.iden_developer_max_clients - len(clients)),
    )


@router.post(
    "",
    response_model=ApplicationCreated,
    status_code=201,
    summary="Register an application",
    description=(
        f"{SELF_SERVICE_NOTE}\n\n"
        "The `clientId` is generated — you do not choose it. A confidential "
        "application's secret is returned **once**, in this response, and is "
        "argon2-hashed on the way in; it cannot be recovered, only rotated.\n\n"
        "**Required scope:** `developer:clients:write`"
    ),
    responses={
        409: {
            "model": ErrorResponse,
            "description": "This account has registered its maximum number of applications",
        },
        422: {"model": ErrorResponse, "description": "A redirect URI is not allowed"},
    },
    dependencies=[WRITE],
)
async def create_application(
    body: ApplicationCreate, user: CurrentUserDep, session: DBSessionDep
) -> ApplicationCreated:
    client, secret = await service.create_application(session, user, body)
    return ApplicationCreated(**to_response(client).model_dump(), client_secret=secret)


@router.get(
    "/{application_id}",
    response_model=ApplicationResponse,
    summary="Read one of your applications",
    description="**Required scope:** `developer:clients:read`",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "No such application of yours",
        }
    },
    dependencies=[READ],
)
async def read_application(
    application_id: UUID, user: CurrentUserDep, session: DBSessionDep
) -> ApplicationResponse:
    return to_response(await service.get_application(session, user, application_id))


@router.patch(
    "/{application_id}",
    response_model=ApplicationResponse,
    summary="Update one of your applications",
    description=(
        "`clientId` and `clientType` are immutable — both are baked into issued "
        "tokens and into however the application is already deployed. Register "
        "a new one to change either.\n\n"
        "**Required scope:** `developer:clients:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such application of yours"},
        422: {"model": ErrorResponse, "description": "A redirect URI is not allowed"},
    },
    dependencies=[WRITE],
)
async def update_application(
    application_id: UUID,
    body: ApplicationUpdate,
    user: CurrentUserDep,
    session: DBSessionDep,
) -> ApplicationResponse:
    client = await service.update_application(session, user, application_id, body)
    return to_response(client)


@router.post(
    "/{application_id}/rotate-secret",
    response_model=SecretRotated,
    summary="Rotate an application's secret",
    description=(
        "Issues a new secret and returns it **once**. The previous secret stops "
        "working immediately, so deploy the new one before rotating.\n\n"
        "**Required scope:** `developer:clients:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such application of yours"},
        422: {
            "model": ErrorResponse,
            "description": "Public applications have no secret",
        },
    },
    dependencies=[WRITE],
)
async def rotate_secret(
    application_id: UUID, user: CurrentUserDep, session: DBSessionDep
) -> SecretRotated:
    secret = await service.rotate_secret(session, user, application_id)
    return SecretRotated(client_secret=secret)


@router.delete(
    "/{application_id}",
    status_code=204,
    summary="Delete one of your applications",
    description=(
        "Every token and consent grant belonging to the application goes with "
        "it, and everyone signed in through it is signed out.\n\n"
        "**Required scope:** `developer:clients:write`"
    ),
    responses={
        404: {"model": ErrorResponse, "description": "No such application of yours"}
    },
    dependencies=[WRITE],
)
async def delete_application(
    application_id: UUID, user: CurrentUserDep, session: DBSessionDep
) -> Response:
    await service.delete_application(session, user, application_id)
    return Response(status_code=204)
