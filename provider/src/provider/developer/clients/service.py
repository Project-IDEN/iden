"""Application registration for people who are not administrators.

Everything here is scoped to one owner. No function takes a user id from the
caller — the owner is always the authenticated `User` the route was handed, so
reading or writing someone else's application is not something a bug can reach.
"""

import re
import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from provider.authz.services.scope_resolver import OIDC_SCOPES, grantable_scopes
from provider.core.config import settings
from provider.core.security import generate_token, hash_secret
from provider.developer.clients.errors import (
    ApplicationNotFound,
    ApplicationQuotaReached,
    PublicClientHasNoSecret,
)
from provider.developer.clients.schemas import ApplicationCreate, ApplicationUpdate
from provider.shared.enums import ClientType, GrantType
from provider.shared.models import Client, User

# What a self-registered application may do, always. `client_credentials` is the
# omission that matters: it lets a client act with no user present, so a
# registrant who could ask for it could mint a token for themselves alone.
SELF_SERVICE_GRANTS = [GrantType.AUTHORIZATION_CODE, GrantType.REFRESH_TOKEN]


def _client_id_for(name: str) -> str:
    """`library-web-3f9c1a2b4d5e6f70` — readable, and not chosen by the registrant.

    Letting a developer pick would let the first one to ask take `dashboard`, or
    a name that reads like another team's application on the consent screen. The
    random half is 64 bits, so the unique constraint on the column is a backstop
    that is never reached rather than a race to handle.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "app"
    return f"{slug}-{secrets.token_hex(8)}"


def visible_scopes(client: Client) -> list[str]:
    """What the application may put in its `scope` parameter.

    The OIDC scopes are not rows in the scopes table and are granted to every
    client (`scope_resolver.OIDC_SCOPES`), which is why a self-registered
    application needs no scope assignment to sign someone in and read their
    profile. Anything beyond them was attached by an administrator.
    """
    return sorted(set(OIDC_SCOPES) | grantable_scopes(client))


async def count_applications(session: AsyncSession, owner: User) -> int:
    return (
        await session.scalar(
            select(func.count(Client.id)).where(Client.owner_user_id == owner.id)
        )
        or 0
    )


async def list_applications(session: AsyncSession, owner: User) -> list[Client]:
    return list(
        await session.scalars(
            select(Client)
            .where(Client.owner_user_id == owner.id)
            .order_by(Client.created_at.desc())
        )
    )


async def get_application(
    session: AsyncSession, owner: User, application_id: uuid.UUID
) -> Client:
    """404 rather than 403 for an application belonging to someone else.

    A 403 would confirm the id exists, which is the one thing the owner of the
    other application has not agreed to share.
    """
    client = await session.scalar(
        select(Client).where(
            Client.id == application_id, Client.owner_user_id == owner.id
        )
    )
    if client is None:
        raise ApplicationNotFound
    return client


async def create_application(
    session: AsyncSession, owner: User, data: ApplicationCreate
) -> tuple[Client, str | None]:
    # Counting and inserting are two statements, so without this lock two
    # simultaneous registrations both see room and both insert. It serializes one
    # person's own registrations and nobody else's.
    await session.execute(select(User.id).where(User.id == owner.id).with_for_update())

    if await count_applications(session, owner) >= settings.iden_developer_max_clients:
        raise ApplicationQuotaReached

    secret = generate_token(32) if data.client_type == ClientType.CONFIDENTIAL else None

    client = Client(
        client_id=_client_id_for(data.name),
        name=data.name,
        client_type=data.client_type,
        client_secret_hash=hash_secret(secret) if secret else None,
        allowed_grants=list(SELF_SERVICE_GRANTS),
        redirect_uris=data.redirect_uris,
        post_logout_redirect_uris=data.post_logout_redirect_uris,
        # A third-party application asks. `skip_consent` exists for the
        # organization's own dashboard and is not on offer here.
        skip_consent=False,
        is_system=False,
        owner_user_id=owner.id,
    )
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return client, secret


async def update_application(
    session: AsyncSession,
    owner: User,
    application_id: uuid.UUID,
    data: ApplicationUpdate,
) -> Client:
    client = await get_application(session, owner, application_id)

    for field in ("name", "redirect_uris", "post_logout_redirect_uris"):
        value = getattr(data, field)
        if value is not None:
            setattr(client, field, value)

    await session.commit()
    await session.refresh(client)
    return client


async def rotate_secret(
    session: AsyncSession, owner: User, application_id: uuid.UUID
) -> str:
    client = await get_application(session, owner, application_id)
    if client.client_type != ClientType.CONFIDENTIAL:
        raise PublicClientHasNoSecret

    secret = generate_token(32)
    client.client_secret_hash = hash_secret(secret)
    await session.commit()
    return secret


async def delete_application(
    session: AsyncSession, owner: User, application_id: uuid.UUID
) -> None:
    client = await get_application(session, owner, application_id)
    await session.delete(client)
    await session.commit()
