"""Phase 4.2 — the profile photo.

An avatar is the one piece of profile data that is not text, and the only one
whose bytes arrive from outside. Everything here is about that: what the
provider accepts, what it stores, and who can read it back.
"""

import io

import pytest
from PIL import Image

from provider.authz.services.token_service import identity_claims

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")


def an_image(size=(900, 300), mode="RGB", fmt="PNG", **save) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, (60, 120, 200)).save(buffer, format=fmt, **save)
    return buffer.getvalue()


def upload(client, headers, data: bytes, name: str = "me.png", kind: str = "image/png"):
    return client.put(
        "/entity/profile/photo", files={"file": (name, data, kind)}, headers=headers
    )


class TestUpload:
    async def test_it_returns_the_profile_with_a_url(self, client, entity_headers):
        response = await upload(client, entity_headers, an_image())

        assert response.status_code == 200
        assert response.json()["pictureUrl"].startswith(
            "http://localhost:8000/media/avatars/"
        )

    async def test_the_stored_file_is_a_square_webp(
        self, client, entity_headers, storage
    ):
        await upload(client, entity_headers, an_image(size=(1600, 400)))

        (stored,) = storage.objects.values()
        image = Image.open(io.BytesIO(stored))
        assert image.format == "WEBP"
        assert image.size == (512, 512)

    async def test_the_original_bytes_are_never_kept(
        self, client, entity_headers, storage
    ):
        """Re-encoding is what drops the metadata a camera writes. A comment
        survives here only if the upload was stored as it arrived."""
        original = an_image(fmt="JPEG", comment=b"taken at 51.5074,-0.1278")

        await upload(client, entity_headers, original, "me.jpg", "image/jpeg")

        (stored,) = storage.objects.values()
        assert b"51.5074" not in stored
        assert stored != original

    async def test_a_second_upload_replaces_the_first(
        self, client, entity_headers, storage
    ):
        first = (await upload(client, entity_headers, an_image())).json()["pictureUrl"]

        second = (await upload(client, entity_headers, an_image())).json()["pictureUrl"]

        assert first != second
        assert len(storage.objects) == 1

    async def test_a_file_that_is_not_an_image_is_refused(self, client, entity_headers):
        response = await upload(client, entity_headers, b"MZ\x90\x00 not an image")

        assert response.status_code == 422
        assert response.json()["code"] == "invalid_image"

    async def test_a_decompression_bomb_is_refused(self, client, entity_headers):
        """A few bytes declaring a 20,000-pixel square: Pillow refuses it in
        `open`, before any pixel is decoded."""
        import struct
        import zlib

        def chunk(kind: bytes, body: bytes) -> bytes:
            crc = zlib.crc32(kind + body)
            return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

        header = struct.pack(">IIBBBBB", 20_000, 20_000, 8, 2, 0, 0, 0)
        bomb = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")

        response = await upload(client, entity_headers, bomb)

        assert response.status_code == 422
        assert response.json()["code"] == "invalid_image"

    async def test_an_oversized_file_is_refused(self, client, entity_headers):
        from provider.core.config import settings

        response = await upload(
            client, entity_headers, b"\x00" * (settings.iden_avatar_max_bytes + 1)
        )

        assert response.status_code == 422
        assert response.json()["code"] == "photo_too_large"

    async def test_it_needs_the_write_scope(self, client, token_for, member):
        headers = await token_for("entity:profile:read", user=member)

        response = await upload(client, headers, an_image())

        assert response.status_code == 403


class TestDelete:
    async def test_it_clears_the_url_and_the_object(
        self, client, entity_headers, storage
    ):
        await upload(client, entity_headers, an_image())

        response = await client.delete("/entity/profile/photo", headers=entity_headers)

        assert response.status_code == 200
        assert response.json()["pictureUrl"] is None
        assert storage.objects == {}

    async def test_removing_nothing_succeeds(self, client, entity_headers):
        response = await client.delete("/entity/profile/photo", headers=entity_headers)

        assert response.status_code == 200
        assert response.json()["pictureUrl"] is None


class TestDelivery:
    async def test_it_serves_the_image_without_a_token(self, client, entity_headers):
        url = (await upload(client, entity_headers, an_image())).json()["pictureUrl"]

        response = await client.get(url)

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"
        assert "immutable" in response.headers["cache-control"]

    async def test_the_previous_url_stops_resolving(self, client, entity_headers):
        """What makes a photo removable at all: the name is the only handle on
        the object, so replacing it retires every copy of the old link."""
        old = (await upload(client, entity_headers, an_image())).json()["pictureUrl"]
        await upload(client, entity_headers, an_image())

        assert (await client.get(old)).status_code == 404

    async def test_a_name_cannot_reach_another_prefix(self, client):
        response = await client.get("/media/avatars/..%2Fbiometric%2Fface.webp")

        assert response.status_code in (404, 422)


class TestClaim:
    async def test_the_picture_claim_carries_the_url(
        self, client, entity_headers, db, member
    ):
        """The point of holding a photo in an identity provider at all: every
        client granted `profile` gets it as the standard OIDC claim, for
        free."""
        url = (await upload(client, entity_headers, an_image())).json()["pictureUrl"]
        await db.refresh(member)

        claims = identity_claims(member, {"profile"})

        assert claims["picture"] == url

    async def test_it_is_null_when_no_photo_is_set(self, db, member):
        assert identity_claims(member, {"profile"})["picture"] is None
