import json
import threading

import cv2
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from engine import app as app_module
from engine.config import settings
from tests.conftest import MANIFEST, needs_models

TOKEN = "engine-test-token"


@pytest.fixture
def client(tmp_path, monkeypatch, face_image):
    token_file = tmp_path / "engine.token"
    token_file.write_text(TOKEN)
    monkeypatch.setattr(settings, "engine_token_file", token_file)
    monkeypatch.setattr(settings, "engine_device", "cpu")
    with TestClient(app_module.app) as test_client:
        yield test_client


def _upload(image, count):
    _, encoded = cv2.imencode(".jpg", image)
    return [
        ("frames", (f"{i}.jpg", encoded.tobytes(), "image/jpeg")) for i in range(count)
    ]


AUTH = {"Authorization": f"Bearer {TOKEN}"}


@needs_models
def test_a_caller_without_the_token_is_refused(client, face_image):
    response = client.post(
        "/enroll",
        files=_upload(face_image, 3),
        data={"meta": json.dumps({"steps": ["center"] * 3})},
    )
    assert response.status_code == 401
    assert client.get("/info").status_code == 401


@needs_models
def test_info_reports_the_model_and_device(client):
    body = client.get("/info", headers=AUTH).json()
    assert body["model_version"] == MANIFEST.version
    assert body["device"] == "cpu"
    assert body["calibrated"] is False


@needs_models
def test_steps_must_describe_every_frame(client, face_image):
    response = client.post(
        "/enroll",
        headers=AUTH,
        files=_upload(face_image, 3),
        data={"meta": json.dumps({"steps": ["center", "frown", "center"]})},
    )
    assert response.status_code == 400
    response = client.post(
        "/enroll",
        headers=AUTH,
        files=_upload(face_image, 3),
        data={"meta": json.dumps({"steps": ["center"] * 2})},
    )
    assert response.status_code == 400


@needs_models
def test_something_that_is_not_an_image_is_refused(client):
    response = client.post(
        "/enroll",
        headers=AUTH,
        files=[("frames", ("x.jpg", b"not an image", "image/jpeg"))],
        data={"meta": json.dumps({"steps": ["center"]})},
    )
    assert response.status_code == 400


@needs_models
def test_verify_compares_against_the_templates_sent(client, face_image):
    from engine import pipeline

    analysis = pipeline.analyse(app_module.models(), [face_image] * 3, ["center"] * 3)
    assert analysis.reference is not None
    response = client.post(
        "/verify",
        headers=AUTH,
        files=_upload(face_image, 3),
        data={
            "meta": json.dumps(
                {"steps": ["center"] * 3, "templates": [analysis.reference.tolist()]}
            )
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["usable"] and body["matched"]


@needs_models
def test_a_template_of_the_wrong_width_is_refused(client, face_image):
    """From another model, or truncated on the way: refused, not a 500."""
    response = client.post(
        "/verify",
        headers=AUTH,
        files=_upload(face_image, 3),
        data={"meta": json.dumps({"steps": ["center"] * 3, "templates": [[0.1] * 3]})},
    )

    assert response.status_code == 400


class TestATokenThatGoesMissing:
    """Startup refuses prod without a token, but the file is read per request:
    emptied afterwards, it must close the engine, not open it."""

    def test_prod_refuses_every_caller(self, tmp_path, monkeypatch):
        token_file = tmp_path / "engine.token"
        token_file.write_text("")
        monkeypatch.setattr(settings, "engine_token_file", token_file)
        monkeypatch.setattr(settings, "engine_env", "prod")

        with pytest.raises(HTTPException) as refused:
            app_module.require_token(authorization="Bearer anything")

        assert refused.value.status_code == 503

    def test_dev_still_runs_without_one(self, monkeypatch):
        monkeypatch.setattr(settings, "engine_token_file", None)

        app_module.require_token(authorization=None)


class TestInferenceSlots:
    def test_a_capture_past_the_cap_is_refused_with_retry_after(self, monkeypatch):
        slots = threading.BoundedSemaphore(1)
        monkeypatch.setattr(app_module, "_inflight", slots)
        monkeypatch.setattr(settings, "engine_queue_seconds", 0.01)
        slots.acquire()

        with pytest.raises(HTTPException) as refused:
            next(app_module.inference_slot())

        assert refused.value.status_code == 503
        assert refused.value.headers == {"Retry-After": "2"}

    def test_a_slot_is_given_back_when_the_request_ends(self, monkeypatch):
        slots = threading.BoundedSemaphore(1)
        monkeypatch.setattr(app_module, "_inflight", slots)

        held = app_module.inference_slot()
        next(held)
        assert not slots.acquire(blocking=False)
        held.close()

        assert slots.acquire(blocking=False)
