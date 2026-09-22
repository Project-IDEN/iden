"""Test fixtures.

A real PostgreSQL database (`iden_test`), created once per session and truncated
between tests. Not SQLite: the models use PostgreSQL arrays and UUIDs.

The schema is built by running the migrations rather than `create_all`, because
that is the path a deployment takes.
"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from provider.core.config import settings
from provider.core.db import Base, get_db_session
from provider.core.redis import get_redis
from provider.core.security import hash_secret
from provider.core.storage import get_storage
from provider.shared.enums import ClientType, GrantType
from provider.shared.models import Client, ClientScope, ResourceApi, Scope, User

BASE_URL = make_url(settings.iden_database_url)
TEST_URL = BASE_URL.set(database="iden_test")
MAINTENANCE_URL = BASE_URL.set(database="postgres")

# A separate Redis logical database, flushed between tests, so a test run can
# never evict a developer's live session.
TEST_REDIS_URL = f"{settings.iden_redis_url.rsplit('/', 1)[0]}/15"

ADMIN_EMAIL = "admin@test.local"
ADMIN_PASSWORD = "correct-horse-battery-staple"
REDIRECT_URI = "http://localhost:5173/callback"
THIRD_PARTY_REDIRECT = "https://library.example.org/callback"


def _upgrade_to_head(url: str) -> None:
    """Run the migrations against `url`.

    In a worker thread: Alembic's env.py calls `asyncio.run`, which cannot nest
    inside the loop pytest is already running.
    """
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
async def engine():
    admin = create_async_engine(MAINTENANCE_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        _ = await conn.execute(text("DROP DATABASE IF EXISTS iden_test WITH (FORCE)"))
        _ = await conn.execute(text("CREATE DATABASE iden_test"))
    await admin.dispose()

    await asyncio.to_thread(
        _upgrade_to_head, TEST_URL.render_as_string(hide_password=False)
    )
    test_engine = create_async_engine(TEST_URL)

    yield test_engine
    await test_engine.dispose()

    admin = create_async_engine(MAINTENANCE_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        _ = await conn.execute(text("DROP DATABASE IF EXISTS iden_test WITH (FORCE)"))
    await admin.dispose()


@pytest.fixture
async def db(engine: AsyncEngine):
    """A session for the test body itself. Routes get their own — they commit,
    and the test must be able to see what they committed."""
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        _ = await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def redis():
    client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    yield client
    # Flushed on the way out as well, so a finished run leaves nothing behind.
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def catalogue(db):
    """The system APIs, scopes, and roles, seeded by the real seed functions —
    so a drift between the seed and the tests shows up as a failure."""
    from scripts.seed import seed_catalogue, seed_roles

    scopes = await seed_catalogue(db)
    roles = await seed_roles(db, scopes)
    await db.commit()
    return {"scopes": scopes, "roles": roles}


@pytest.fixture
async def admin_user(db, catalogue) -> User:
    user = User(
        email=ADMIN_EMAIL,
        username="admin",
        display_name="Administrator",
        password_hash=hash_secret(ADMIN_PASSWORD),
    )
    user.roles = [catalogue["roles"]["administrator"]]
    db.add(user)
    await db.commit()
    return user


@pytest.fixture
async def dashboard(db, catalogue) -> Client:
    client = Client(
        client_id="dashboard",
        name="IDEN Dashboard",
        client_type=ClientType.PUBLIC,
        allowed_grants=[GrantType.AUTHORIZATION_CODE, GrantType.REFRESH_TOKEN],
        redirect_uris=[REDIRECT_URI],
        post_logout_redirect_uris=["http://localhost:5173/"],
        skip_consent=True,
    )
    db.add(client)
    await db.flush()

    for scope in catalogue["scopes"].values():
        db.add(ClientScope(client_id=client.id, scope_id=scope.id, grantable=True))
    await db.commit()
    return client


@pytest.fixture
async def kiosk(db, catalogue) -> tuple[Client, str]:
    """Returns the client and its cleartext secret."""
    secret = "kiosk-test-secret"
    client = Client(
        client_id="kiosk",
        name="Biometric Kiosk",
        client_type=ClientType.CONFIDENTIAL,
        client_secret_hash=hash_secret(secret),
        allowed_grants=[GrantType.CLIENT_CREDENTIALS],
        skip_consent=True,
    )
    db.add(client)
    await db.flush()

    granted = catalogue["scopes"]["entity:profile:read"]
    db.add(
        ClientScope(
            client_id=client.id, scope_id=granted.id, grantable=False, granted=True
        )
    )
    await db.commit()
    return client, secret


class MemoryStorage:
    """The blob store, in a dict.

    A third container for two hundred bytes of test JPEG would be a poor trade,
    which is why `core.storage.Storage` is a protocol rather than an S3 client.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
async def client(engine, redis, storage, monkeypatch) -> AsyncGenerator[AsyncClient]:
    """An HTTP client wired to the app in-process — no live server, no port."""
    from provider.core import audit
    from provider.core.app import app

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_storage] = lambda: storage
    # The audit middleware runs outside the dependency system, so its session
    # factory has to be redirected separately — otherwise it writes to the
    # developer's own database while the rest of the test uses iden_test.
    monkeypatch.setattr(audit, "session_factory", factory)

    # base_url matches the configured issuer on purpose: /authorize builds
    # absolute resume URLs from it, and a cookie set on one host is not sent to
    # another. Mismatched hosts silently break the login round-trip.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url=settings.iden_issuer) as http:
        yield http

    app.dependency_overrides.clear()


