from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from provider.authz import session_cookie
from provider.authz.deps import LoginSessionDep
from provider.authz.login.errors import (
    ChallengeNotFound,
    InactiveUser,
    InvalidCredentials,
    InvalidTotpCode,
    NoSession,
    TotpNotEnrolled,
)
from provider.authz.login.schemas import (
    AuthStepResponse,
    ChallengeResponse,
    ChallengeScope,
    LoginRequest,
    TotpRequest,
)
from provider.authz.login.service import (
    authenticate_password,
    has_confirmed_totp,
    verify_totp,
)
from provider.authz.services import auth_methods, challenge_store, session_store
from provider.authz.services.scope_resolver import OIDC_SCOPES, parse_scope
from provider.core import ratelimit
from provider.core.audit import set_actor
from provider.core.config import settings
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.schemas import ErrorResponse
from provider.shared.enums import AmrMethod
from provider.shared.models import Client, Scope, User

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

OIDC_SCOPE_DESCRIPTIONS = {
    "openid": "Sign you in.",
    "profile": "Your name and username.",
    "email": "Your email address.",
    # OIDC Core Section 11 requires consent for this one specifically: it is the
    # difference between access while you are here and access while you are not.
    "offline_access": "Stay signed in when you are not using the application.",
}


async def _next_step(session, challenge, *, totp_enrolled: bool) -> AuthStepResponse:
    """What still has to happen before the authorization request can resume.

    Two separate reasons to ask for a code, and they answer to different people.
    The client can demand a level through `acr_values`. The *person* demands it
    by having set up an authenticator at all: once they have, a password alone
    stops being enough to sign in as them, whatever the client asked for.

    That second rule is the point of enrolling. A second factor that only
    applies when an application happens to request it protects nobody — the
    attacker with the password simply uses an application that does not ask.
    """
    acr = auth_methods.derive_acr(session.amr)
    amr = auth_methods.normalized_amr(session.amr)

    needs_step_up = not auth_methods.meets(acr, challenge.params.get("acr_values"))
    owes_second_factor = totp_enrolled and AmrMethod.OTP not in session.amr

    if needs_step_up or owes_second_factor:
        return AuthStepResponse(status="totp_required", acr=acr, amr=amr)

    return AuthStepResponse(
        status="complete",
        resume_url=challenge_store.resume_url(challenge),
        acr=acr,
        amr=amr,
    )


@router.get(
    "/challenge/{challenge_id}",
    response_model=ChallengeResponse,
    summary="Read a pending login or consent challenge",
    description=(
        "Everything the Auth UI needs to render its page: which application is "
        "asking, and for what.\n\n"
        "**Required scope:** none — the challenge id is the credential, and it "
        "expires in ten minutes."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Challenge expired or unknown"}
    },
)
async def read_challenge(
    challenge_id: str, session: DBSessionDep, redis: RedisDep
) -> ChallengeResponse:
    challenge = await challenge_store.get(redis, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail=ChallengeNotFound())

    client = await session.scalar(
        select(Client).where(Client.client_id == challenge.params["client_id"])
    )
    requested = parse_scope(challenge.params.get("scope"))

    descriptions = dict(OIDC_SCOPE_DESCRIPTIONS)
    rows = await session.execute(
        select(Scope.value, Scope.description).where(
            Scope.value.in_(requested - OIDC_SCOPES)
        )
    )
    descriptions |= {value: text for value, text in rows}

    return ChallengeResponse(
        client_name=client.name if client else challenge.params["client_id"],
        scopes=[
            ChallengeScope(value=value, description=descriptions.get(value, value))
            for value in sorted(requested)
        ],
        acr_values=challenge.params.get("acr_values"),
        authenticated=challenge.user_id is not None,
        login_hint=challenge.params.get("login_hint"),
    )


