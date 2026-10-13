from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    FaceChallengeRequest,
    LoginRequest,
    TotpRequest,
)
from provider.authz.login.service import (
    authenticate_password,
    enrolled_methods,
    verify_totp,
)
from provider.authz.logout import service as logout_service
from provider.authz.services import auth_methods, challenge_store, session_store
from provider.authz.services.scope_resolver import OIDC_SCOPES, parse_scope
from provider.biometric import challenges
from provider.biometric import service as face
from provider.biometric.deps import read_frames
from provider.biometric.engine_client import EngineDep
from provider.biometric.errors import (
    FaceChallengeInvalid,
    FaceNotEnrolled,
    FaceRejected,
)
from provider.biometric.schemas import FaceChallengeResponse
from provider.core import ratelimit
from provider.core.audit import set_actor
from provider.core.config import settings
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.schemas import ErrorResponse
from provider.shared import logos, user_agent
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


async def _next_step(session, challenge, enrolled: set[str]) -> AuthStepResponse:
    """What still has to happen before the authorization request can resume —
    see `auth_methods.outstanding` for when that is another method."""
    acr = auth_methods.derive_acr(session.amr)
    amr = auth_methods.normalized_amr(session.amr)

    required = challenge.params.get("acr_values")
    if methods := auth_methods.outstanding(session.amr, enrolled, required):
        return AuthStepResponse(
            status="method_required", methods=methods, acr=acr, amr=amr
        )

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
        client_logo_url=logos.public_url(client.logo_key) if client else None,
        scopes=[
            ChallengeScope(value=value, description=descriptions.get(value, value))
            for value in sorted(requested)
        ],
        acr_values=challenge.params.get("acr_values"),
        authenticated=challenge.user_id is not None,
        methods=challenge.methods,
        login_hint=challenge.params.get("login_hint"),
    )


