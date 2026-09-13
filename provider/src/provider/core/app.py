import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from urllib.parse import urlencode

import structlog
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from provider.authz.oauth.errors import OAuthError, RedirectableError
from provider.core import redis as redis_module
from provider.core.audit import AuditMiddleware
from provider.core.config import settings
from provider.core.db import engine
from provider.core.errors import (
    ConflictError,
    IdenError,
    ImmutableError,
    NotFoundError,
    RateLimitedError,
    UnavailableError,
    ValidationError,
)
from provider.core.headers import SecurityHeadersMiddleware
from provider.core.logging import configure_logging, logger
from provider.core.router import router
from provider.core.schemas import ErrorResponse
from provider.core.storage import ensure_ready

configure_logging()

# Domain errors carry no HTTP knowledge, so the mapping lives here — the one
# place that knows both vocabularies. Matched by class rather than by code, so a
# package can raise `ApiNotFound` with its own message and still land on 404.
# Most specific first: ImmutableError is a ConflictError.
ERROR_STATUS = (
    (RateLimitedError, 429),
    (NotFoundError, 404),
    (ImmutableError, 409),
    (ConflictError, 409),
    (ValidationError, 422),
    (UnavailableError, 503),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Provider starting", env=settings.iden_env, issuer=settings.iden_issuer)
    await ensure_ready()
    yield
    await engine.dispose()
    await redis_module.client.aclose()


# The interactive docs are a development tool, and a deployment is reachable by
# anyone the moment it is behind a proxy. `/openapi.json` is the complete shape
# of the admin API -- every route, every field -- which is a map worth not
# handing out. `app.openapi()` still builds the schema in process, so
# `web/scripts/gen-api.sh` keeps working either way.
_DOCS_ENABLED = settings.iden_env != "prod"

app = FastAPI(
    title="IDEN Core Server",
    version="0.0.1",
    description=(
        "Identity and access control provider. "
        "See `/.well-known/openid-configuration` for OIDC metadata."
    ),
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)


@app.middleware("http")
async def add_request_id(request: Request, call_next: Callable) -> Response | None:
    request_id = str(uuid.uuid4())

    request.state.request_id = request_id

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    response = await call_next(request)
    return response


@app.exception_handler(IdenError)
async def handle_iden_error(request: Request, exc: IdenError) -> JSONResponse:
    """Translate a domain exception into the documented JSON error shape.

    Central rather than per-route: the mapping is uniform across every
    resource, and thirty routes each repeating the same try/except would add
    noise without adding meaning. Routes still declare their failures in
    `responses={...}` so `/docs` stays accurate.
    """
    status_code = next(
        (code for cls, code in ERROR_STATUS if isinstance(exc, cls)), 500
    )
    if status_code >= 500:
        logger.error("Unmapped domain error", code=exc.code, path=request.url.path)

    body = ErrorResponse(code=exc.code, message=exc.message, details=exc.details)
    # A client told to back off but not told for how long simply retries at once.
    headers = (
        {"Retry-After": str(exc.retry_after)}
        if isinstance(exc, RateLimitedError)
        else None
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(by_alias=True),
        headers=headers,
    )


# A bare HTTPException carries a status and a string. The contract needs a
# stable machine-readable code as well, and there is no per-route information
# to derive one from — the status is the whole of what was said.
STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    501: "not_implemented",
}


