from typing import Literal

from fastapi import APIRouter, Response
from pydantic import Field
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.schemas import CamelCaseBaseModel

router = APIRouter()

# Imported here rather than in app.py so the app module stays about wiring the
# application, not about knowing which modules exist.
from provider.admin.apis.routes import router as admin_apis_router  # noqa: E402
from provider.admin.audit.routes import router as admin_audit_router  # noqa: E402
from provider.admin.clients.routes import router as admin_clients_router  # noqa: E402
from provider.admin.groups.routes import router as admin_groups_router  # noqa: E402
from provider.admin.profile_fields.routes import (  # noqa: E402
    router as admin_profile_fields_router,
)
from provider.admin.roles.routes import router as admin_roles_router  # noqa: E402
from provider.admin.scopes.routes import router as admin_scopes_router  # noqa: E402
from provider.admin.users.routes import router as admin_users_router  # noqa: E402
from provider.authz.consent.routes import router as consent_router  # noqa: E402
from provider.authz.discovery.routes import router as discovery_router  # noqa: E402
from provider.authz.login.routes import router as login_router  # noqa: E402
from provider.authz.oauth.routes import router as oauth_router  # noqa: E402
from provider.authz.recovery.routes import router as recovery_router  # noqa: E402
from provider.developer.clients.routes import (  # noqa: E402
    router as developer_clients_router,
)
from provider.entity.connections.routes import (  # noqa: E402
    router as entity_connections_router,
)
from provider.entity.credentials.routes import (  # noqa: E402
    router as entity_credentials_router,
)
from provider.entity.permissions.routes import (  # noqa: E402
    router as entity_permissions_router,
)
from provider.entity.profile.routes import router as entity_profile_router  # noqa: E402
from provider.entity.sessions.routes import (  # noqa: E402
    router as entity_sessions_router,
)
from provider.entity.totp.routes import router as entity_totp_router  # noqa: E402
from provider.media.routes import router as media_router  # noqa: E402

router.include_router(discovery_router)
router.include_router(oauth_router)
router.include_router(login_router)
router.include_router(consent_router)
router.include_router(recovery_router)

router.include_router(admin_apis_router)
router.include_router(admin_scopes_router)
router.include_router(admin_roles_router)
router.include_router(admin_groups_router)
router.include_router(admin_users_router)
router.include_router(admin_clients_router)
router.include_router(admin_profile_fields_router)
router.include_router(admin_audit_router)

router.include_router(entity_profile_router)
router.include_router(entity_credentials_router)
router.include_router(entity_totp_router)
router.include_router(entity_sessions_router)
router.include_router(entity_connections_router)
router.include_router(entity_permissions_router)

router.include_router(developer_clients_router)

router.include_router(media_router)


class LivenessResponse(CamelCaseBaseModel):
    status: Literal["alive"] = Field(
        description="Constant. The process answered, which is the whole question."
    )


class HealthResponse(CamelCaseBaseModel):
    status: Literal["ok", "degraded"] = Field(
        description="`ok` only when every dependency is reachable."
    )
    database: Literal["ok", "unreachable"] = Field(
        description="PostgreSQL connectivity."
    )
    redis: Literal["ok", "unreachable"] = Field(description="Redis connectivity.")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    description=(
        "Reports whether the provider can reach PostgreSQL and Redis.\n\n"
        "Always returns `200` so a monitoring system can distinguish *the service "
        "is down* from *the service is up and telling you a dependency is down*.\n\n"
        "**Required scope:** none — this endpoint is public."
    ),
    tags=["health"],
)
async def health(session: DBSessionDep, redis: RedisDep) -> HealthResponse:
    return await _dependencies(session, redis)


async def _dependencies(session: AsyncSession, redis: Redis) -> HealthResponse:
    try:
        await session.execute(text("select 1"))
        database = "ok"
    except SQLAlchemyError:
        database = "unreachable"

    try:
        await redis.ping()
        cache = "ok"
    except RedisError:
        cache = "unreachable"

    status = "ok" if database == "ok" and cache == "ok" else "degraded"
    return HealthResponse(status=status, database=database, redis=cache)


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description=(
        "Whether the process is running. Touches no dependency, and answers "
        "`200` whenever it can answer at all.\n\n"
        "This is what an orchestrator should **restart** on. A liveness probe "
        "that checks the database restarts every replica the moment the "
        "database has a bad minute, which turns a recoverable outage into a "
        "restart loop. Use `/health/ready` to decide where to send traffic.\n\n"
        "**Required scope:** none — this endpoint is public."
    ),
    tags=["health"],
)
async def liveness() -> LivenessResponse:
    return LivenessResponse(status="alive")


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    description=(
        "Whether the provider can serve a request end to end: PostgreSQL and "
        "Redis both reachable.\n\n"
        "Unlike `/health`, an unreachable dependency answers **503**, so a load "
        "balancer takes this replica out of rotation without anyone parsing the "
        "body. Nothing here warrants a restart — see `/health/live`.\n\n"
        "**Required scope:** none — this endpoint is public."
    ),
    responses={503: {"description": "A dependency is unreachable."}},
    tags=["health"],
)
async def readiness(
    session: DBSessionDep, redis: RedisDep, response: Response
) -> HealthResponse:
    health = await _dependencies(session, redis)
    if health.status != "ok":
        response.status_code = 503
    return health
