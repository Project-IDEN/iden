"""The kiosk server against a stand-in IDEN.

IDEN is an `httpx.MockTransport` that answers the handful of routes a kiosk
uses, and records what it was sent.
"""

import json
import stat
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from kiosk_server import credentials
from kiosk_server.config import settings


class FakeIden:
    def __init__(self) -> None:
        self.secret = "s3cret"
        self.pairing_code = "ABCD-EFGH"
        self.tokens_issued = 0
        self.valid_tokens: set[str] = set()
        self.revoked = False
        self.reachable = True
        # Answers the token endpoint with this instead, when set.
        self.token_failure: httpx.Response | None = None
        self.requests: list[httpx.Request] = []
        self.heartbeats: list[dict] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if not self.reachable:
            raise httpx.ConnectError("down", request=request)
        self.requests.append(request)
        path = request.url.path

        if path == "/biometric/kiosk/pair":
            if json.loads(request.content)["code"] != self.pairing_code:
                return httpx.Response(404, json={"code": "pairing_code_invalid"})
            return httpx.Response(
                200,
                json={
                    "clientId": "kiosk-abc",
                    "clientSecret": self.secret,
                    "name": "Library Kiosk 2",
                },
            )

        if path == "/oauth2/token":
            if self.token_failure is not None:
                return self.token_failure
            form = dict(httpx.QueryParams(request.content.decode()))
            if self.revoked or form["client_secret"] != self.secret:
                return httpx.Response(401, json={"error": "invalid_client"})
            self.tokens_issued += 1
            token = f"token-{self.tokens_issued}"
            self.valid_tokens.add(token)
            return httpx.Response(200, json={"access_token": token, "expires_in": 600})

        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in self.valid_tokens:
            return httpx.Response(401, json={"code": "unauthorized"})

        if path == "/biometric/kiosk/heartbeat":
            self.heartbeats.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "name": "Library Kiosk 2",
                    "location": "Level 1",
                    "settings": {"idleSeconds": 45, "inService": True},
                    "heartbeatSeconds": 60,
                },
            )
        if path == "/biometric/enroll/challenge":
            if json.loads(request.content)["ticket"] != "good-ticket":
                return httpx.Response(404, json={"code": "enrolment_ticket_invalid"})
            return httpx.Response(
                200,
                json={"faceChallengeId": "c1", "steps": ["center"], "attemptsLeft": 4},
            )
        if path == "/biometric/enroll":
            return httpx.Response(
                422, json={"code": "poor_capture", "details": {"reasons": ["too_dark"]}}
            )
        return httpx.Response(404)


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "kiosk_data_dir", tmp_path)
    return tmp_path


@pytest.fixture
def iden() -> FakeIden:
    return FakeIden()


@pytest.fixture
def kiosk(iden) -> Iterator[TestClient]:
    from kiosk_server.app import create_app

    app = create_app(httpx.MockTransport(iden.handle))
    with TestClient(app, base_url="http://localhost") as client:
        yield client


@pytest.fixture
def paired(kiosk, iden) -> TestClient:
    assert kiosk.post("/api/pair", json={"code": iden.pairing_code}).status_code == 200
    return kiosk


def test_an_unpaired_kiosk_says_so_and_refuses_to_enrol(kiosk):
    assert kiosk.get("/api/state").json()["paired"] is False
    response = kiosk.post("/api/enrol/start", json={"ticket": "good-ticket"})
    assert response.status_code == 409
    assert response.json()["code"] == "not_paired"


def test_pairing_keeps_the_secret_on_disk_for_the_owner_alone(paired, data_dir):
    path = data_dir / "credentials.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["clientSecret"] == "s3cret"
    state = paired.get("/api/state").json()
    assert state["paired"] is True
    assert state["name"] == "Library Kiosk 2"


def test_a_wrong_code_is_passed_through(kiosk):
    response = kiosk.post("/api/pair", json={"code": "nope"})
    assert response.status_code == 404
    assert response.json()["code"] == "pairing_code_invalid"
    assert credentials.load() is None


def test_the_secret_never_reaches_the_ui(paired):
    assert "s3cret" not in paired.get("/api/state").text