@router.post(
    "/login",
    response_model=AuthStepResponse,
    summary="Sign in with a password",
    description=(
        "Verifies the password, records `pwd` in the session's `amr`, and "
        "returns where to go next.\n\n"
        "The response is `method_required`, naming the methods owed, rather "
        "than a resume URL in two cases, and they answer to different people:\n\n"
        "- the client asked for an assurance level a password alone does not "
        "reach (`acr_values`) and this person has a method that does, or\n"
        "- **this person has an authenticator set up.** Once they do, a password "
        "alone stops being enough to sign in as them, whatever the client asked "
        "for. A second factor that applied only when an application requested it "
        "would protect nobody — whoever holds the password would use an "
        "application that does not ask.\n\n"
        "A level this person cannot reach at all is not asked for here. The "
        "response is `complete`, and the authorization request it resumes "
        "returns `unmet_authentication_requirements` to the client.\n\n"
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
        "user_agent": user_agent.capture(request.headers.get("user-agent")),
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
        # A different person on the same browser. IDEN holds one account per
        # browser, so the previous person is signed out here — fully, as
        # /oauth2/logout would: deleting their session alone would leave every
        # application it reached still signed in as them, with refresh tokens
        # nobody could find to revoke.
        if login_session is not None:
            await logout_service.end_session(session, redis, login_session)
        login_session = await session_store.create(
            redis, user.id, AmrMethod.PWD, **origin
        )

    session_cookie.set_session(response, login_session.id)

    challenge.user_id = user.id
    await challenge_store.save(redis, challenge)

    return await _next_step(
        login_session, challenge, await enrolled_methods(session, user.id)
    )


@router.post(
    "/totp",
    response_model=AuthStepResponse,
    summary="Verify a time-based one-time code",
    description=(
        "Adds `otp` to the session's `amr`, raising its assurance level. Used "
        "both as a second factor during login and as a mid-session step-up when "
        "a client requests a higher `acr_values` — in which case the challenge "
        "lists `otp` in `methods` and the Auth UI starts here, without asking "
        "for the password the session already has.\n\n"
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
    return await _next_step(
        login_session, challenge, await enrolled_methods(session, user.id)
    )


FACE_DISABLED = "The biometric module is not enabled on this deployment."


async def _face_step(
    login_session: session_store.Session | None,
    challenge_id: str,
    session: AsyncSession,
    redis: Redis,
) -> tuple[session_store.Session, challenge_store.Challenge, User]:
    """The person a face step is for — whoever this session already signed in
    — and the authorization request it belongs to.

    Face is a second factor only. Without a session there is no claimed
    identity to compare against, and a face alone is not a way in.
    """
    if not settings.iden_biometric_enabled:
        raise HTTPException(status_code=501, detail=FACE_DISABLED)
    if login_session is None:
        raise HTTPException(status_code=401, detail=NoSession())
    challenge = await challenge_store.get(redis, challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail=ChallengeNotFound())
    user = await session.get(User, login_session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail=NoSession())
    return login_session, challenge, user


@router.post(
    "/biometric/challenge",
    response_model=FaceChallengeResponse,
    summary="Start a face check",
    description=(
        "Returns what the camera must capture for `POST /api/v1/auth/biometric`: "
        "frames looking straight ahead, two head movements chosen at random, "
        "and a sequence of screen colours. Valid for one attempt and two "
        "minutes.\n\n"
        "Face is offered only **after a password** — this needs the session "
        "cookie the password step set.\n\n"
        "**Required scope:** none — requires an existing session."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "No session"},
        404: {
            "model": ErrorResponse,
            "description": "Challenge expired, or no face enrolled",
        },
        501: {"model": ErrorResponse, "description": "Biometric module not enabled"},
    },
    dependencies=[Depends(ratelimit.FACE_PER_IP)],
)
async def face_challenge(
    body: FaceChallengeRequest,
    login_session: LoginSessionDep,
    session: DBSessionDep,
    redis: RedisDep,
) -> FaceChallengeResponse:
    _, _, user = await _face_step(login_session, body.challenge_id, session, redis)
    if not await face.is_enrolled(session, user.id):
        raise HTTPException(status_code=404, detail=FaceNotEnrolled())
    return FaceChallengeResponse.of(await challenges.issue(redis, user.id, "login"))


@router.post(
    "/biometric",
    response_model=AuthStepResponse,
    summary="Sign in with a face",
    description=(
        "Multipart: `challengeId`, `faceChallengeId`, and one `frames` part per "
        "step of the face challenge, in order.\n\n"
        "Adds `face` to the session's `amr` only when the capture is **live** — "
        "it passes the anti-spoofing models, follows the requested head "
        "movements, reflects the screen colours, and shows one face throughout "
        "— **and** matches the face enrolled on this account. A match without "
        "liveness is not an authentication.\n\n"
        "`422 poor_capture` lists what to fix and does not count as a failed "
        "attempt. `401 face_rejected` does, and deliberately does not say "
        "whether the face did not match or was not live.\n\n"
        "**Required scope:** none — requires an existing session."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "No session, or rejected"},
        404: {
            "model": ErrorResponse,
            "description": "Challenge or face challenge expired, or no face enrolled",
        },
        409: {
            "model": ErrorResponse,
            "description": "Enrolled under an earlier model; enrol again",
        },
        422: {"model": ErrorResponse, "description": "Poor capture or bad frames"},
        429: {"model": ErrorResponse, "description": "Too many attempts"},
        501: {"model": ErrorResponse, "description": "Biometric module not enabled"},
        503: {"model": ErrorResponse, "description": "The engine is unavailable"},
    },
    dependencies=[Depends(ratelimit.FACE_PER_IP)],
)
async def biometric(
    request: Request,
    challenge_id: Annotated[str, Form(alias="challengeId")],
    face_challenge_id: Annotated[str, Form(alias="faceChallengeId")],
    frames: Annotated[list[UploadFile], File()],
    login_session: LoginSessionDep,
    session: DBSessionDep,
    redis: RedisDep,
    engine: EngineDep,
) -> AuthStepResponse:
    login_session, challenge, user = await _face_step(
        login_session, challenge_id, session, redis
    )
    set_actor(request, user_id=user.id)
    await ratelimit.guard(redis, identity=str(user.id), **ratelimit.FACE_FAILURES)

    face_challenge = await challenges.consume(
        redis, face_challenge_id, user.id, "login"
    )
    if face_challenge is None:
        raise HTTPException(status_code=404, detail=FaceChallengeInvalid())

    try:
        await face.verify(
            session, engine, user.id, await read_frames(frames), face_challenge
        )
    except FaceRejected as exc:
        await ratelimit.record_failure(
            redis,
            ratelimit.FACE_FAILURES["bucket"],
            str(user.id),
            window=ratelimit.FACE_FAILURES["window"],
        )
        raise HTTPException(status_code=401, detail=exc) from exc

    await ratelimit.clear(redis, ratelimit.FACE_FAILURES["bucket"], str(user.id))

    login_session = await session_store.add_method(redis, login_session, AmrMethod.FACE)
    return await _next_step(
        login_session, challenge, await enrolled_methods(session, user.id)
    )
