"""A person's own face: whether it is enrolled, letting a kiosk enrol it, removing it.

Enrolment itself happens at a kiosk, never here — this is where a person
creates the ticket that lets one.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from provider.biometric import service, tickets
from provider.biometric.deps import FaceStorageDep, require_biometric
from provider.core.auth import CurrentUserDep, require_fresh_auth, require_scope
from provider.core.config import settings
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.schemas import ErrorResponse
from provider.entity.face.schemas import EnrolmentTicket, FaceStatus
from provider.shared.models import Client

router = APIRouter(
    prefix="/entity/face",
    tags=["entity: face"],
    dependencies=[Depends(require_biometric)],
    include_in_schema=settings.iden_biometric_enabled,
)

READ = Depends(require_scope("entity:face:read"))
WRITE = Depends(require_scope("entity:face:write"))
FRESH = Depends(require_fresh_auth(max_age=300))

FRESHNESS = (
    "**Needs a recent sign-in.** An enrolled face is a way to sign in as you, so "
    "somebody holding a stolen access token must not be able to let a kiosk "
    "add theirs — nor to remove yours. The refusal is RFC 9470's "
    "`insufficient_user_authentication`.\n\n"
)


@router.get(
    "",
    response_model=FaceStatus,
    summary="Is a face enrolled?",
    description=(
        "Whether a face is on file, when and where it was enrolled.\n\n"
        "**Required scope:** `entity:face:read`"
    ),
    dependencies=[READ],
)
async def read_status(user: CurrentUserDep, session: DBSessionDep) -> FaceStatus:
    rows = await service.templates(session, user.id)
    if not rows:
        return FaceStatus(enrolled=False)

    kiosk = await session.scalar(
        select(Client.name).where(Client.client_id == rows[0].enrolled_by)
    )
    return FaceStatus(
        enrolled=True,
        enrolled_at=rows[0].created_at,
        enrolled_by=kiosk or rows[0].enrolled_by,
        samples=len(rows),
    )


@router.post(
    "/ticket",
    response_model=EnrolmentTicket,
    status_code=201,
    summary="Let a kiosk enrol your face",
    description=(
        "Returns a single-use ticket to show the kiosk as a QR code. It names "
        "you to the kiosk, which otherwise has nobody it may enrol. Expires in "
        f"{settings.iden_face_ticket_ttl // 60} minutes, allows "
        f"{tickets.MAX_ATTEMPTS} capture attempts, and replaces any ticket you "
        "asked for earlier. Enrolling replaces a face already on file.\n\n"
        + FRESHNESS
        + "**Required scope:** `entity:face:write`"
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Sign-in is not recent enough"}
    },
    dependencies=[WRITE, FRESH],
)
async def create_ticket(user: CurrentUserDep, redis: RedisDep) -> EnrolmentTicket:
    ticket, expires_at = await tickets.issue(redis, user.id)
    return EnrolmentTicket(ticket=ticket, expires_at=expires_at)


@router.delete(
    "",
    status_code=204,
    summary="Remove your face",
    description=(
        "Deletes every face sample on file, and any enrolment photos kept with "
        "them. Face is no longer offered when you sign in.\n\n"
        + FRESHNESS
        + "**Required scope:** `entity:face:write`"
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Sign-in is not recent enough"}
    },
    dependencies=[WRITE, FRESH],
)
async def remove(
    user: CurrentUserDep, session: DBSessionDep, storage: FaceStorageDep
) -> Response:
    await service.remove(session, storage, user.id)
    return Response(status_code=204)
