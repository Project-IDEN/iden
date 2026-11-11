"""TDS section A: basis paths of the core auth logic the original suite never ran.

Each test names the function it exists to reach. The expected answer is always the
OAuth error RFC 6749 defines for the case, or the domain error the provider
documents — never a 500.
"""

from datetime import timedelta

import pytest
from sqlalchemy import update

from provider.authz.services.auth_methods import outstanding
from provider.authz.services.token_service import now
from provider.shared.client_uris import MAX_URI_LENGTH, validate_backchannel_uri
from provider.shared.enums import ClientType, GrantType
from provider.shared.models import AuthorizationCode, Client, RefreshToken
from tests.conftest import REDIRECT_URI
from tests.flows import get_code, get_tokens

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")


async def exchange(client, code: str, verifier: str, client_id: str = "dashboard"):
    return await client.post(
        "/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "client_id": client_id,
        },
    )


async def refresh(client, token: str, client_id: str = "dashboard"):
    return await client.post(
        "/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": token,
            "client_id": client_id,
        },
    )


class TestA1ConsumeCode:
    """`authz.oauth.service.consume_code`: unknown, expired and wrong-client codes."""

    async def test_an_unknown_code_is_invalid_grant(self, client):
        """A code IDEN never issued is refused with 400 invalid_grant "Unknown authorization code."."""
        _, verifier = await get_code(client)

        response = await exchange(client, "never-issued-" + "x" * 30, verifier)

        assert response.status_code == 400
        assert response.json() == {
            "error": "invalid_grant",
            "error_description": "Unknown authorization code.",
        }

    async def test_an_expired_code_is_invalid_grant(self, client, db):
        """A code past its expiry is refused with 400 invalid_grant "This authorization code has expired."."""
        code, verifier = await get_code(client)
        await db.execute(
            update(AuthorizationCode).values(expires_at=now() - timedelta(seconds=1))
        )
        await db.commit()

        response = await exchange(client, code, verifier)

        assert response.status_code == 400
        assert response.json() == {
            "error": "invalid_grant",
            "error_description": "This authorization code has expired.",
        }

    async def test_a_code_issued_to_another_client_is_invalid_grant(
        self, client, third_party
    ):
        """A code issued to the dashboard and redeemed by another client is refused with 400 invalid_grant."""
        code, verifier = await get_code(client)

        response = await exchange(client, code, verifier, client_id="library")

        assert response.status_code == 400
        assert response.json() == {
            "error": "invalid_grant",
            "error_description": "This code was issued to a different client.",
        }

    async def test_a_code_without_a_verifier_is_invalid_grant(self, client):
        """WB-1 P6 (`consume_code`, the `not code_verifier` short-circuit): a valid code redeemed with code_verifier omitted is refused with 400 invalid_grant "PKCE verification failed."."""
        code, _ = await get_code(client)

        response = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": "dashboard",
            },
        )

        assert response.status_code == 400
        assert response.json() == {
            "error": "invalid_grant",
            "error_description": "PKCE verification failed.",
        }


class TestA2Refresh:
    """The refresh grant in `authz.oauth.grants` and `authz.services.token_service`."""

    async def test_a_refresh_token_of_another_client_is_invalid_grant(
        self, client, third_party
    ):
        """A refresh token issued to the dashboard and presented by another client is refused with 400 invalid_grant."""
        tokens = await get_tokens(client)

        response = await refresh(client, tokens["refresh_token"], client_id="library")

        assert response.status_code == 400
        assert response.json() == {
            "error": "invalid_grant",
            "error_description": "This refresh token was issued to a different client.",
        }

    async def test_an_expired_refresh_token_is_invalid_grant(self, client, db):
        """A refresh token past its expiry is refused with 400 invalid_grant "Unknown or expired refresh token."."""
        tokens = await get_tokens(client)
        await db.execute(
            update(RefreshToken).values(expires_at=now() - timedelta(seconds=1))
        )
        await db.commit()

        response = await refresh(client, tokens["refresh_token"])

        assert response.status_code == 400
        assert response.json() == {
            "error": "invalid_grant",
            "error_description": "Unknown or expired refresh token.",
        }