def _is_oauth(request: Request) -> bool:
    return request.url.path.startswith(f"{settings.iden_api_prefix}/oauth2")


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Give `raise HTTPException(...)` the same body shape as everything else.

    Without this the provider speaks two dialects: `/admin/*` answers with
    `code`/`message` from the domain-error handler, while every dependency that
    raises HTTPException — `require_scope`, the entity user lookup, login —
    answers with Starlette's `{"detail": ...}`. Handled centrally rather than by
    replacing HTTPException everywhere, because the raising code is right; it is
    only the serialization that was inconsistent.

    A route that raises with a domain error as the detail keeps that error's
    code: the status is the route's to choose, but `totp_not_enrolled` and
    `invalid_totp_code` are both a 400 and a caller has to be able to tell them
    apart.
    """
    body = ErrorResponse(
        code=exc.detail.code
        if isinstance(exc.detail, IdenError)
        else STATUS_CODES.get(exc.status_code, "error"),
        message=str(exc.detail),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(by_alias=True),
        # WWW-Authenticate is where RFC 6750 and RFC 9470 put the machine-
        # readable part of a 401 or a step-up, so it must survive.
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """A malformed request body, reported in the contract's shape.

    FastAPI's default is a third shape again — `{"detail": [...]}` with a list
    where every other error has a string.
    """
    if _is_oauth(request):
        # A client library reading RFC 6749 Section 5.2 will not recognise anything
        # else, and a missing `grant_type` is exactly `invalid_request`.
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "error_description": "The request is missing a required parameter or is malformed.",
            },
        )

    fields = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
    body = ErrorResponse(
        code="validation_error",
        message="The request is invalid.",
        details={"fields": fields},
    )
    return JSONResponse(status_code=422, content=body.model_dump(by_alias=True))


# Connectivity failures only. `SQLAlchemyError` and `RedisError` would also
# catch a malformed query or a wrong argument — programming errors, which must
# keep surfacing as 500s rather than being reported as someone else's outage.
UNAVAILABLE = (
    RedisConnectionError,
    RedisTimeoutError,
    OperationalError,
    InterfaceError,
)


async def handle_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """A store the provider depends on is unreachable.

    Without this the exception escapes to the ASGI server, which answers with a
    bare `Internal Server Error` — a third body shape, arriving at exactly the
    moment an operator is trying to work out what broke. 503 also tells a proxy
    it may retry, which 500 does not.
    """
    logger.error(
        "Dependency unavailable",
        path=request.url.path,
        error=type(exc).__name__,
    )
    body = ErrorResponse(
        code="service_unavailable",
        message="A service the provider depends on is unavailable.",
    )
    return JSONResponse(
        status_code=503,
        content=body.model_dump(by_alias=True),
        headers={"Retry-After": "5"},
    )


for _exception in UNAVAILABLE:
    app.add_exception_handler(_exception, handle_unavailable)


@app.exception_handler(RedirectableError)
async def handle_redirectable_error(
    request: Request, exc: RedirectableError
) -> RedirectResponse:
    """Deliver the error to the client's redirect_uri — RFC 6749 Section 4.1.2.1.

    Only reachable after client_id and redirect_uri have been validated.
    """
    # `iss` rides on the error response too — RFC 9207 Section 2 requires it on every
    # authorization response, and a client that validates it on success but not
    # on failure has only closed half the mix-up.
    params = {
        "error": exc.error,
        "error_description": exc.description,
        "iss": settings.iden_issuer,
    }
    if exc.state:
        params["state"] = exc.state
    return RedirectResponse(f"{exc.redirect_uri}?{urlencode(params)}", status_code=303)


@app.exception_handler(OAuthError)
async def handle_oauth_error(request: Request, exc: OAuthError) -> JSONResponse:
    """RFC 6749 Section 5.2 fixes this shape; a client library will not understand
    the project's own error contract here.

    The `WWW-Authenticate` scheme follows what failed, not the status code.
    `invalid_client` is a *client* that did not authenticate, so `Basic` tells
    it to retry with its credentials (RFC 6749 Section 5.2). `invalid_token` is a
    protected resource refusing a *user's* token, and answering `Basic` there
    told the client to present client credentials instead of sending the person
    back through a login — the opposite of the recovery it needs (RFC 6750 Section 3).
    """
    headers = None
    if exc.status_code in (401, 403):
        challenge = (
            'Basic realm="iden"'
            if exc.error == "invalid_client"
            else f'Bearer error="{exc.error}", error_description="{exc.description}"'
        )
        headers = {"WWW-Authenticate": challenge}

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "error_description": exc.description},
        headers=headers,
    )


# Every state-changing request leaves a permanent record. Added before CORS so
# it wraps the routing that populates the route template it records.
app.add_middleware(AuditMiddleware)

# Credentialed requests from the hosted Auth UI and the dashboard: the session
# cookie must ride along, which requires an explicit origin allow-list.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.iden_auth_ui_base_url,
        *settings.iden_allowed_admin_origins,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Neither of these is CORS-safelisted, so without naming them here a browser
    # hands the application a 403 or a 429 stripped of the one part that says
    # what to do about it — the step-up challenge of RFC 9470, and how long to
    # wait. `allow_headers` does not cover this; it governs the request.
    expose_headers=["WWW-Authenticate", "Retry-After"],
)

# Outermost, so the headers reach responses the inner middleware produces on
# its own — a CORS preflight, an audit failure — not only the ones routes return.
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(router, prefix=settings.iden_api_prefix)


def main():
    # Reload watches the source tree and restarts on every write. In a container
    # that is a memory cost and a restart loop waiting for a mounted file to
    # change, so it follows the environment rather than being always on.
    uvicorn.run(
        "provider.core.app:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,
        reload=settings.iden_env == "dev",
        # Uvicorn rewrites `scope["client"]` from `X-Forwarded-For` when the peer
        # is trusted, which is why neither the rate limiter nor the audit log has
        # to know a proxy exists. An empty list trusts nobody — uvicorn's own
        # default trusts loopback, and that is a decision worth making out loud
        # rather than inheriting.
        forwarded_allow_ips=settings.iden_forwarded_allow_ips or [],
    )
