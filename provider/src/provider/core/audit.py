"""Append-only record of every state-changing request.

Written from a session of its own after the response has been produced: the
request's own transaction has already committed by then, so the audit row and
the change it describes cannot be atomic. A failed write is logged loudly
rather than swallowed — see KI-17 in PLAN.md.

Pure ASGI rather than a `@app.middleware("http")` function: the request body is
part of what makes an entry worth reading, and reading it from inside a
BaseHTTPMiddleware consumes the stream the endpoint is about to read.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from provider.core.db import session_factory
from provider.core.logging import logger
from provider.shared.models import AuditEvent, User

# `/oauth2/token` is deliberately absent: a refresh happens every few minutes
# per active session, and issuance is already implied by the login that
# preceded it. Revocation is here because it destroys something.
AUDITED_PREFIXES = (
    "/admin",
    "/entity",
    "/developer",
    "/api/v1/auth",
    "/oauth2/revoke",
)

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# The exception to the read/write split: RP-initiated logout is a GET by
# specification (OIDC RP-Initiated Logout Section 2), and it destroys a session.
ALWAYS_AUDITED = frozenset({"/oauth2/logout"})

# Compared with punctuation stripped, so `client_secret` and `clientSecret` are
# the same key. Anything listed here never reaches the database.
SECRET_KEYS = frozenset(
    {
        "password",
        "newpassword",
        "currentpassword",
        "clientsecret",
        "secret",
        "token",
        "refreshtoken",
        "accesstoken",
        "code",
        "codeverifier",
    }
)

MAX_BODY_BYTES = 4096


@dataclass
class Actor:
    """Who is making the request, as far as the request itself can tell."""

    user_id: uuid.UUID | None = None
    client_id: str | None = None


def set_actor(
    request: Request, *, user_id: uuid.UUID | None = None, client_id: str | None = None
) -> None:
    """Record who the caller is, for the audit entry written after the response.

    Called from `require_scope` for token-authenticated routes and from the
    login steps, which authenticate a person before any token exists.
    """
    request.state.audit_actor = Actor(user_id=user_id, client_id=client_id)


def _normalise(key: str) -> str:
    return "".join(c for c in key if c.isalnum()).lower()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _normalise(key) in SECRET_KEYS else _redact(inner)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return None


def _body_detail(scope: Scope, body: bytes) -> dict:
    content_type = _header(scope, b"content-type") or ""
    if "application/json" not in content_type or not 0 < len(body) <= MAX_BODY_BYTES:
        return {}
    try:
        parsed = json.loads(body)
    except ValueError:
        return {}
    return _redact(parsed) if isinstance(parsed, dict) else {}


def _is_audited(scope: Scope) -> bool:
    if scope["type"] != "http":
        return False
    if scope["path"] in ALWAYS_AUDITED:
        return True
    return scope["method"] not in READ_METHODS and scope["path"].startswith(
        AUDITED_PREFIXES
    )


async def record(
    session: AsyncSession,
    *,
    action: str,
    status_code: int,
    target: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    detail: dict | None = None,
) -> None:
    """Write an audit entry for something that is not an inbound request.

    The middleware covers everything that arrives at IDEN. This covers what
    IDEN does on its own initiative — delivering a logout token, so far — which
    is equally part of the record and has no request to hang off.

    Added to the caller's session rather than a fresh one: this describes work
    inside a transaction, and it should live or die with it.
    """
    session.add(
        AuditEvent(
            action=action,
            status_code=status_code,
            target=target,
            actor_user_id=actor_user_id,
            detail=detail or {},
        )
    )


class AuditMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_audited(scope):
            await self.app(scope, receive, send)
            return

        body = bytearray()
        status = 0

        async def receive_copying_body() -> Message:
            message = await receive()
            # Stop copying once there is more than the detail extractor will
            # look at. Without the cap, uploading a photo buys a second copy of
            # the whole file in memory to derive nothing from.
            if message["type"] == "http.request" and len(body) <= MAX_BODY_BYTES:
                body.extend(message.get("body", b""))
            return message

        async def send_noting_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        await self.app(scope, receive_copying_body, send_noting_status)
        await _write(scope, bytes(body), status)


async def _write(scope: Scope, body: bytes, status_code: int) -> None:
    route = scope.get("route")
    if route is None:
        # No route matched, so nothing happened worth recording.
        return

    actor: Actor = scope.get("state", {}).get("audit_actor") or Actor()
    params = scope.get("path_params") or {}
    detail = _body_detail(scope, body)
    if params:
        detail = {**detail, "pathParams": {k: str(v) for k, v in params.items()}}
    if forwarded := _header(scope, b"x-forwarded-for"):
        # Recorded but not trusted: the socket peer is what `ip` holds, because
        # a header a client sets is a claim, not an observation.
        detail = {**detail, "xForwardedFor": forwarded}

    try:
        async with session_factory() as session:
            label = None
            if actor.user_id is not None:
                user = await session.get(User, actor.user_id)
                label = user.email if user else None

            session.add(
                AuditEvent(
                    action=f"{scope['method']} {route.path}",
                    status_code=status_code,
                    # The last path parameter is the object being acted on:
                    # `/admin/apis/{api_id}/scopes/{scope_id}` is about the scope.
                    target=str(list(params.values())[-1]) if params else None,
                    actor_user_id=actor.user_id,
                    actor_label=label,
                    actor_client=actor.client_id,
                    ip=scope["client"][0] if scope.get("client") else None,
                    user_agent=_header(scope, b"user-agent"),
                    detail=detail,
                )
            )
            await session.commit()
    except Exception:
        # An audit write must never turn a completed request into a failure —
        # the change has already been committed. Loud, because a silent gap in
        # an audit log is worse than no audit log.
        logger.exception(
            "Audit write failed", action=f"{scope['method']} {scope['path']}"
        )