def test_the_token_is_reused_until_it_nears_expiry(paired, iden):
    for _ in range(3):
        paired.post("/api/enrol/start", json={"ticket": "good-ticket"})
    assert iden.tokens_issued == 1


def test_a_revoked_token_is_replaced_once(paired, iden):
    paired.post("/api/enrol/start", json={"ticket": "good-ticket"})
    iden.valid_tokens.clear()

    response = paired.post("/api/enrol/start", json={"ticket": "good-ticket"})
    assert response.status_code == 200
    assert iden.tokens_issued == 2


def test_a_revoked_kiosk_forgets_its_credentials(paired, iden, data_dir):
    iden.revoked = True
    iden.valid_tokens.clear()

    response = paired.post("/api/enrol/start", json={"ticket": "good-ticket"})
    assert response.status_code == 409
    assert paired.get("/api/state").json()["paired"] is False
    assert not (data_dir / "credentials.json").exists()


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(400, json={"error": "invalid_scope"}),
        httpx.Response(500, text="Internal Server Error"),
    ],
)
def test_a_token_failure_that_is_not_a_revocation_keeps_the_pairing(
    paired, iden, data_dir, failure
):
    iden.token_failure = failure
    iden.valid_tokens.clear()

    response = paired.post("/api/enrol/start", json={"ticket": "good-ticket"})
    assert response.status_code == 503
    assert response.json()["code"] == "iden_unreachable"
    assert (data_dir / "credentials.json").exists()
    assert paired.get("/api/state").json()["online"] is False


def test_iden_is_not_called_unreachable_before_it_was_asked(kiosk):
    assert kiosk.get("/api/state").json()["online"] is None


def test_iden_errors_reach_the_ui_unchanged(paired):
    start = paired.post("/api/enrol/start", json={"ticket": "used"})
    assert start.status_code == 404
    assert start.json()["code"] == "enrolment_ticket_invalid"

    response = paired.post(
        "/api/enrol",
        data={"ticket": "good-ticket", "faceChallengeId": "c1"},
        files=[("frames", ("0.jpg", b"\xff\xd8 one", "image/jpeg"))],
    )
    assert response.status_code == 422
    assert response.json()["details"]["reasons"] == ["too_dark"]


def test_frames_are_forwarded_in_order(paired, iden):
    paired.post(
        "/api/enrol",
        data={"ticket": "good-ticket", "faceChallengeId": "c1"},
        files=[
            ("frames", (f"{i}.jpg", b"frame-%d" % i, "image/jpeg")) for i in range(3)
        ],
    )
    sent = iden.requests[-1].content
    assert sent.index(b"frame-0") < sent.index(b"frame-1") < sent.index(b"frame-2")
    assert b'name="faceChallengeId"' in sent


def test_too_many_frames_are_refused_here(paired, iden):
    response = paired.post(
        "/api/enrol",
        data={"ticket": "good-ticket", "faceChallengeId": "c1"},
        files=[("frames", (f"{i}.jpg", b"x", "image/jpeg")) for i in range(17)],
    )
    assert response.status_code == 422
    assert not any(r.url.path == "/biometric/enroll" for r in iden.requests)


def test_unreachable_iden_is_a_503(paired, iden):
    iden.reachable = False
    response = paired.post("/api/enrol/start", json={"ticket": "good-ticket"})
    assert response.status_code == 503
    assert response.json()["code"] == "iden_unreachable"


def test_another_host_is_refused(kiosk):
    response = kiosk.get("/api/state", headers={"host": "evil.example"})
    assert response.status_code == 400


@pytest.mark.anyio
async def test_a_heartbeat_reports_the_camera_and_reads_the_settings(iden):
    from kiosk_server.device import Device

    async with httpx.AsyncClient(
        base_url="http://iden", transport=httpx.MockTransport(iden.handle)
    ) as http:
        device = Device(http)
        await device.pair(iden.pairing_code)
        device.camera = "Rapoo C280"
        await device.heartbeat()

    assert iden.heartbeats[-1] == {"softwareVersion": "dev", "camera": "Rapoo C280"}
    state = device.state()
    assert state.settings["idleSeconds"] == 45
    assert state.location == "Level 1"
    assert state.online is True


@pytest.fixture
def anyio_backend():
    return "asyncio"
