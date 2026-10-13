"""An application's logo, set by whoever registered it and shown on consent.

A logo is a file a developer — someone outside the organization — hands to a
page every user sees. So the same rules as a profile photo: decoded and
re-encoded, never stored as it arrived, served under a name nobody can guess.
"""

import io

import pytest
from PIL import Image

from tests.flows import pkce_pair, query_of, sign_in, start
from tests.test_admin_clients import WEB_APP

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

DEVELOPER_APP = {
    "name": "Attendance",
    "clientType": "public",
    "redirectUris": ["https://attendance.example.org/callback"],
}


def an_image(size=(600, 200), mode="RGBA", fmt="PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, (60, 120, 200, 128)).save(buffer, format=fmt)
    return buffer.getvalue()


def upload(client, path: str, headers, data: bytes):
    return client.put(
        f"{path}/logo", files={"file": ("logo.png", data, "image/png")}, headers=headers
    )


@pytest.fixture
async def admin_client(client, admin_headers) -> str:
    response = await client.post("/admin/clients", json=WEB_APP, headers=admin_headers)
    return f"/admin/clients/{response.json()['id']}"


@pytest.fixture
async def application(client, developer_headers) -> dict:
    response = await client.post(
        "/developer/clients", json=DEVELOPER_APP, headers=developer_headers
    )
    return response.json()


class TestAdminLogo:
    async def test_it_returns_the_client_with_a_url(
        self, client, admin_headers, admin_client
    ):
        response = await upload(client, admin_client, admin_headers, an_image())

        assert response.status_code == 200
        assert response.json()["logoUrl"].startswith(
            "http://localhost:8000/media/logos/"
        )

    async def test_it_is_scaled_to_fit_not_cropped(
        self, client, admin_headers, admin_client, storage
    ):
        """A wordmark cut to a square loses its words."""
        await upload(client, admin_client, admin_headers, an_image(size=(1200, 400)))

        (stored,) = storage.objects.values()
        image = Image.open(io.BytesIO(stored))
        assert image.format == "WEBP"
        assert image.size == (256, 85)
        assert "A" in image.getbands()

    async def test_a_small_logo_is_not_enlarged(
        self, client, admin_headers, admin_client, storage
    ):
        await upload(client, admin_client, admin_headers, an_image(size=(64, 32)))

        (stored,) = storage.objects.values()
        assert Image.open(io.BytesIO(stored)).size == (64, 32)

    async def test_a_second_upload_replaces_the_first(
        self, client, admin_headers, admin_client, storage
    ):
        first = (await upload(client, admin_client, admin_headers, an_image())).json()
        second = (await upload(client, admin_client, admin_headers, an_image())).json()

        assert first["logoUrl"] != second["logoUrl"]
        assert len(storage.objects) == 1
        assert (await client.get(first["logoUrl"])).status_code == 404

    async def test_a_file_that_is_not_an_image_is_refused(
        self, client, admin_headers, admin_client
    ):
        response = await upload(client, admin_client, admin_headers, b"<svg></svg>")

        assert response.status_code == 422
        assert response.json()["code"] == "invalid_image"

    async def test_an_oversized_file_is_refused(
        self, client, admin_headers, admin_client
    ):
        from provider.shared.logos import MAX_BYTES

        response = await upload(
            client, admin_client, admin_headers, b"\x00" * (MAX_BYTES + 1)
        )

        assert response.status_code == 422
        assert response.json()["code"] == "logo_too_large"

    async def test_reading_clients_does_not_allow_setting_one(
        self, client, token_for, admin_client
    ):
        headers = await token_for("admin:clients:read")

        response = await upload(client, admin_client, headers, an_image())

        assert response.status_code == 403

    async def test_removing_it_clears_the_url_and_the_object(
        self, client, admin_headers, admin_client, storage
    ):
        await upload(client, admin_client, admin_headers, an_image())

        response = await client.delete(f"{admin_client}/logo", headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["logoUrl"] is None
        assert storage.objects == {}

    async def test_deleting_the_client_deletes_the_logo(
        self, client, admin_headers, admin_client, storage
    ):
        await upload(client, admin_client, admin_headers, an_image())

        response = await client.delete(admin_client, headers=admin_headers)

        assert response.status_code == 204
        assert storage.objects == {}

    async def test_it_is_served_without_a_token(
        self, client, admin_headers, admin_client
    ):
        url = (await upload(client, admin_client, admin_headers, an_image())).json()[
            "logoUrl"
        ]

        response = await client.get(url)

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"
        assert "immutable" in response.headers["cache-control"]


class TestDeveloperLogo:
    async def test_a_developer_can_set_their_own(
        self, client, developer_headers, application
    ):
        path = f"/developer/clients/{application['id']}"

        response = await upload(client, path, developer_headers, an_image())

        assert response.status_code == 200
        assert response.json()["logoUrl"]

    async def test_someone_elses_application_is_not_found(
        self, client, other_developer_headers, application, storage
    ):
        path = f"/developer/clients/{application['id']}"

        response = await upload(client, path, other_developer_headers, an_image())

        assert response.status_code == 404
        assert storage.objects == {}

    async def test_deleting_the_application_deletes_the_logo(
        self, client, developer_headers, application, storage
    ):
        path = f"/developer/clients/{application['id']}"
        await upload(client, path, developer_headers, an_image())

        await client.delete(path, headers=developer_headers)

        assert storage.objects == {}


class TestConsentScreen:
    async def read_challenge(self, client, client_id: str, redirect_uri: str) -> dict:
        _, challenge = pkce_pair()
        started = await start(
            client,
            challenge,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope="openid profile",
            code_challenge=challenge,
            code_challenge_method="S256",
        )
        login = await sign_in(client, query_of(started)["challenge"])
        resumed = await client.get(login.json()["resumeUrl"])
        assert "/auth/consent" in resumed.headers["location"]

        response = await client.get(
            f"/api/v1/auth/challenge/{query_of(resumed)['challenge']}"
        )
        return response.json()

    async def test_the_challenge_carries_the_logo(
        self, client, developer_headers, application
    ):
        path = f"/developer/clients/{application['id']}"
        logo = (await upload(client, path, developer_headers, an_image())).json()[
            "logoUrl"
        ]

        challenge = await self.read_challenge(
            client, application["clientId"], DEVELOPER_APP["redirectUris"][0]
        )

        assert challenge["clientName"] == "Attendance"
        assert challenge["clientLogoUrl"] == logo

    async def test_it_is_null_without_one(self, client, application):
        challenge = await self.read_challenge(
            client, application["clientId"], DEVELOPER_APP["redirectUris"][0]
        )

        assert challenge["clientLogoUrl"] is None