@pytest.fixture
def scope_of(catalogue):
    """Look up a seeded Scope by its value."""
    return lambda value: catalogue["scopes"][value]


@pytest.fixture
async def token_for(db, admin_user, dashboard):
    """Mint an access token carrying exactly the given scopes.

    Lets a test assert on authorization without running a login flow.
    """
    from provider.authz.services import token_service

    async def _mint(*scopes: str, user: User | None = None) -> dict[str, str]:
        token, _, _ = await token_service.mint_access_token(
            db,
            subject=str((user or admin_user).id),
            client=dashboard,
            scopes=set(scopes),
            acr="iden:loa:1",
            amr=["pwd"],
            # Freshly authenticated, so the token satisfies require_fresh_auth.
            # A test about staleness moves the clock instead.
            authenticated_at=token_service.now(),
        )
        return {"Authorization": f"Bearer {token}"}

    return _mint


@pytest.fixture
async def admin_headers(token_for, catalogue):
    """Every admin scope — for tests whose subject is the resource, not the gate."""
    return await token_for(*[v for v in catalogue["scopes"] if v.startswith("admin:")])


@pytest.fixture
async def unheld_scope(db, catalogue) -> Scope:
    """A scope nobody holds — so it is always pruned at issuance."""
    api = ResourceApi(name="library", audience="https://api.example.org/library")
    db.add(api)
    await db.flush()

    scope = Scope(
        api_id=api.id, value="library:loans:read", description="View your loans."
    )
    db.add(scope)
    await db.commit()
    return scope


@pytest.fixture
async def third_party(db, catalogue, unheld_scope) -> Client:
    """A client that must ask, unlike the first-party dashboard."""
    client = Client(
        client_id="library",
        name="Library",
        client_type=ClientType.PUBLIC,
        allowed_grants=[GrantType.AUTHORIZATION_CODE, GrantType.REFRESH_TOKEN],
        redirect_uris=[THIRD_PARTY_REDIRECT],
        skip_consent=False,
    )
    db.add(client)
    await db.flush()

    for scope in (catalogue["scopes"]["entity:profile:read"], unheld_scope):
        db.add(ClientScope(client_id=client.id, scope_id=scope.id, grantable=True))
    await db.commit()
    return client


@pytest.fixture
def no_grace(monkeypatch):
    """Turn off the refresh replay window.

    By default a token re-presented straight away is a retry, which is the point
    of KI-16's fix. Tests about *theft* need the window closed.
    """
    monkeypatch.setattr(settings, "iden_refresh_grace_period", 0)


@pytest.fixture
async def member(db, catalogue) -> User:
    """An ordinary person: every entity scope, no admin authority."""
    user = User(
        email="student@test.local",
        username="student",
        display_name="A Student",
        password_hash=hash_secret("correct-horse-battery-staple"),
    )
    user.roles = [catalogue["roles"]["member"]]
    db.add(user)
    await db.commit()
    # Relationships are unloaded on a freshly created object, and reading one
    # later triggers a lazy load that fails in async code. Routes never hit
    # this because they load the user with a query; a fixture has to say so.
    await db.refresh(user, ["groups", "roles", "scopes"])
    return user


@pytest.fixture
async def developer(db, catalogue) -> User:
    """Someone who registers their own application against IDEN — the showcase
    participant. Self-service only; no authority over the directory."""
    user = User(
        email="dev@test.local",
        username="dev",
        display_name="A Developer",
        password_hash=hash_secret("correct-horse-battery-staple"),
    )
    user.roles = [catalogue["roles"]["developer"]]
    db.add(user)
    await db.commit()
    await db.refresh(user, ["groups", "roles", "scopes"])
    return user


@pytest.fixture
async def other_developer(db, catalogue) -> User:
    """A second one, so 'only your own applications' is testable."""
    user = User(
        email="dev2@test.local",
        username="dev2",
        display_name="Another Developer",
        password_hash=hash_secret("correct-horse-battery-staple"),
    )
    user.roles = [catalogue["roles"]["developer"]]
    db.add(user)
    await db.commit()
    await db.refresh(user, ["groups", "roles", "scopes"])
    return user


@pytest.fixture
async def developer_headers(token_for, developer, catalogue):
    return await token_for(
        *[v for v in catalogue["scopes"] if v.startswith("developer:")], user=developer
    )


@pytest.fixture
async def other_developer_headers(token_for, other_developer, catalogue):
    return await token_for(
        *[v for v in catalogue["scopes"] if v.startswith("developer:")],
        user=other_developer,
    )


@pytest.fixture
async def entity_headers(token_for, member, catalogue):
    return await token_for(
        *[v for v in catalogue["scopes"] if v.startswith("entity:")], user=member
    )


@pytest.fixture
async def self_headers(token_for, catalogue):
    """Every entity scope, for the administrator — the person the login flow
    helpers sign in as."""
    return await token_for(*[v for v in catalogue["scopes"] if v.startswith("entity:")])


@pytest.fixture
async def stale_headers(db, member, dashboard, catalogue):
    """A token for a sign-in that happened an hour ago.

    The clock moves in the token rather than the process: `auth_time` is what the
    freshness check reads, and no global state is involved.
    """
    from datetime import timedelta

    from provider.authz.services import token_service

    token, _, _ = await token_service.mint_access_token(
        db,
        subject=str(member.id),
        client=dashboard,
        scopes={v for v in catalogue["scopes"] if v.startswith("entity:")},
        acr="iden:loa:1",
        amr=["pwd"],
        authenticated_at=token_service.now() - timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}
