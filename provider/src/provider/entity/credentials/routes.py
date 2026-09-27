from fastapi import APIRouter, Depends, Request

from provider.authz import session_cookie
from provider.core.auth import CurrentUserDep, require_fresh_auth, require_scope
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.schemas import ErrorResponse
from provider.entity.credentials import service
from provider.entity.credentials.schemas import CredentialChangeResponse, PasswordChange

router = APIRouter(prefix="/entity/credentials", tags=["entity: credentials"])

WRITE = Depends(require_scope("entity:credentials:write"))
FRESH = Depends(require_fresh_auth(max_age=300))

FRESHNESS = (
    "**Needs a recent sign-in.** A valid token is not enough: someone holding "
    "a stolen one could take the account over outright. A sign-in within five "
    "minutes is required, and the refusal is RFC 9470's "
    "`insufficient_user_authentication` with the `max_age` that would satisfy "
    "it — send the user back through `/authorize` with that `max_age`.\n\n"
)


@router.post(
    "/password",
    response_model=CredentialChangeResponse,
    summary="Change your password",
    description=(
        "Requires the current password as well as a recent sign-in: one proves "
        "the account, the other proves the person.\n\n"
        + FRESHNESS
        + "Every refresh token is revoked and every other session ends. The "
        "session making the change survives — signing someone out of the page "
        "they are using to secure their account is hostile.\n\n"
        "**Required scope:** `entity:credentials:write`"
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Sign-in is not recent enough"},
        422: {"model": ErrorResponse, "description": "Wrong or unchanged password"},
    },
    dependencies=[WRITE, FRESH],
)
async def change_password(
    body: PasswordChange,
    request: Request,
    user: CurrentUserDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> CredentialChangeResponse:
    ended = await service.change_password(
        session,
        redis,
        user,
        current=body.current_password,
        new=body.new_password,
        keep_session=request.cookies.get(session_cookie.NAME),
    )
    return CredentialChangeResponse(sessions_ended=ended)
