"""The engine's HTTP surface. Reachable only from inside the deployment.

Stateless: no database, no blob store, no idea who anybody is. The provider
sends frames — and, to verify, the templates to compare against — and receives
verdicts. Nothing sent here outlives the request.
"""

import secrets
from contextlib import asynccontextmanager
from typing import Annotated

import numpy as np
import uvicorn
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import ValidationError

from engine import manifest as manifest_module
from engine import pipeline, runtime
from engine.config import settings
from engine.imaging import InvalidImage, decode
from engine.log import configure_logging, logger
from engine.schemas import EnrollResult, Info, Meta, VerifyMeta, VerifyResult
from engine.steps import is_valid

configure_logging()

_state: dict[str, runtime.Models] = {}


def models() -> runtime.Models:
    loaded = _state.get("models")
    if loaded is None:
        raise HTTPException(status_code=503, detail="Models are not loaded.")
    return loaded


def _warm_up(loaded: runtime.Models) -> None:
    """One inference per model, so the first person to sign in after a restart
    does not wait for CUDA to initialise."""
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    pipeline.detect(
        loaded.detector,
        blank,
        loaded.manifest.detector.input_size,
        loaded.manifest.detector.score_threshold,
    )
    pipeline.embed(loaded.recognizer, [blank[:112, :112]], 127.5, 127.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.engine_env == "prod" and settings.token() is None:
        raise RuntimeError("ENGINE_TOKEN_FILE must name a non-empty file in prod.")

    manifest = manifest_module.load(settings.engine_manifest)
    loaded = runtime.load(manifest, settings.engine_model_dir, settings.engine_device)
    _warm_up(loaded)
    _state["models"] = loaded
    logger.info(
        "Engine ready",
        model_version=manifest.version,
        device=loaded.device,
        calibrated=manifest.recognizer.calibrated,
    )
    yield
    _state.clear()


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = settings.token()
    if expected is None:
        return
    presented = (authorization or "").removeprefix("Bearer ")
    if not secrets.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unknown caller.")


AUTH = [Depends(require_token)]

app = FastAPI(
    title="IDEN Biometric Engine",
    version="0.0.1",
    description="Internal. Face detection, quality, anti-spoofing and 1:1 matching.",
    lifespan=lifespan,
    docs_url="/docs" if settings.engine_env != "prod" else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.engine_env != "prod" else None,
)


def _frames(frames: list[UploadFile], steps: list[str]) -> list[np.ndarray]:
    if not frames or len(frames) > settings.engine_max_frames:
        raise HTTPException(status_code=400, detail="Wrong number of frames.")
    if len(frames) != len(steps) or not all(is_valid(step) for step in steps):
        raise HTTPException(status_code=400, detail="Steps do not describe the frames.")

    images = []
    for frame in frames:
        data = frame.file.read(settings.engine_max_frame_bytes + 1)
        if len(data) > settings.engine_max_frame_bytes:
            raise HTTPException(status_code=413, detail="A frame is too large.")
        try:
            images.append(decode(data, settings.engine_max_pixels))
        except InvalidImage as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return images


def _meta[M: Meta](kind: type[M], raw: str) -> M:
    try:
        return kind.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Malformed meta.") from exc


@app.post("/enroll", response_model=EnrollResult, dependencies=AUTH)
def enroll(
    frames: Annotated[list[UploadFile], File()],
    meta: Annotated[str, Form()],
) -> EnrollResult:
    steps = _meta(Meta, meta).steps
    return pipeline.enroll(models(), _frames(frames, steps), steps)


@app.post("/verify", response_model=VerifyResult, dependencies=AUTH)
def verify(
    frames: Annotated[list[UploadFile], File()],
    meta: Annotated[str, Form()],
) -> VerifyResult:
    parsed = _meta(VerifyMeta, meta)
    return pipeline.verify(
        models(), _frames(frames, parsed.steps), parsed.steps, parsed.templates
    )


@app.get("/info", response_model=Info, dependencies=AUTH)
def info() -> Info:
    loaded = models()
    return Info(
        model_version=loaded.manifest.version,
        device=loaded.device,
        providers=loaded.providers,
        calibrated=loaded.manifest.recognizer.calibrated,
        match_threshold=loaded.manifest.recognizer.match_threshold,
    )


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
def ready() -> dict[str, str]:
    models()
    return {"status": "ready"}


def main() -> None:
    uvicorn.run(
        "engine.app:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,
        workers=settings.engine_workers,
    )
