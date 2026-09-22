"""A ceiling on the request body, in the application rather than only the proxy.

FastAPI reads a JSON body in full before Pydantic sees it, and a multipart upload
is spooled to a temporary file while it is parsed. Neither had a limit, so an
unauthenticated caller could make the provider hold as much memory — or write as
much disk — as it was willing to send. `deploy/nginx` refuses these earlier; these
tests are about the limit that is still there when it does not.
"""

import pytest

from provider.core.bodylimit import MAX_BODY_BYTES

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")


class TestJsonBodies:
    async def test_an_oversized_body_is_refused(self, client):
        response = await client.post(
            "/api/v1/auth/login",
            content=b'{"a":"' + b"x" * (MAX_BODY_BYTES + 1) + b'"}',
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 413
        assert response.json()["code"] == "payload_too_large"

    async def test_it_is_refused_before_the_password_is_checked(self, client):
        """The refusal has to come before argon2, which is the expense the limit
        exists to protect. A 413 rather than a 401 or a 422 is what says so."""
        response = await client.post(
            "/api/v1/auth/login",
            content=b'{"challengeId":"x","email":"a@b","password":"'
            + b"x" * (MAX_BODY_BYTES + 1)
            + b'"}',
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 413

    async def test_a_chunked_body_with_no_length_is_still_counted(self, client):
        """`Content-Length` is a claim. A chunked body makes none, so the only
        place to catch it is while it streams."""

        async def oversized():
            for _ in range(MAX_BODY_BYTES // 1024 + 2):
                yield b"x" * 1024

        response = await client.post(
            "/api/v1/auth/login",
            content=oversized(),
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 413

    async def test_an_ordinary_body_is_untouched(self, client):
        response = await client.post(
            "/api/v1/auth/login",
            json={"challengeId": "nope", "email": "a@b.test", "password": "x" * 20},
        )

        assert response.status_code == 404


class TestPhotoUploads:
    async def test_the_upload_endpoint_gets_its_own_ceiling(
        self, client, entity_headers
    ):
        """`IDEN_AVATAR_MAX_BYTES` is checked after the body has been received,
        so it is not what stops a large one arriving."""
        from provider.core.config import settings

        response = await client.put(
            "/entity/profile/photo",
            files={"file": ("big.png", b"x" * (settings.iden_avatar_max_bytes * 2))},
            headers=entity_headers,
        )

        assert response.status_code == 413

    async def test_a_photo_within_the_ceiling_still_reaches_the_decoder(
        self, client, entity_headers
    ):
        """Refused for not being an image, which means the body arrived."""
        response = await client.put(
            "/entity/profile/photo",
            files={"file": ("small.png", b"not an image")},
            headers=entity_headers,
        )

        assert response.status_code == 422
