"""Append-only record of every state-changing request.

Written from its own session after the response: the request's transaction has
already committed, so the row and the change cannot be atomic. A failed write is
logged loudly rather than swallowed — see KI-17 in PLAN.md.

Pure ASGI rather than `@app.middleware("http")`, because reading the request body
from a BaseHTTPMiddleware consumes the stream the endpoint is about to read.
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

# Column widths. Every value below is clipped to its own, because the
# alternative is not a truncated row but *no row*: one character over fails the
# insert, the failure is caught, and the entry is gone. The `User-Agent` and the
# last path segment are both caller-chosen, which made "send a long header" a way
# to act without being recorded.
ACTION_LIMIT = 160
TARGET_LIMIT = 255
ACTOR_LABEL_LIMIT = 255
IP_LIMIT = 45
USER_AGENT_LIMIT = 512


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "\u2026"


def _clip_optional(value: str | None, limit: int) -> str | None:
    return None if value is None else _clip(value, limit)


@dataclass
class Actor:
    """Who is making the request, as far as the request itself can tell."""

    user_id: uuid.UUID | None = None
    client_id: str | None = None


def set_actor(
    request: Request, *, user_id: uuid.UUID | None = None, client_id: str | None = None
) -> None:
    """Record who the caller is, for the entry written after the response.

    From `require_scope`, and from the login steps, which authenticate somebody
    before any token exists.
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
    """Write an entry for something that is not an inbound request.

    What IDEN does on its own initiative — delivering a logout token, so far.
    Added to the caller's session rather than a fresh one, so it lives or dies
    with the transaction it describes.
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
            # Capped: without it, a photo upload buys a second copy of the whole
            # file in memory to derive nothing from.
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
                    action=_clip(f"{scope['method']} {route.path}", ACTION_LIMIT),
                    status_code=status_code,
                    # The last path parameter is the object being acted on:
                    # `/admin/apis/{api_id}/scopes/{scope_id}` is about the scope.
                    target=_clip_optional(
                        str(list(params.values())[-1]) if params else None, TARGET_LIMIT
                    ),
                    actor_user_id=actor.user_id,
                    actor_label=_clip_optional(label, ACTOR_LABEL_LIMIT),
                    actor_client=actor.client_id,
                    ip=_clip_optional(
                        scope["client"][0] if scope.get("client") else None, IP_LIMIT
                    ),
                    user_agent=_clip_optional(
                        _header(scope, b"user-agent"), USER_AGENT_LIMIT
                    ),
                    detail=detail,
                )
            )
            await session.commit()
    except Exception:
        # Never turn a completed request into a failure; the change is already
        # committed. Loud, because a silent gap is worse than no log.
        logger.exception(
            "Audit write failed", action=f"{scope['method']} {scope['path']}"
        )
