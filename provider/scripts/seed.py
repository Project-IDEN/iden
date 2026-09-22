"""Idempotent development bootstrap.

Upserts the system catalogue and registers the bootstrap clients and
administrator. Safe to re-run at any time.

The schema is not its job: Alembic owns that, and the seed refuses to run
against a database that has not been migrated.

    uv run alembic upgrade head
    uv run python -m scripts.seed
"""

import asyncio
import secrets
import sys

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from provider.core.config import settings
from provider.core.db import engine, session_factory
from provider.core.security import hash_secret
from provider.shared.enums import ClientType, GrantType
from provider.shared.models import (
    Client,
    ClientScope,
    ResourceApi,
    Role,
    Scope,
    User,
)
from provider.shared.scopes import system_apis, system_roles

# The dashboard is served from /console -- the origin root's /admin/* is this
# API's, and the app's own admin screens have the same names. Both ports because
# `pnpm dev` serves on 5173 and the container on 3000.
DASHBOARD_REDIRECT_URIS = [
    "http://localhost:5173/console/callback",
    "http://localhost:3000/console/callback",
]


async def seed_catalogue(session: AsyncSession) -> dict[str, Scope]:
    """Upsert the system APIs and their scopes. Returns every scope by value."""
    scopes_by_value: dict[str, Scope] = {}

    for spec in system_apis():
        api = await session.scalar(
            select(ResourceApi).where(ResourceApi.name == spec.name)
        )
        if api is None:
            api = ResourceApi(name=spec.name)
            session.add(api)

        api.audience = spec.audience
        api.description = spec.description
        api.is_system = True
        await session.flush()

        for scope_spec in spec.scopes:
            scope = await session.scalar(
                select(Scope).where(
                    Scope.api_id == api.id, Scope.value == scope_spec.value
                )
            )
            if scope is None:
                scope = Scope(api_id=api.id, value=scope_spec.value)
                session.add(scope)

            scope.description = scope_spec.description
            scope.is_system = True
            scopes_by_value[scope_spec.value] = scope

    await session.flush()
    return scopes_by_value


async def seed_roles(
    session: AsyncSession, scopes: dict[str, Scope]
) -> dict[str, Role]:
    roles: dict[str, Role] = {}

    for spec in system_roles():
        role = await session.scalar(select(Role).where(Role.name == spec.name))
        if role is None:
            role = Role(name=spec.name)
            session.add(role)

        role.description = spec.description
        role.is_system = True
        # Assigned wholesale so a scope added to the catalogue reaches existing
        # deployments on the next seed.
        role.scopes = [scopes[value] for value in spec.scopes if value in scopes]
        roles[spec.name] = role

    await session.flush()
    return roles


async def seed_client(
    session: AsyncSession,
    *,
    client_id: str,
    name: str,
    client_type: ClientType,
    grants: list[str],
    redirect_uris: list[str],
    skip_consent: bool,
    scopes: dict[str, Scope],
    grantable: list[str],
    granted: list[str],
) -> str | None:
    """Upsert a bootstrap client. Returns a cleartext secret only when one was generated."""
    client = await session.scalar(select(Client).where(Client.client_id == client_id))
    secret = None

    if client is None:
        client = Client(client_id=client_id)
        session.add(client)
        if client_type is ClientType.CONFIDENTIAL:
            secret = secrets.token_urlsafe(32)
            client.client_secret_hash = hash_secret(secret)

    client.name = name
    client.client_type = client_type
    client.allowed_grants = grants
    client.redirect_uris = redirect_uris
    client.skip_consent = skip_consent
    client.is_system = True
    await session.flush()

    wanted = {
        value: (value in grantable, value in granted) for value in grantable + granted
    }
    # Queried rather than read off client.scopes: the relationship is unloaded on a
    # freshly flushed object, and a lazy load inside async code fails.
    links = await session.scalars(
        select(ClientScope).where(ClientScope.client_id == client.id)
    )
    existing = {link.scope.value: link for link in links}

    for value, (is_grantable, is_granted) in wanted.items():
        if value not in scopes:
            continue
        link = existing.get(value)
        if link is None:
            link = ClientScope(client_id=client.id, scope_id=scopes[value].id)
            session.add(link)
        link.grantable = is_grantable
        link.granted = is_granted

    await session.flush()
    return secret


async def seed_admin_user(session: AsyncSession, roles: dict[str, Role]) -> str | None:
    """Create the bootstrap administrator. Returns the password only on creation."""
    email = settings.iden_bootstrap_admin_email
    user = await session.scalar(select(User).where(User.email == email))
    if user is not None:
        return None

    password = settings.iden_bootstrap_admin_password or secrets.token_urlsafe(18)
    user = User(
        email=email,
        username="admin",
        display_name="Administrator",
        password_hash=hash_secret(password),
    )
    user.roles = [roles["administrator"]]
    session.add(user)
    await session.flush()

    return password


async def require_schema() -> None:
    """Fail loudly rather than half-seeding an empty database."""
    async with engine.connect() as conn:
        migrated = await conn.scalar(
            text("SELECT to_regclass('public.alembic_version')")
        )

    if migrated is None:
        sys.exit("No schema found. Run `uv run alembic upgrade head` first.")


async def main() -> None:
    await require_schema()

    async with session_factory() as session:
        scopes = await seed_catalogue(session)
        roles = await seed_roles(session, scopes)

        dashboard_scopes = [
            v for v in scopes if v.startswith(("admin:", "entity:", "developer:"))
        ]
        biometric_scopes = [v for v in scopes if v.startswith("biometric:")]

        await seed_client(
            session,
            client_id="dashboard",
            name="IDEN Dashboard",
            client_type=ClientType.PUBLIC,
            grants=[GrantType.AUTHORIZATION_CODE, GrantType.REFRESH_TOKEN],
            redirect_uris=DASHBOARD_REDIRECT_URIS,
            # First-party: consenting to your own organization's dashboard is noise.
            skip_consent=True,
            scopes=scopes,
            grantable=dashboard_scopes,
            granted=[],
        )
        kiosk_secret = await seed_client(
            session,
            client_id="kiosk",
            name="Biometric Kiosk",
            client_type=ClientType.CONFIDENTIAL,
            grants=[GrantType.CLIENT_CREDENTIALS],
            redirect_uris=[],
            skip_consent=True,
            scopes=scopes,
            grantable=[],
            granted=biometric_scopes,
        )
        admin_password = await seed_admin_user(session, roles)

        await session.commit()

    await engine.dispose()

    print(f"Seeded {len(scopes)} system scopes across {len(system_apis())} APIs.")
    if admin_password:
        print("\n  Bootstrap administrator — shown once, change it after first login")
        print(f"    email:    {settings.iden_bootstrap_admin_email}")
        print(f"    password: {admin_password}")
    if kiosk_secret:
        print("\n  Kiosk client secret — shown once, it is hashed in the database")
        print("    client_id:     kiosk")
        print(f"    client_secret: {kiosk_secret}")
    if not admin_password and not kiosk_secret:
        print("Nothing new to create — existing credentials left untouched.")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
