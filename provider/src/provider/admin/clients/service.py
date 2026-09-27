from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.admin.clients.errors import (
    ClientIdTaken,
    ClientNotFound,
    PublicClientHasNoSecret,
    RedirectUriRequired,
    RestrictedScopeOnOwnedClient,
    SystemClientImmutable,
    UnknownScopes,
)
from provider.admin.clients.schemas import ClientCreate, ClientUpdate
from provider.core.security import generate_token, hash_secret
from provider.shared.enums import ClientType, GrantType
from provider.shared.models import Client, ClientScope, Scope
from provider.shared.scopes import RESTRICTED_PREFIXES


async def _validate_scope_ids(session: AsyncSession, scope_ids: set[UUID]) -> None:
    if not scope_ids:
        return

    found = set(await session.scalars(select(Scope.id).where(Scope.id.in_(scope_ids))))
    if found != scope_ids:
        raise UnknownScopes(missing=[str(i) for i in scope_ids - found])


async def _apply_scopes(
    session: AsyncSession, client: Client, grantable: list[UUID], granted: list[UUID]
) -> None:
    wanted = set(grantable) | set(granted)
    await _validate_scope_ids(session, wanted)

    # A developer can repoint their own application's redirect URIs, so a
    # restricted scope on it would let them collect administrators' tokens.
    if client.owner_user_id is not None:
        values = await session.scalars(
            select(Scope.value).where(Scope.id.in_(wanted), Scope.is_system)
        )
        if any(value.split(":")[0] in RESTRICTED_PREFIXES for value in values):
            raise RestrictedScopeOnOwnedClient

    existing = {
        link.scope_id: link
        for link in await session.scalars(
            select(ClientScope).where(ClientScope.client_id == client.id)
        )
    }

    for scope_id in wanted:
        link = existing.get(scope_id) or ClientScope(
            client_id=client.id, scope_id=scope_id
        )
        link.grantable = scope_id in grantable
        link.granted = scope_id in granted
        session.add(link)

    for scope_id, link in existing.items():
        if scope_id not in wanted:
            await session.delete(link)


async def list_clients(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[Client], int]:
    total = await session.scalar(select(func.count(Client.id))) or 0
    clients = list(
        await session.scalars(
            select(Client).order_by(Client.client_id).limit(limit).offset(offset)
        )
    )
    return clients, total


async def get_client(session: AsyncSession, client_id: UUID) -> Client:
    client = await session.get(Client, client_id)
    if client is None:
        raise ClientNotFound
    return client


async def create_client(
    session: AsyncSession, data: ClientCreate
) -> tuple[Client, str | None]:
    if await session.scalar(select(Client).where(Client.client_id == data.client_id)):
        raise ClientIdTaken

    if GrantType.AUTHORIZATION_CODE in data.allowed_grants and not data.redirect_uris:
        raise RedirectUriRequired

    secret = generate_token(32) if data.client_type == ClientType.CONFIDENTIAL else None

    client = Client(
        client_id=data.client_id,
        name=data.name,
        client_type=data.client_type,
        client_secret_hash=hash_secret(secret) if secret else None,
        allowed_grants=data.allowed_grants,
        redirect_uris=data.redirect_uris,
        post_logout_redirect_uris=data.post_logout_redirect_uris,
        backchannel_logout_uri=data.backchannel_logout_uri,
        backchannel_logout_session_required=data.backchannel_logout_session_required,
        skip_consent=data.skip_consent,
    )
    session.add(client)
    await session.flush()

    await _apply_scopes(
        session, client, data.grantable_scope_ids, data.granted_scope_ids
    )
    await session.commit()
    await session.refresh(client)
    return client, secret


async def update_client(
    session: AsyncSession, client_id: UUID, data: ClientUpdate
) -> Client:
    client = await get_client(session, client_id)

    for field in (
        "name",
        "allowed_grants",
        "redirect_uris",
        "post_logout_redirect_uris",
        "backchannel_logout_uri",
        "backchannel_logout_session_required",
        "skip_consent",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(client, field, value)

    if (
        GrantType.AUTHORIZATION_CODE in client.allowed_grants
        and not client.redirect_uris
    ):
        raise RedirectUriRequired

    await session.commit()
    return client


async def set_client_scopes(
    session: AsyncSession, client_id: UUID, grantable: list[UUID], granted: list[UUID]
) -> Client:
    client = await get_client(session, client_id)
    await _apply_scopes(session, client, grantable, granted)
    await session.commit()
    await session.refresh(client)
    return client


async def rotate_secret(session: AsyncSession, client_id: UUID) -> str:
    client = await get_client(session, client_id)
    if client.client_type != ClientType.CONFIDENTIAL:
        raise PublicClientHasNoSecret

    secret = generate_token(32)
    client.client_secret_hash = hash_secret(secret)
    await session.commit()
    return secret


async def delete_client(session: AsyncSession, client_id: UUID) -> None:
    client = await get_client(session, client_id)
    if client.is_system:
        raise SystemClientImmutable

    await session.delete(client)
    await session.commit()
