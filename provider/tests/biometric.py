"""What the face tests share: a fake engine and the requests a face flow makes.

The fixtures built on these live in conftest.py.
"""

from provider.biometric import consent
from provider.biometric.engine_client import (
    Checks,
    EmbedResult,
    EngineInfo,
    EnrollResult,
    VerifyResult,
)
from tests.flows import pkce_pair, query_of, start

VERSION = "test-model-1"
LIVE = Checks(
    anti_spoofing=True,
    anti_spoofing_score=0.97,
    actions=True,
    consistent=True,
)
SPOOF = LIVE.model_copy(update={"anti_spoofing": False, "actions": False})
VECTORS = [[0.1, 0.2, 0.3, 0.4], [0.2, 0.1, 0.4, 0.3], [0.3, 0.3, 0.2, 0.2]]


class FakeEngine:
    def __init__(self) -> None:
        self.enroll_result = EnrollResult(
            usable=True,
            reasons=[],
            checks=LIVE,
            live=True,
            model_version=VERSION,
            embeddings=VECTORS,
            qualities=[3.0, 2.0, 1.0],
            sources=[0, 2, 1],
        )
        self.verify_result = VerifyResult(
            usable=True,
            reasons=[],
            checks=LIVE,
            live=True,
            model_version=VERSION,
            matched=True,
            similarity=0.83,
        )
        self.calls: list[tuple[str, int, list[str]]] = []
        self.templates_seen: list[list[float]] = []

    async def enroll(self, frames, steps):
        self.calls.append(("enroll", len(frames), steps))
        return self.enroll_result

    async def verify(self, frames, steps, templates):
        self.calls.append(("verify", len(frames), steps))
        self.templates_seen = templates
        return self.verify_result

    async def info(self):
        return EngineInfo(model_version=VERSION, device="cpu", calibrated=False)

    async def embed(self, frames):
        self.calls.append(("embed", len(frames), []))
        return EmbedResult(
            model_version=VERSION,
            embeddings=[
                None if b"blank" in f else [0.9, 0.1, 0.0, 0.0] for f in frames
            ],
        )


def frames(count: int) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("frames", (f"{i}.jpg", b"\xff\xd8 frame %d" % i, "image/jpeg"))
        for i in range(count)
    ]


async def new_ticket(client, face_headers) -> str:
    response = await client.post("/entity/face/ticket", headers=face_headers)
    assert response.status_code == 201
    return response.json()["ticket"]


async def kiosk_capture(client, kiosk_headers, ticket: str):
    response = await client.post(
        "/biometric/enroll/challenge", headers=kiosk_headers, json={"ticket": ticket}
    )
    return response


async def enrol_at_kiosk(client, kiosk_headers, face_headers):
    ticket = await new_ticket(client, face_headers)
    challenge = (await kiosk_capture(client, kiosk_headers, ticket)).json()
    return await client.post(
        "/biometric/enroll",
        headers=kiosk_headers,
        data={
            "ticket": ticket,
            "faceChallengeId": challenge["faceChallengeId"],
            "consent": consent.version(),
        },
        files=frames(len(challenge["steps"])),
    )


async def begin(client, **params) -> str:
    _, challenge = pkce_pair()
    return query_of(await start(client, challenge, **params))["challenge"]


async def face_step(client, challenge_id: str, count: int | None = None):
    issued = await client.post(
        "/api/v1/auth/biometric/challenge", json={"challengeId": challenge_id}
    )
    assert issued.status_code == 200, issued.text
    body = issued.json()
    return await client.post(
        "/api/v1/auth/biometric",
        data={"challengeId": challenge_id, "faceChallengeId": body["faceChallengeId"]},
        files=frames(count or len(body["steps"])),
    )
