"""The kiosk's API: enrolling a face, given the ticket its owner created.

A client credential with `biometric:enroll` is not enough. The ticket is what
names the person, and only they can create one — after signing in to the
dashboard — so a stolen kiosk secret enrols nobody.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select

from provider.biometric import challenges, service, tickets
from provider.biometric.deps import FaceStorageDep, read_frames, require_biometric
from provider.biometric.engine_client import EngineDep
from provider.biometric.errors import FaceChallengeInvalid, TicketInvalid
from provider.biometric.schemas import (
    KioskChallengeRequest,
    KioskChallengeResponse,
    KioskEnrolment,
)
from provider.core.audit import set_target
from provider.core.auth import AccessToken, require_scope
from provider.core.config import settings
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.schemas import ErrorResponse
from provider.shared.models import Client, User

router = APIRouter(
    prefix="/biometric",
    tags=["biometric"],
    dependencies=[Depends(require_biometric)],
    include_in_schema=settings.iden_biometric_enabled,
)

ENROLL = require_scope("biometric:enroll")

CAPTURE_FAILURES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "No valid kiosk token"},
    403: {"model": ErrorResponse, "description": "Token lacks `biometric:enroll`"},
    404: {
        "model": ErrorResponse,
        "description": "Ticket expired, used, or out of attempts",
    },
}


async def _holder(session, redis, ticket: str, *, attempt: bool) -> User:
    user_id = await tickets.holder(redis, ticket, attempt=attempt)
    user = await session.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise TicketInvalid
    return user


@router.post(
    "/enroll/challenge",
    response_model=KioskChallengeResponse,
    summary="Start a face capture for the person holding a ticket",
    description=(
        "Reads the enrolment ticket from the person's QR code and returns what "
        "to capture: a few frames looking straight ahead, two head movements "
        "chosen at random, and a sequence of screen colours.\n\n"
        "Every call counts one attempt against the ticket; a ticket allows "
        f"{tickets.MAX_ATTEMPTS}.\n\n"
        "**Required scope:** `biometric:enroll`"
    ),
    responses=CAPTURE_FAILURES,
)
async def start_enrolment(
    body: KioskChallengeRequest,
    session: DBSessionDep,
    redis: RedisDep,
    token: Annotated[AccessToken, Depends(ENROLL)],
) -> KioskChallengeResponse:
    user = await _holder(session, redis, body.ticket, attempt=True)
    challenge = await challenges.issue(redis, user.id, "enrol")
    return KioskChallengeResponse.of(
        challenge, display_name=user.display_name or user.username
    )


@router.post(
    "/enroll",
    response_model=KioskEnrolment,
    status_code=201,
    summary="Enrol the face in a capture",
    description=(
        "Multipart: `ticket`, `faceChallengeId`, and one `frames` part per step "
        "of the challenge, in order (JPEG or PNG).\n\n"
        "The capture must pass every liveness check: the anti-spoofing models, "
        "the head movements, the screen-colour reflections, and the same face "
        "throughout. Any face already enrolled on the account is replaced, and "
        "the person is told by email.\n\n"
        "A `422 poor_capture` lists what to fix (`too_dark`, `too_small`, "
        "`blurred`, …) and a `422 not_live` the checks that failed; both leave "
        "the ticket usable for another attempt.\n\n"
        "**Required scope:** `biometric:enroll`"
    ),
    responses={
        **CAPTURE_FAILURES,
        422: {
            "model": ErrorResponse,
            "description": "Poor capture, failed liveness, or frames that do not "
            "match the challenge",
        },
        503: {"model": ErrorResponse, "description": "The engine is unavailable"},
    },
)
async def enrol(
    request: Request,
    ticket: Annotated[str, Form()],
    face_challenge_id: Annotated[str, Form(alias="faceChallengeId")],
    frames: Annotated[list[UploadFile], File()],
    session: DBSessionDep,
    redis: RedisDep,
    engine: EngineDep,
    storage: FaceStorageDep,
    token: Annotated[AccessToken, Depends(ENROLL)],
) -> KioskEnrolment:
    user = await _holder(session, redis, ticket, attempt=False)
    set_target(request, str(user.id))

    challenge = await challenges.consume(redis, face_challenge_id, user.id, "enrol")
    if challenge is None:
        raise HTTPException(status_code=404, detail=FaceChallengeInvalid())

    kiosk = await session.scalar(
        select(Client).where(Client.client_id == token.client_id)
    )
    if kiosk is None:
        raise HTTPException(status_code=401, detail="Unknown client.")

    rows = await service.enrol(
        session, engine, storage, user, kiosk, await read_frames(frames), challenge
    )
    await tickets.spend(redis, ticket, user.id)
    return KioskEnrolment(enrolled=True, samples=len(rows))
