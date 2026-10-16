"""The provider's side of the engine's wire format.

The engine is the only component that ever sees a photo. Everything here is
the request that carries them there and the verdict that comes back.
"""

import json
from functools import cache
from typing import Annotated, Literal, Protocol

import httpx
from fastapi import Depends
from pydantic import BaseModel

from provider.biometric.errors import BadFrames, EngineUnavailable
from provider.core.config import settings
from provider.core.logging import logger

Reason = Literal[
    "no_face",
    "multiple_faces",
    "too_small",
    "blurred",
    "too_dark",
    "too_bright",
    "off_angle",
    "out_of_frame",
]


class Checks(BaseModel):
    anti_spoofing: bool
    anti_spoofing_score: float
    actions: bool
    actions_score: float = 0.0
    consistent: bool
    consistency_score: float = 0.0

    def scores(self) -> dict[str, float]:
        return {
            "antiSpoofing": round(self.anti_spoofing_score, 3),
            "actions": round(self.actions_score, 3),
            "consistency": round(self.consistency_score, 3),
        }

    def failed(self) -> list[str]:
        return [
            name
            for name in ("anti_spoofing", "actions", "consistent")
            if not getattr(self, name)
        ]


class Capture(BaseModel):
    usable: bool
    reasons: list[Reason]
    checks: Checks | None = None
    live: bool = False
    model_version: str


class EnrollResult(Capture):
    embeddings: list[list[float]] = []
    qualities: list[float] = []
    sources: list[int] = []


class VerifyResult(Capture):
    matched: bool = False
    similarity: float = 0.0


class EmbedResult(BaseModel):
    model_version: str
    embeddings: list[list[float] | None]


class EngineInfo(BaseModel):
    model_version: str
    device: str
    calibrated: bool


class Engine(Protocol):
    async def info(self) -> EngineInfo: ...

    async def enroll(self, frames: list[bytes], steps: list[str]) -> EnrollResult: ...

    async def verify(
        self, frames: list[bytes], steps: list[str], templates: list[list[float]]
    ) -> VerifyResult: ...

    async def embed(self, frames: list[bytes]) -> EmbedResult: ...


@cache
def _token() -> str | None:
    path = settings.engine_token_path
    return path.read_text().strip() if path.is_file() else None


# One for the process, so a face check reuses a pooled connection rather than
# opening a new one to the engine. Closed in the app's lifespan.
client = httpx.AsyncClient(
    base_url=settings.iden_engine_base_url, timeout=settings.iden_engine_timeout
)


class HttpEngine:
    async def _request[R: BaseModel](
        self,
        method: str,
        path: str,
        kind: type[R],
        frames: list[bytes] | None = None,
        meta: dict | None = None,
    ) -> R:
        token = _token()
        files = [
            ("frames", (f"{i}.jpg", frame, "image/jpeg"))
            for i, frame in enumerate(frames or [])
        ]
        try:
            response = await client.request(
                method,
                path,
                files=files or None,
                data={"meta": json.dumps(meta)} if meta is not None else None,
                headers={"Authorization": f"Bearer {token}"} if token else None,
            )
        except httpx.HTTPError as exc:
            logger.error("Engine unreachable", path=path, error=type(exc).__name__)
            raise EngineUnavailable from exc

        # The engine refuses frames it cannot read or that do not match the
        # steps — the caller's fault, not the engine's.
        if response.status_code in (400, 413):
            raise BadFrames(response.json().get("detail") or BadFrames.message)
        if response.status_code != 200:
            logger.error("Engine refused", path=path, status=response.status_code)
            raise EngineUnavailable
        return kind.model_validate(response.json())

    async def info(self) -> EngineInfo:
        return await self._request("GET", "/info", EngineInfo)

    async def enroll(self, frames: list[bytes], steps: list[str]) -> EnrollResult:
        return await self._request(
            "POST", "/enroll", EnrollResult, frames, {"steps": steps}
        )

    async def verify(
        self, frames: list[bytes], steps: list[str], templates: list[list[float]]
    ) -> VerifyResult:
        return await self._request(
            "POST",
            "/verify",
            VerifyResult,
            frames,
            {"steps": steps, "templates": templates},
        )

    async def embed(self, frames: list[bytes]) -> EmbedResult:
        return await self._request("POST", "/embed", EmbedResult, frames)


def get_engine() -> Engine:
    return HttpEngine()


EngineDep = Annotated[Engine, Depends(get_engine)]
