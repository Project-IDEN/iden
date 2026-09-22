from fastapi import APIRouter, Depends, Response

from provider.core.auth import CurrentUserDep, require_fresh_auth, require_scope
from provider.core.db import DBSessionDep
from provider.core.schemas import ErrorResponse
from provider.entity.totp import service
from provider.entity.totp.schemas import TotpConfirm, TotpEnrollment, TotpStatus

router = APIRouter(prefix="/entity/totp", tags=["entity: totp"])

READ = Depends(require_scope("entity:totp:read"))
ENROLL = Depends(require_scope("entity:totp:enroll"))
FRESH = Depends(require_fresh_auth(max_age=300))

FRESHNESS = (
    "**Needs a recent sign-in.** Enrolling is not a smaller act than removing. "
    "Once a confirmed authenticator exists it is owed at *every* subsequent "
    "sign-in, whatever the application asked for — so somebody holding a stolen "
    "access token could enrol one of their own and lock the account's owner out "
    "for good: the owner cannot produce the code, a password reset does not "
    "clear the credential, and removing it needs the recent sign-in they can no "
    "longer complete. The refusal is RFC 9470's "
    "`insufficient_user_authentication` with the `max_age` that would satisfy "
    "it.\n\n"
)


@router.get(
    "",
    response_model=TotpStatus,
    summary="Is an authenticator set up?",
    description=(
        "`enrolled` is true only once a generated code has been confirmed — a "
        "half-finished enrollment is not an authenticator.\n\n"
        "**Required scope:** `entity:totp:read`"
    ),
    dependencies=[READ],
)
async def read_status(user: CurrentUserDep, session: DBSessionDep) -> TotpStatus:
    credential = await service.status(session, user)
    return TotpStatus(
        enrolled=credential is not None,
        confirmed_at=credential.confirmed_at if credential else None,
    )


@router.post(
    "/enroll",
    response_model=TotpEnrollment,
    status_code=201,
    summary="Start setting up an authenticator",
    description=(
        "Returns a secret and an `otpauth://` URI to render as a QR code. "
        "Nothing is active yet: `POST /entity/totp/confirm` with a generated "
        "code finishes it. Two steps on purpose — a mis-scanned QR code would "
        "otherwise lock someone out of their own account.\n\n"
        + FRESHNESS
        + "**Required scope:** `entity:totp:enroll`"
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Sign-in is not recent enough"},
        409: {"model": ErrorResponse, "description": "Already enrolled"},
    },
    dependencies=[ENROLL, FRESH],
)
async def enroll(user: CurrentUserDep, session: DBSessionDep) -> TotpEnrollment:
    secret, uri = await service.begin(session, user)
    return TotpEnrollment(secret=secret, uri=uri)


@router.post(
    "/confirm",
    response_model=TotpStatus,
    summary="Finish setting up an authenticator",
    description=(
        "Proves the app was scanned correctly and is keeping the right time.\n\n"
        + FRESHNESS
        + "**Required scope:** `entity:totp:enroll`"
    ),
    responses={
        403: {"model": ErrorResponse, "description": "Sign-in is not recent enough"},
        404: {"model": ErrorResponse, "description": "Nothing pending to confirm"},
        422: {"model": ErrorResponse, "description": "Wrong code"},
    },
    dependencies=[ENROLL, FRESH],
)
async def confirm(
    body: TotpConfirm, user: CurrentUserDep, session: DBSessionDep
) -> TotpStatus:
    credential = await service.confirm(session, user, body.code)
    return TotpStatus(enrolled=True, confirmed_at=credential.confirmed_at)


@router.delete(
    "",
    status_code=204,
    summary="Remove your authenticator",
    description=(
        "**Needs a recent sign-in.** Removing a second factor is the step an "
        "attacker with a stolen token would take first, so it demands the one "
        "thing they cannot do — see RFC 9470 and `max_age` on `/authorize`.\n\n"
        "**Required scope:** `entity:totp:enroll`"
    ),
    responses={403: {"model": ErrorResponse, "description": "Sign-in is not recent"}},
    dependencies=[ENROLL, FRESH],
)
async def remove(user: CurrentUserDep, session: DBSessionDep) -> Response:
    await service.remove(session, user)
    return Response(status_code=204)
