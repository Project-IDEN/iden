import json

import cv2
import pytest
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
        data={"meta": json.dumps({"steps": ["center", "smile", "center"]})},
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