class TestA3ClientCredentials:
    """The client_credentials grant in `authz.oauth.grants`."""

    async def test_a_public_client_cannot_use_client_credentials(self, client, db):
        """A public client configured with client_credentials is still refused that grant with an OAuth client error, not a token."""
        db.add(
            Client(
                client_id="public-machine",
                name="Public machine",
                client_type=ClientType.PUBLIC,
                allowed_grants=[GrantType.CLIENT_CREDENTIALS],
            )
        )
        await db.commit()

        response = await client.post(
            "/oauth2/token",
            data={"grant_type": "client_credentials", "client_id": "public-machine"},
        )

        assert response.status_code in (400, 401)
        assert response.json()["error"] in ("unauthorized_client", "invalid_client")
        assert "access_token" not in response.json()


class TestA5BackchannelUri:
    """`shared.client_uris.validate_backchannel_uri`."""

    @pytest.mark.parametrize(
        "uri",
        [
            "https://app.example.org/logout",
            "http://localhost:5100/logout",
            "http://127.0.0.1/backchannel",
        ],
    )
    def test_a_valid_uri_is_kept(self, uri):
        """An absolute https URI, or http on loopback, is accepted unchanged."""
        assert validate_backchannel_uri(uri) == uri

    @pytest.mark.parametrize("uri", [None, ""])
    def test_no_uri_means_none(self, uri):
        """An absent or empty back-channel URI means the client is never told, and is stored as None."""
        assert validate_backchannel_uri(uri) is None

    @pytest.mark.parametrize(
        ("uri", "reason"),
        [
            ("http://app.example.org/logout", "http is allowed only on localhost"),
            ("/logout", "must be http or https"),
            ("logout", "must be http or https"),
            ("https:///logout", "needs a host"),
            ("https://app.example.org/logout#frag", "fragment or credentials"),
            ("https://user:pw@app.example.org/logout", "fragment or credentials"),
            ("https://app.example.org/a b", "printable ASCII"),
            (
                "https://app.example.org/" + "a" * (MAX_URI_LENGTH - 23),
                f"at most {MAX_URI_LENGTH} characters",
            ),
        ],
    )
    def test_an_invalid_uri_is_refused(self, uri, reason):
        """A non-https remote, relative, hostless, fragment, credential, non-printable or over-length URI is refused with a reason."""
        with pytest.raises(ValueError, match=reason):
            validate_backchannel_uri(uri)

    def test_exactly_the_maximum_length_is_accepted(self):
        """A back-channel URI of exactly MAX_URI_LENGTH characters is accepted (upper boundary)."""
        uri = "https://app.example.org/" + "a" * (MAX_URI_LENGTH - 24)
        assert len(uri) == MAX_URI_LENGTH
        assert validate_backchannel_uri(uri) == uri

    async def test_the_admin_api_answers_422_not_500(self, client, admin_headers):
        """Registering a client with an http non-loopback back-channel URI is refused with 422 validation_error."""
        response = await client.post(
            "/admin/clients",
            headers=admin_headers,
            json={
                "clientId": "bc-test",
                "name": "Back-channel test",
                "clientType": "public",
                "redirectUris": ["https://app.example.org/callback"],
                "backchannelLogoutUri": "http://app.example.org/logout",
            },
        )

        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"


class TestWB4Outstanding:
    """`authz.services.auth_methods.outstanding` — `reaching` empty, so `unused` is returned."""

    def test_when_no_single_method_reaches_the_level_every_unused_one_is_offered(self):
        """WB-4 P3: with nothing used yet and mfa-face required, no single added method reaches it, so outstanding returns every unused method, ["face", "otp", "pwd"]."""
        assert outstanding([], {"pwd", "otp", "face"}, "urn:iden:acr:mfa-face") == [
            "face",
            "otp",
            "pwd",
        ]
