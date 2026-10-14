"""The kiosk's API: pairing, reporting in, and enrolling a face given the ticket
its owner created.

A client credential with `biometric:enroll` is not enough. The client must be a
registered kiosk, in service, and the ticket is what names the person: only they
can create one, after signing in to the dashboard, so a stolen kiosk secret
enrols nobody.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from provider.admin.kiosks import service as kiosks
from provider.biometric import challenges, pairing, service, tickets
from provider.biometric.deps import FaceStorageDep, read_frames, require_biometric
from provider.biometric.engine_client import EngineDep
from provider.biometric.errors import (
    FaceChallengeInvalid,
    KioskOutOfService,
    PairingCodeInvalid,
    TicketInvalid,
)
from provider.biometric.schemas import (
    Heartbeat,
    KioskChallengeRequest,
    KioskChallengeResponse,
    KioskConfig,
    KioskEnrolment,
    PairedKiosk,
    PairRequest,
)
from provider.core.audit import set_target
from provider.core.auth import AccessToken, require_scope
from provider.core.config import settings
from provider.core.db import DBSessionDep
from provider.core.ratelimit import KIOSK_PER_IP, PAIR_PER_IP, client_ip
from provider.core.redis import RedisDep
from provider.core.schemas import ErrorResponse
from provider.shared.models import Kiosk, User

router = APIRouter(
    prefix="/biometric",
    tags=["biometric"],
    dependencies=[Depends(require_biometric)],
    include_in_schema=settings.iden_biometric_enabled,
)


def _kiosk_of(scope: str):
    """The registered kiosk a token belongs to.

    Looked up on every request rather than trusted from the token: a revoked
    kiosk's last access token is still valid for minutes, and its row is gone.
    """
    require = require_scope(scope)

    async def dependency(
        session: DBSessionDep, token: Annotated[AccessToken, Depends(require)]
    ) -> Kiosk:
        kiosk = await kiosks.for_client(session, token.client_id)
        if kiosk is None:
            raise HTTPException(status_code=401, detail="Not a registered kiosk.")
        return kiosk

    return dependency


async def _enrolling_kiosk(
    kiosk: Annotated[Kiosk, Depends(_kiosk_of("biometric:enroll"))],
) -> Kiosk:
    if not kiosks.settings_of(kiosk).in_service:
        raise KioskOutOfService
    return kiosk


EnrollingKioskDep = Annotated[Kiosk, Depends(_enrolling_kiosk)]
DeviceKioskDep = Annotated[Kiosk, Depends(_kiosk_of("biometric:device"))]

CAPTURE_FAILURES: dict[int | str, dict[str, Any]] = {
    401: {
        "model": ErrorResponse,
        "description": "No valid kiosk token, or the kiosk was revoked",
    },
    403: {
        "model": ErrorResponse,
        "description": "Token lacks `biometric:enroll`, or the kiosk is out of "
        "service (`kiosk_out_of_service`)",
    },
    404: {
        "model": ErrorResponse,
        "description": "Ticket expired, used, or out of attempts",
    },
}


async def _holder(session, redis, ticket: str, *, attempt: bool) -> tuple[User, int]:
    held = await tickets.holder(redis, ticket, attempt=attempt)
    user = await session.get(User, held[0]) if held else None
    if held is None or user is None or not user.is_active:
        raise TicketInvalid
    return user, held[1]


@router.post(
    "/kiosk/pair",
    response_model=PairedKiosk,
    summary="Pair a device with its kiosk registration",
    description=(
        "Exchanges the pairing code an administrator was shown for this kiosk's "
        "client secret. The code works once. Pairing replaces the secret, so a "
        "device paired earlier with the same kiosk can no longer sign in.\n\n"
        "**Required scope:** none — the code is the credential."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Code expired or already used"},
        429: {"model": ErrorResponse, "description": "Too many attempts"},
    },
    dependencies=[Depends(PAIR_PER_IP)],
)
async def pair(
    body: PairRequest, request: Request, session: DBSessionDep, redis: RedisDep
) -> PairedKiosk:
    kiosk_id = await pairing.consume(redis, body.code)
    if kiosk_id is None:
        raise PairingCodeInvalid
    set_target(request, str(kiosk_id))
    kiosk, secret = await kiosks.pair(session, kiosk_id)
    return PairedKiosk(
        client_id=kiosk.client.client_id, client_secret=secret, name=kiosk.client.name
    )


@router.post(
    "/kiosk/heartbeat",
    response_model=KioskConfig,
    summary="Report in, and read this kiosk's settings",
    description=(
        "Called every `heartbeatSeconds`. Records that the kiosk is up, its "
        "software version and camera, and returns its name and settings as set "
        "in the dashboard. Not recorded in the audit log.\n\n"
        "**Required scope:** `biometric:device`"
    ),
    responses={
        401: {
            "model": ErrorResponse,
            "description": "No valid kiosk token, or the kiosk was revoked",
        },
        403: {"model": ErrorResponse, "description": "Token lacks `biometric:device`"},
    },
)
async def heartbeat(
    body: Heartbeat, request: Request, session: DBSessionDep, kiosk: DeviceKioskDep
) -> KioskConfig:
    kiosk = await kiosks.heartbeat(
        session,
        kiosk,
        version=body.software_version,
        camera=body.camera,
        address=client_ip(request),
    )
    return KioskConfig(
        name=kiosk.client.name,
        location=kiosk.location,
        settings=kiosks.settings_of(kiosk),
        heartbeat_seconds=kiosks.HEARTBEAT_SECONDS,
    )


@router.post(
    "/enroll/challenge",
    response_model=KioskChallengeResponse,
    summary="Start a face capture for the person holding a ticket",
    description=(
        "Reads the enrolment ticket from the person's QR code and returns what "
        "to capture: a few frames looking straight ahead, then two head "
        "movements chosen at random.\n\n"
        "Every call counts one attempt against the ticket; a ticket allows "
        f"{tickets.MAX_ATTEMPTS}.\n\n"
        "**Required scope:** `biometric:enroll`"
    ),
    responses=CAPTURE_FAILURES,
    dependencies=[Depends(KIOSK_PER_IP)],
)
async def start_enrolment(
    body: KioskChallengeRequest,
    session: DBSessionDep,
    redis: RedisDep,
    kiosk: EnrollingKioskDep,
) -> KioskChallengeResponse:
    user, attempts_left = await _holder(session, redis, body.ticket, attempt=True)
    challenge = await challenges.issue(redis, user.id, "enrol")
    return KioskChallengeResponse.of(
        challenge,
        display_name=user.display_name or user.username,
        attempts_left=attempts_left,
    )


@router.post(
    "/enroll",
    response_model=KioskEnrolment,
    status_code=201,
    summary="Enrol the face in a capture",
    description=(
        "Multipart: `ticket`, `faceChallengeId`, and one `frames` part per step "
        "of the challenge, in order, as JPEG.\n\n"
        "The capture must pass every liveness check: the anti-spoofing model, "
        "the head movements, and the same face throughout. Any face already enrolled on the account is replaced, and "
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
    dependencies=[Depends(KIOSK_PER_IP)],
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
    kiosk: EnrollingKioskDep,
) -> KioskEnrolment:
    user, _ = await _holder(session, redis, ticket, attempt=False)
    set_target(request, str(user.id))

    challenge = await challenges.consume(redis, face_challenge_id, user.id, "enrol")
    if challenge is None:
        raise HTTPException(status_code=404, detail=FaceChallengeInvalid())

    rows = await service.enrol(
        session,
        engine,
        storage,
        user,
        kiosk.client,
        await read_frames(frames),
        challenge,
    )
    await tickets.spend(redis, ticket, user.id)
    return KioskEnrolment(enrolled=True, samples=len(rows))
