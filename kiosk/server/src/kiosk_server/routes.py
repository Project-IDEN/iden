"""The kiosk UI's API. Served on localhost only, to the browser on this device.

What IDEN answers is passed through as it came — status and body — so the UI
reads IDEN's own error codes (`poor_capture`, `not_live`, …) and this process
need not translate them.
"""

import json
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from kiosk_server.device import Device, NotPaired, Unreachable
from kiosk_server.logging import logger
from kiosk_server.schemas import CameraReport, KioskState, PairRequest, TicketRequest

router = APIRouter(prefix="/api", tags=["kiosk"])

# Thirteen frames are asked for; a 640×480 JPEG is well under the limit each.
MAX_FRAMES = 16
MAX_FRAME_BYTES = 300_000


def get_device(request: Request) -> Device:
    return request.app.state.device


DeviceDep = Annotated[Device, Depends(get_device)]


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


def _relay(response: httpx.Response) -> Response:
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "application/json"),
    )


async def _as_kiosk(device: Device, method: str, path: str, **kwargs) -> Response:
    try:
        return _relay(await device.call(method, path, **kwargs))
    except NotPaired:
        return _error(409, "not_paired", "This kiosk is not paired.")
    except Unreachable:
        return _error(503, "iden_unreachable", "IDEN cannot be reached.")


@router.get("/state", response_model=KioskState, summary="This kiosk's state")
async def state(device: DeviceDep) -> KioskState:
    return device.state()


@router.post(
    "/pair",
    response_model=KioskState,
    summary="Pair with the code from the dashboard",
    responses={404: {"description": "Code expired or already used"}},
)
async def pair(body: PairRequest, request: Request, device: DeviceDep) -> Response:
    try:
        response = await device.pair(body.code)
    except Unreachable:
        return _error(503, "iden_unreachable", "IDEN cannot be reached.")
    if response.status_code != 200:
        return _relay(response)
    request.app.state.wake.set()
    return JSONResponse(device.state().model_dump(mode="json"))


@router.post(
    "/camera",
    status_code=204,
    response_class=Response,
    summary="Report which camera the UI opened",
)
async def camera(body: CameraReport, device: DeviceDep) -> Response:
    device.camera = body.camera
    return Response(status_code=204)


@router.post("/enrol/start", summary="Read a ticket and start a capture")
async def start_enrolment(body: TicketRequest, device: DeviceDep) -> Response:
    return await _as_kiosk(
        device, "POST", "/biometric/enroll/challenge", json={"ticket": body.ticket}
    )


@router.post("/enrol", summary="Send a capture to be enrolled")
async def enrol(
    device: DeviceDep,
    ticket: Annotated[str, Form()],
    face_challenge_id: Annotated[str, Form(alias="faceChallengeId")],
    frames: Annotated[list[UploadFile], File()],
) -> Response:
    if not 0 < len(frames) <= MAX_FRAMES:
        return _error(422, "invalid_frames", "Wrong number of frames.")
    files = []
    for index, frame in enumerate(frames):
        data = await frame.read(MAX_FRAME_BYTES + 1)
        if len(data) > MAX_FRAME_BYTES:
            return _error(422, "invalid_frames", "A frame is too large.")
        files.append(
            ("frames", (f"{index}.jpg", data, frame.content_type or "image/jpeg"))
        )

    response = await _as_kiosk(
        device,
        "POST",
        "/biometric/enroll",
        data={"ticket": ticket, "faceChallengeId": face_challenge_id},
        files=files,
    )
    _log_outcome(response)
    return response


def _log_outcome(response: Response) -> None:
    """What the engine made of a capture — the light, the camera, the checks
    that failed — for whoever is tuning this kiosk. Nothing about the person."""
    if response.status_code < 400:
        logger.info("Enrolment accepted")
        return
    try:
        body = json.loads(bytes(response.body))
    except ValueError:
        body = {}
    logger.warning(
        "Enrolment refused",
        status=response.status_code,
        code=body.get("code"),
        details=body.get("details") or None,
    )
