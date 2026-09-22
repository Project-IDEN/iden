from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, update

from provider.core.auth import CurrentUserDep, require_scope
from provider.core.db import DBSessionDep
from provider.entity.connections.schemas import (
    ConnectionListResponse,
    ConnectionSummary,
)
from provider.shared.models import Client, ConsentGrant, RefreshToken

router = APIRouter(prefix="/entity/connections", tags=["entity: connections"])

READ = Depends(require_scope("entity:connections:read"))
REVOKE = Depends(require_scope("entity:connections:revoke"))


@router.get(
    "",
    response_model=ConnectionListResponse,
    summary="See which applications have access",
    description=(
        "The consent you have given, and to whom. Consent has been recorded "
        "since the first release; until now there was no way to look at it or "
        "take it back, which made it a one-way decision.\n\n"
        "First-party applications marked `skipConsent` never asked, so they do "
        "not appear here — there is no agreement to withdraw.\n\n"
        "**Required scope:** `entity:connections:read`"
    ),
    dependencies=[READ],
)
async def list_connections(
    user: CurrentUserDep, session: DBSessionDep
) -> ConnectionListResponse:
    rows = await session.execute(
        select(ConsentGrant, Client)
        .join(Client, Client.id == ConsentGrant.client_id)
        .where(ConsentGrant.user_id == user.id)
        .order_by(ConsentGrant.granted_at.desc())
    )

    return ConnectionListResponse(
        connections=[
            ConnectionSummary(
                client_id=client.client_id,
                name=client.name,
                scopes=sorted(grant.scopes),
                granted_at=grant.granted_at,
            )
            for grant, client in rows
        ]
    )


@router.delete(
    "/{client_id}",
    status_code=204,
    summary="Withdraw an application's access",
    description=(
        "Deletes the consent and revokes every refresh token that application "
        "holds for you, so it cannot renew what it already has. Access tokens "
        "already issued run to their expiry.\n\n"
        "The application may ask again — withdrawing consent is not a block "
        "list. It will have to, since the grant is gone.\n\n"
        "Returns `204` whether or not there was anything to withdraw.\n\n"
        "**Required scope:** `entity:connections:revoke`"
    ),
    dependencies=[REVOKE],
)
async def revoke_connection(
    client_id: str, user: CurrentUserDep, session: DBSessionDep
) -> Response:
    client = await session.scalar(select(Client).where(Client.client_id == client_id))
    if client is None:
        return Response(status_code=204)

    grant = await session.scalar(
        select(ConsentGrant).where(
            ConsentGrant.user_id == user.id, ConsentGrant.client_id == client.id
        )
    )
    if grant is not None:
        await session.delete(grant)

    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.client_id == client.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    return Response(status_code=204)
