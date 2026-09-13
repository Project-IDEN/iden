from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from provider.authz.consent.schemas import ConsentRequest, ConsentResponse
from provider.authz.consent.service import record_consent
from provider.authz.deps import LoginSessionDep
from provider.authz.login.errors import ChallengeNotFound, NoSession
from provider.authz.services import challenge_store
from provider.authz.services.scope_resolver import parse_scope, resolve_for_user
from provider.core.audit import set_actor
from provider.core.config import settings
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.schemas import ErrorResponse
from provider.shared.models import Client, User

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post(
    "/consent",
    response_model=ConsentResponse,
    summary="Approve or deny a consent request",
    description=(
        "Records the user's decision and returns where to send the browser.\n\n"
        "Approval persists a consent grant so the same scopes are not asked for "
        "again. Denial returns the user to the client with `error=access_denied` "
        "as required by RFC 6749 Section 4.1.2.1.\n\n"
        "**Required scope:** none — requires an existing session cookie."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "No session"},
        404: {"model": ErrorResponse, "description": "Challenge expired or unknown"},
    },
)
async def consent(
    body: ConsentRequest,
    request: Request,
    login_session: LoginSessionDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> ConsentResponse:
    if login_session is None:
        raise HTTPException(status_code=401, detail=NoSession())

    challenge = await challenge_store.get(redis, body.challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail=ChallengeNotFound())

    if not body.approved:
        await challenge_store.delete(redis, challenge.id)
        params = {
            "error": "access_denied",
            "error_description": "The user refused the request.",
            # An authorization response like any other — RFC 9207 Section 2.
            "iss": settings.iden_issuer,
        }
        if state := challenge.params.get("state"):
            params["state"] = state
        return ConsentResponse(
            redirect_url=f"{challenge.params['redirect_uri']}?{urlencode(params)}"
        )

    user = await session.get(User, login_session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail=NoSession())

    set_actor(request, user_id=user.id)

    client = await session.scalar(
        select(Client).where(Client.client_id == challenge.params["client_id"])
    )
    if client is None:
        raise HTTPException(status_code=404, detail=ChallengeNotFound())

    # The resolved set, not the requested one. A user shown a consent screen
    # agrees to what they are actually granting; recording the raw request would
    # also bank consent for scopes that were pruned because they did not hold
    # them — so a role granted later would be used without ever asking again.
    requested = parse_scope(challenge.params.get("scope"))
    granted = resolve_for_user(requested, client, user)

    await record_consent(session, user, client, granted)
    await session.commit()

    return ConsentResponse(redirect_url=challenge_store.resume_url(challenge))
