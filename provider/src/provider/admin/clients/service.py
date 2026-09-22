from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.admin import delegation
from provider.admin.clients.errors import (
    ClientIdTaken,
    ClientNotFound,
    PublicClientHasNoSecret,
    RedirectUriRequired,
    SystemClientImmutable,
    UnknownScopes,
)
from provider.admin.clients.schemas import ClientCreate, ClientUpdate
from provider.core.security import generate_token, hash_secret
from provider.shared.enums import ClientType, GrantType
from provider.shared.models import Client, ClientScope, Scope


async def _validate_scope_ids(session: AsyncSession, scope_ids: set[UUID]) -> None:
    if not scope_ids:
        return

    found = set(await session.scalars(select(Scope.id).where(Scope.id.in_(scope_ids))))
    if found != scope_ids:
        raise UnknownScopes(missing=[str(i) for i in scope_ids - found])


async def _apply_scopes(
    session: AsyncSession,
    client: Client,
    grantable: list[UUID],
    granted: list[UUID],
    *,
    caller_scopes: set[str],
) -> None:
    """Attach scopes to a client, subject to the same delegation rule as a person.

    A client is the other way to obtain a token, and `granted` is the dangerous
    half: a confidential client holding `admin:grants:write` in its own right is
    a `client_credentials` request away from being an administrator, with a
    secret the registrant was shown once. Without this, `admin:clients:write`
    was a complete escalation path of its own, independent of anything a person
    was allowed to be granted.
    """
    await _validate_scope_ids(session, set(grantable) | set(granted))

    existing = {
        link.scope_id: link
        for link in await session.scalars(
            select(ClientScope).where(ClientScope.client_id == client.id)
        )
    }

    wanted = set(grantable) | set(granted)
    # What is *newly conferred*, which is not the same as what is newly attached:
    # a scope already present as `grantable` and promoted to `granted` gains the
    # client the right to mint it for itself, and comparing only the id sets
    # missed exactly that. A capability the client did not have before counts,
    # however the row got there.
    conferred = {
        scope_id
        for scope_id in wanted
        if (link := existing.get(scope_id)) is None
        or (scope_id in granted and not link.granted)
        or (scope_id in grantable and not link.grantable)
    }
    added = await session.scalars(select(Scope).where(Scope.id.in_(conferred)))
    delegation.refuse_undelegatable(caller_scopes, list(added))
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


async def get_client_to_modify(
    session: AsyncSession, client_id: UUID, caller_scopes: set[str]
) -> Client:
    """The client a write is about, once the caller is allowed to act on it.

    A client holding a scope outright is dormant only until somebody adds the
    `client_credentials` grant and rotates its secret — both `admin:clients:write`,
    and neither of them a scope assignment. So the gate is on touching the client
    at all, not on the scope endpoint alone.
    """
    client = await get_client(session, client_id)
    delegation.refuse_if_client_outranks(caller_scopes, client)
    return client


async def create_client(
    session: AsyncSession, data: ClientCreate, *, caller_scopes: set[str]
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
        session,
        client,
        data.grantable_scope_ids,
        data.granted_scope_ids,
        caller_scopes=caller_scopes,
    )
    await session.commit()
    await session.refresh(client)
    return client, secret


async def update_client(
    session: AsyncSession,
    client_id: UUID,
    data: ClientUpdate,
    *,
    caller_scopes: set[str],
) -> Client:
    client = await get_client_to_modify(session, client_id, caller_scopes)

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
    session: AsyncSession,
    client_id: UUID,
    grantable: list[UUID],
    granted: list[UUID],
    *,
    caller_scopes: set[str],
) -> Client:
    client = await get_client_to_modify(session, client_id, caller_scopes)
    await _apply_scopes(
        session, client, grantable, granted, caller_scopes=caller_scopes
    )
    await session.commit()
    await session.refresh(client)
    return client


async def rotate_secret(
    session: AsyncSession, client_id: UUID, *, caller_scopes: set[str]
) -> str:
    client = await get_client_to_modify(session, client_id, caller_scopes)
    if client.client_type != ClientType.CONFIDENTIAL:
        raise PublicClientHasNoSecret

    secret = generate_token(32)
    client.client_secret_hash = hash_secret(secret)
    await session.commit()
    return secret


async def delete_client(
    session: AsyncSession, client_id: UUID, *, caller_scopes: set[str]
) -> None:
    client = await get_client_to_modify(session, client_id, caller_scopes)
    if client.is_system:
        raise SystemClientImmutable

    await session.delete(client)
    await session.commit()
