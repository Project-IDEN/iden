"""Enrolment kiosks: registering them, pairing a device, configuring, revoking.

Each kiosk signs in as a client of its own, created here and holding the
`biometric:` scopes. Only this module changes those clients; `/admin/clients`
refuses to.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from provider.admin.kiosks import service
from provider.admin.kiosks.schemas import (
    KioskCreate,
    KioskCreated,
    KioskEnrolmentEvent,
    KioskResponse,
    KioskUpdate,
    PairingCode,
)
from provider.biometric import pairing
from provider.biometric.deps import require_biometric
from provider.core.auth import require_scope
from provider.core.config import settings
from provider.core.db import DBSessionDep
from provider.core.redis import RedisDep
from provider.core.schemas import ErrorResponse, Page, PageMeta, PaginationDep
from provider.shared.models import Kiosk
from provider.shared.scopes import BIOMETRIC_SCOPES

router = APIRouter(
    prefix="/admin/kiosks",
    tags=["admin: kiosks"],
    dependencies=[Depends(require_biometric)],
    include_in_schema=settings.iden_biometric_enabled,
)

READ = Depends(require_scope("admin:kiosks:read"))
WRITE = Depends(require_scope("admin:kiosks:write"))
# Creating a kiosk or pairing one hands a device the `biometric:` scopes, so the
# caller must hold them — the rule `admin.delegation` applies to grants.
ISSUE = Depends(
    require_scope("admin:kiosks:write", *(s.value for s in BIOMETRIC_SCOPES))
)
ISSUE_NOTE = (
    "**Required scope:** `admin:kiosks:write`, plus every `biometric:` scope — "
    "the device it pairs will hold them."
)

NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No such kiosk"}
}


def to_response(kiosk: Kiosk) -> KioskResponse:
    return KioskResponse(
        id=kiosk.id,
        client_id=kiosk.client.client_id,
        name=kiosk.client.name,
        location=kiosk.location,
        status=service.status_of(kiosk),
        settings=service.settings_of(kiosk),
        paired_at=kiosk.paired_at,
        last_seen_at=kiosk.last_seen_at,
        last_seen_version=kiosk.last_seen_version,
        last_seen_camera=kiosk.last_seen_camera,
        last_seen_address=kiosk.last_seen_address,
        created_at=kiosk.created_at,
    )


@router.get(
    "",
    response_model=Page[KioskResponse],
    summary="List enrolment kiosks",
    description="With each one's status and last report.\n\n"
    "**Required scope:** `admin:kiosks:read`",
    dependencies=[READ],
)
async def list_kiosks(
    session: DBSessionDep, page: PaginationDep
) -> Page[KioskResponse]:
    kiosks, total = await service.list_kiosks(
        session, limit=page.limit, offset=page.offset
    )
    return Page[KioskResponse](
        items=[to_response(kiosk) for kiosk in kiosks],
        meta=PageMeta(total=total, limit=page.limit, offset=page.offset),
    )


@router.post(
    "",
    response_model=KioskCreated,
    status_code=201,
    summary="Register a kiosk",
    description=(
        "Creates the kiosk and the client it will sign in as, and returns a "
        "**pairing code**. Enter or scan the code on the device: it receives its "
        f"own secret, once. The code lasts {settings.iden_kiosk_pairing_ttl // 60} "
        "minutes and works once.\n\n" + ISSUE_NOTE
    ),
    dependencies=[ISSUE],
)
async def create_kiosk(
    body: KioskCreate, session: DBSessionDep, redis: RedisDep
) -> KioskCreated:
    kiosk = await service.create_kiosk(session, body)
    code, expires_at = await pairing.issue(redis, kiosk.id)
    return KioskCreated(
        **to_response(kiosk).model_dump(),
        pairing=PairingCode(code=code, expires_at=expires_at),
    )


@router.get(
    "/{kiosk_id}",
    response_model=KioskResponse,
    summary="Read a kiosk",
    description="**Required scope:** `admin:kiosks:read`",
    responses=NOT_FOUND,
    dependencies=[READ],
)
async def read_kiosk(kiosk_id: UUID, session: DBSessionDep) -> KioskResponse:
    return to_response(await service.get_kiosk(session, kiosk_id))


@router.patch(
    "/{kiosk_id}",
    response_model=KioskResponse,
    summary="Rename, move, or configure a kiosk",
    description=(
        "Settings reach the device at its next heartbeat, within a minute. "
        "`inService: false` takes effect at once on IDEN's side: its enrolments "
        "are refused.\n\n**Required scope:** `admin:kiosks:write`"
    ),
    responses=NOT_FOUND,
    dependencies=[WRITE],
)
async def update_kiosk(
    kiosk_id: UUID, body: KioskUpdate, session: DBSessionDep
) -> KioskResponse:
    return to_response(await service.update_kiosk(session, kiosk_id, body))


@router.post(
    "/{kiosk_id}/pairing-code",
    response_model=PairingCode,
    status_code=201,
    summary="Pair a device again",
    description=(
        "For a replaced or reinstalled device. Any earlier code stops working. "
        "When the new device pairs, the old one is signed out for good: the "
        "secret it held is replaced.\n\n" + ISSUE_NOTE
    ),
    responses=NOT_FOUND,
    dependencies=[ISSUE],
)
async def new_pairing_code(
    kiosk_id: UUID, session: DBSessionDep, redis: RedisDep
) -> PairingCode:
    kiosk = await service.get_kiosk(session, kiosk_id)
    code, expires_at = await pairing.issue(redis, kiosk.id)
    return PairingCode(code=code, expires_at=expires_at)


@router.delete(
    "/{kiosk_id}",
    status_code=204,
    response_class=Response,
    summary="Revoke a kiosk",
    description=(
        "Deletes the kiosk and its client. The device stops at once — enrolment "
        "refuses it even while its last access token is unexpired. Faces it "
        "enrolled stay enrolled.\n\n**Required scope:** `admin:kiosks:write`"
    ),
    responses=NOT_FOUND,
    dependencies=[WRITE],
)
async def delete_kiosk(kiosk_id: UUID, session: DBSessionDep) -> Response:
    await service.delete_kiosk(session, kiosk_id)
    return Response(status_code=204)


@router.get(
    "/{kiosk_id}/enrolments",
    response_model=Page[KioskEnrolmentEvent],
    summary="What a kiosk enrolled",
    description=(
        "Every enrolment this kiosk attempted, newest first, and why the failed "
        "ones failed. Read from the audit log.\n\n"
        "**Required scope:** `admin:kiosks:read`"
    ),
    responses=NOT_FOUND,
    dependencies=[READ],
)
async def list_enrolments(
    kiosk_id: UUID, session: DBSessionDep, page: PaginationDep
) -> Page[KioskEnrolmentEvent]:
    events, total = await service.enrolments(
        session, kiosk_id, limit=page.limit, offset=page.offset
    )
    return Page[KioskEnrolmentEvent](
        items=events, meta=PageMeta(total=total, limit=page.limit, offset=page.offset)
    )