@router.post(
    "/login",
    response_model=AuthStepResponse,
    summary="Sign in with a password",
    description=(
        "Verifies the password, records `pwd` in the session's `amr`, and "
        "returns where to go next.\n\n"
        "The response is `totpRequired` rather than a resume URL in two cases, "
        "and they answer to different people:\n\n"
        "- the client asked for an assurance level a password alone does not "
        "reach (`acr_values`), or\n"
        "- **this person has an authenticator set up.** Once they do, a password "
        "alone stops being enough to sign in as them, whatever the client asked "
        "for. A second factor that applied only when an application requested it "
        "would protect nobody — whoever holds the password would use an "
        "application that does not ask.\n\n"
        "**Required scope:** none — this is how a session is established."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Email or password incorrect"},
        403: {"model": ErrorResponse, "description": "Account disabled"},
        404: {"model": ErrorResponse, "description": "Challenge expired or unknown"},
        429: {
            "model": ErrorResponse,
            "description": "Too many attempts, from this address or against this account",
        },
    },
    dependencies=[Depends(ratelimit.LOGIN_PER_IP)],
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    login_session: LoginSessionDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> AuthStepResponse:
    challenge = await challenge_store.get(redis, body.challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail=ChallengeNotFound())

    # Counted per account as well as per address: credential stuffing rotates
    # addresses and does not rotate the target.
    await ratelimit.guard(redis, identity=body.email, **ratelimit.LOGIN_FAILURES)

    try:
        user = await authenticate_password(session, body.email, body.password)
    except InvalidCredentials as exc:
        await ratelimit.record_failure(
            redis,
            ratelimit.LOGIN_FAILURES["bucket"],
            body.email,
            window=ratelimit.LOGIN_FAILURES["window"],
        )
        raise HTTPException(status_code=401, detail=exc) from exc
    except InactiveUser as exc:
        raise HTTPException(status_code=403, detail=exc) from exc

    # Cleared on success, so someone under attack can still sign in with the
    # password they know.
    await ratelimit.clear(redis, ratelimit.LOGIN_FAILURES["bucket"], body.email)

    await session.commit()
    # A failed attempt is audited too, with no actor — the submitted email is
    # in the entry's detail, and it is a claim, not an identity.
    set_actor(request, user_id=user.id)

    # Recorded so a person can recognise their own sessions later. The address
    # is the socket peer, the same source the rate limiter and the audit log
    # use — an `X-Forwarded-For` the caller sets is a claim, and honouring it
    # here would let anyone write any address into their own security page.
    origin = {
        "ip": ratelimit.client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }

    if login_session is not None and login_session.user_id == user.id:
        # Re-authenticating an existing session — `prompt=login`, or a `max_age`
        # it had outgrown. The id is kept: minting a new one would strand the
        # old session in Redis with no cookie pointing at it, and every client
        # already holding the old `sid` would never be signed out.
        login_session = await session_store.reauthenticate(
            redis, login_session, AmrMethod.PWD, **origin
        )
    else:
        # A different person on the same browser. The previous session ends
        # here rather than lingering until its TTL.
        if login_session is not None:
            await session_store.delete(redis, login_session.id)
        login_session = await session_store.create(
            redis, user.id, AmrMethod.PWD, **origin
        )

    session_cookie.set_session(response, login_session.id)

    challenge.user_id = user.id
    await challenge_store.save(redis, challenge)

    return await _next_step(
        login_session,
        challenge,
        totp_enrolled=await has_confirmed_totp(session, user.id),
    )


@router.post(
    "/totp",
    response_model=AuthStepResponse,
    summary="Verify a time-based one-time code",
    description=(
        "Adds `otp` to the session's `amr`, raising its assurance level. Used "
        "both as a second factor during login and as a mid-session step-up when "
        "a client requests a higher `acr_values`.\n\n"
        "**Required scope:** none — requires an existing session cookie."
    ),
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Code invalid or no authenticator enrolled",
        },
        401: {"model": ErrorResponse, "description": "No session"},
        404: {"model": ErrorResponse, "description": "Challenge expired or unknown"},
        429: {"model": ErrorResponse, "description": "Too many attempts"},
    },
    dependencies=[Depends(ratelimit.TOTP_PER_IP)],
)
async def totp(
    body: TotpRequest,
    request: Request,
    login_session: LoginSessionDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> AuthStepResponse:
    if login_session is None:
        raise HTTPException(status_code=401, detail=NoSession())

    challenge = await challenge_store.get(redis, body.challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail=ChallengeNotFound())

    user = await session.get(User, login_session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail=NoSession())

    set_actor(request, user_id=user.id)

    # A six-digit code is a small space; without this an attacker with a valid
    # session could simply try them all.
    await ratelimit.guard(redis, identity=str(user.id), **ratelimit.TOTP_FAILURES)

    try:
        await verify_totp(session, user, body.code)
    except (InvalidTotpCode, TotpNotEnrolled) as exc:
        await ratelimit.record_failure(
            redis,
            ratelimit.TOTP_FAILURES["bucket"],
            str(user.id),
            window=ratelimit.TOTP_FAILURES["window"],
        )
        raise HTTPException(status_code=400, detail=exc) from exc

    await ratelimit.clear(redis, ratelimit.TOTP_FAILURES["bucket"], str(user.id))

    await session_store.add_method(redis, login_session, AmrMethod.OTP)
    # Enrollment is settled by the code that just verified, so this cannot ask
    # for another one.
    return await _next_step(login_session, challenge, totp_enrolled=True)


@router.post(
    "/biometric",
    response_model=AuthStepResponse,
    summary="Sign in with a face",
    description=(
        "Adds `face` to the session's `amr`, but only when the engine reports a "
        "**liveness-verified** match — a match without liveness is not an "
        "authentication.\n\n"
        "Returns `501` unless `IDEN_BIOMETRIC_ENABLED` is set. The route exists "
        "while the module does not so the Auth UI contract is fixed from the "
        "start; Phase 4 fills in the handler.\n\n"
        "**Required scope:** none — requires an existing session or challenge."
    ),
    responses={
        501: {"model": ErrorResponse, "description": "Biometric module not enabled"}
    },
)
async def biometric() -> AuthStepResponse:
    if not settings.iden_biometric_enabled:
        raise HTTPException(
            status_code=501,
            detail="The biometric module is not enabled on this deployment.",
        )
    raise HTTPException(status_code=501, detail="Biometric login arrives in Phase 4.")
