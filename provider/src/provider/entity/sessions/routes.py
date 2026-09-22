from fastapi import APIRouter, Depends, Request, Response

from provider.authz import session_cookie
from provider.authz.logout import service as logout_service
from provider.authz.services import session_store
from provider.core.auth import CurrentUserDep, require_fresh_auth, require_scope
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.schemas import ErrorResponse
from provider.entity.sessions.schemas import SessionListResponse, SessionSummary
from provider.shared import user_agent

router = APIRouter(prefix="/entity/sessions", tags=["entity: sessions"])

READ = Depends(require_scope("entity:sessions:read"))
REVOKE = Depends(require_scope("entity:sessions:revoke"))
FRESH = Depends(require_fresh_auth(max_age=300))


@router.get(
    "",
    response_model=SessionListResponse,
    summary="See where you are signed in",
    description=(
        "Every live session for this person, newest first, with the "
        "applications each one reached. That list is what makes signing a "
        "session out mean something — those are the applications that will be "
        "told.\n\n"
        "**Required scope:** `entity:sessions:read`"
    ),
    dependencies=[READ],
)
async def list_sessions(
    request: Request, user: CurrentUserDep, redis: RedisDep
) -> SessionListResponse:
    cookie = request.cookies.get(session_cookie.NAME)
    current = session_store.public_id_of(cookie) if cookie else None

    sessions = await session_store.list_for_user(redis, user.id)

    summaries = []
    for session in sessions:
        # Derived here rather than stored: the labels are presentation, and the
        # header they come from is already kept verbatim in the audit log. The
        # raw string is deliberately not returned — it is fingerprinting
        # material, and the labels are what the screen needs.
        device, browser = user_agent.describe(session.user_agent)
        summaries.append(
            SessionSummary(
                id=session.id,
                current=session.id == current,
                authenticated_at=session.authenticated_at,
                last_seen_at=session.last_seen_at,
                amr=session.amr,
                clients=sorted(
                    await session_store.clients_for_public_id(redis, session.id)
                ),
                ip=session.ip,
                device=device,
                browser=browser,
            )
        )

    return SessionListResponse(sessions=summaries)


@router.delete(
    "/{session_id}",
    status_code=204,
    summary="Sign one session out",
    description=(
        "Ends that session everywhere: its refresh tokens are revoked and every "
        "application it reached is sent a logout token, exactly as "
        "`/oauth2/logout` does for your own.\n\n"
        "**Needs a recent sign-in** — this is how someone locks an intruder "
        "out, so it must not be available to the intruder.\n\n"
        "Returns `204` whether or not the session existed: a different answer "
        "would tell a caller which session ids are real.\n\n"
        "Ending your *own* session clears the session cookie with it, so the "
        "browser is not left holding one that names nothing.\n\n"
        "**Required scope:** `entity:sessions:revoke`"
    ),
    responses={403: {"model": ErrorResponse, "description": "Sign-in is not recent"}},
    dependencies=[REVOKE, FRESH],
)
async def revoke_session(
    session_id: str,
    request: Request,
    user: CurrentUserDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> Response:
    clients = await session_store.clients_for_public_id(redis, session_id)

    if await session_store.delete_by_public_id(redis, user.id, session_id):
        await logout_service.revoke_session_tokens(session, session_id)
        await logout_service.notify(
            session, client_ids=clients, subject=user.id, sid=session_id
        )
        await session.commit()

    response = Response(status_code=204)

    cookie = request.cookies.get(session_cookie.NAME)
    if cookie and session_store.public_id_of(cookie) == session_id:
        session_cookie.clear_session(response)

    return response
