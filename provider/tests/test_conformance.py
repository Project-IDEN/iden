"""Where the implementation meets the specifications it claims.

Each test names the clause it enforces. They are grouped by the gap they close
rather than by endpoint, because the interesting thing about most of these is
not what the endpoint does — it is which sentence in which document says so.
"""

import base64
from urllib.parse import quote

import jwt
import pytest

from provider.core.security import hash_secret
from provider.shared.enums import ClientType, GrantType
from provider.shared.models import Client, ClientScope
from tests.flows import get_tokens, pkce_pair, query_of, start

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")


def header_of(token: str) -> dict:
    return jwt.get_unverified_header(token)


class TestTokenType:
    """C-1 · RFC 9068 Section 2.1 — every token says what it is.

    Without the `typ` header nothing distinguishes an access token from an ID
    token by type, and the two endpoints that do not check audience would not
    catch the confusion at all.
    """

    async def test_an_access_token_is_marked_as_one(self, client):
        tokens = await get_tokens(client)
        assert header_of(tokens["access_token"])["typ"] == "at+jwt"

    async def test_an_id_token_is_not_marked_as_an_access_token(self, client):
        tokens = await get_tokens(client)
        assert header_of(tokens["id_token"])["typ"] == "JWT"

    async def test_an_id_token_is_refused_at_userinfo(self, client):
        """The bug behind C-1. `/oauth2/userinfo` reads `claims["jti"]`, an ID
        token has none, so this answered 500 where 401 belongs."""
        tokens = await get_tokens(client)

        response = await client.get(
            "/oauth2/userinfo",
            headers={"Authorization": f"Bearer {tokens['id_token']}"},
        )

        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"

    async def test_an_id_token_is_refused_at_introspect(self, client, kiosk):
        _, secret = kiosk
        tokens = await get_tokens(client)

        response = await client.post(
            "/oauth2/introspect",
            data={
                "token": tokens["id_token"],
                "client_id": "kiosk",
                "client_secret": secret,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"active": False}

    async def test_an_id_token_is_refused_at_a_resource_server(self, client):
        tokens = await get_tokens(client)

        response = await client.get(
            "/admin/users", headers={"Authorization": f"Bearer {tokens['id_token']}"}
        )

        assert response.status_code == 401

    async def test_an_id_token_hint_is_still_accepted_where_it_belongs(self, client):
        """The type check must not break the one place an ID token is the
        correct credential — otherwise `prompt=none` stops working."""
        tokens = await get_tokens(client)
        _, challenge = pkce_pair()

        response = await start(
            client, challenge, prompt="none", id_token_hint=tokens["id_token"]
        )

        assert "code" in query_of(response)


class TestUserInfoMethods:
    """C-2 · OIDC Core Section 5.3.1 — GET and POST, and the token may arrive in either."""

    async def test_post_is_accepted_with_a_bearer_header(self, client):
        tokens = await get_tokens(client)

        response = await client.post(
            "/oauth2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )

        assert response.status_code == 200
        assert response.json()["sub"]

    async def test_post_is_accepted_with_a_form_encoded_token(self, client):
        """RFC 6750 Section 2.2. Several relying-party libraries send it this way."""
        tokens = await get_tokens(client)

        response = await client.post(
            "/oauth2/userinfo", data={"access_token": tokens["access_token"]}
        )

        assert response.status_code == 200
        assert response.json()["sub"]

    async def test_get_and_post_agree(self, client):
        tokens = await get_tokens(client)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        from_get = await client.get("/oauth2/userinfo", headers=headers)
        from_post = await client.post("/oauth2/userinfo", headers=headers)

        assert from_get.json() == from_post.json()

    async def test_a_missing_token_is_still_refused(self, client):
        assert (await client.post("/oauth2/userinfo")).status_code == 401


class TestLogoutMethods:
    """C-3 · RP-Initiated Logout 1.0 Section 2 — POST keeps the hint out of history."""

    async def test_post_ends_the_session(self, client):
        await get_tokens(client)  # leaves a session cookie on the client

        response = await client.post("/oauth2/logout")

        assert response.status_code in (204, 303)
        # The cookie is cleared, so the next authorize needs a fresh login.
        _, challenge = pkce_pair()
        assert "challenge" in query_of(await start(client, challenge))

    async def test_post_honours_a_registered_redirect(self, client):
        await get_tokens(client)

        response = await client.post(
            "/oauth2/logout",
            data={
                "client_id": "dashboard",
                "post_logout_redirect_uri": "http://localhost:5173/",
            },
        )

        assert response.status_code == 303
        assert response.headers["location"].startswith("http://localhost:5173/")


class TestBasicCredentialEncoding:
    """C-4 · RFC 6749 Section 2.3.1 — both halves are form-urlencoded before base64."""

    @pytest.fixture
    async def reserved(self, db, catalogue) -> tuple[str, str]:
        """A client whose secret contains characters the spec requires escaping."""
        secret = "s3cr:t/with+reserved&chars"
        record = Client(
            client_id="legacy-import",
            name="Imported Service",
            client_type=ClientType.CONFIDENTIAL,
            client_secret_hash=hash_secret(secret),
            allowed_grants=[GrantType.CLIENT_CREDENTIALS],
            skip_consent=True,
        )
        db.add(record)
        await db.flush()
        db.add(
            ClientScope(
                client_id=record.id,
                scope_id=catalogue["scopes"]["entity:profile:read"].id,
                grantable=False,
                granted=True,
            )
        )
        await db.commit()
        return "legacy-import", secret

    async def test_a_secret_with_reserved_characters_authenticates(
        self, client, reserved
    ):
        """This failed as `invalid_client` with nothing to suggest why. IDEN's
        own generated secrets are URL-safe, so it only bit on an import."""
        client_id, secret = reserved
        encoded = base64.b64encode(
            f"{quote(client_id, safe='')}:{quote(secret, safe='')}".encode()
        ).decode()

        response = await client.post(
            "/oauth2/token",
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {encoded}"},
        )

        assert response.status_code == 200

    async def test_an_unescaped_secret_without_reserved_characters_still_works(
        self, client, kiosk
    ):
        """The common case must not regress: nothing in a URL-safe secret
        changes under unquoting."""
        _, secret = kiosk
        encoded = base64.b64encode(f"kiosk:{secret}".encode()).decode()

        response = await client.post(
            "/oauth2/token",
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {encoded}"},
        )

        assert response.status_code == 200


class TestChallengeHeaders:
    """C-5 and C-6 · RFC 6750 Section 3 — the challenge says what to do about it."""

    async def test_insufficient_scope_is_named_in_the_header(self, client, token_for):
        """C-5. Without this a client cannot tell "you lack this scope" from any
        other 403 without parsing prose."""
        headers = await token_for("admin:users:read")

        response = await client.post(
            "/admin/users",
            json={"email": "x@test.local", "username": "x"},
            headers=headers,
        )

        assert response.status_code == 403
        challenge = response.headers["www-authenticate"]
        assert 'error="insufficient_scope"' in challenge
        assert "admin:users:write" in challenge

    async def test_a_protected_resource_challenges_with_bearer(self, client):
        """C-6. `Basic` here told the client to retry with client credentials
        instead of sending the person back through a login."""
        response = await client.get(
            "/oauth2/userinfo", headers={"Authorization": "Bearer nonsense"}
        )

        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Bearer")

    async def test_the_token_endpoint_still_challenges_with_basic(self, client):
        """The other half of C-6: `invalid_client` really is a client that
        failed to authenticate, and `Basic` is the right thing to say."""
        response = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "kiosk",
                "client_secret": "wrong",
            },
        )

        assert response.status_code == 401
        assert response.headers["www-authenticate"].startswith("Basic")


class TestMetadataDeclarations:
    """C-7 · OIDC Discovery 1.0 Section 3 — the omissions defaulted to `true`."""

    async def test_unimplemented_features_are_declared_false(self, client):
        body = (await client.get("/.well-known/openid-configuration")).json()

        # Each of these defaults to true when absent, so silence advertised
        # support for request objects IDEN does not implement.
        assert body["request_parameter_supported"] is False
        assert body["request_uri_parameter_supported"] is False
        assert body["claims_parameter_supported"] is False

    async def test_response_modes_are_stated(self, client):
        body = (await client.get("/.well-known/openid-configuration")).json()
        assert body["response_modes_supported"] == ["query"]

    async def test_introspection_does_not_advertise_public_clients(self, client):
        body = (await client.get("/.well-known/openid-configuration")).json()
        assert "none" not in body["introspection_endpoint_auth_methods_supported"]
        assert "none" in body["revocation_endpoint_auth_methods_supported"]


class TestAuthorizationServerMetadata:
    """RFC 8414 — a pure OAuth 2.0 client looks only here."""

    async def test_the_oauth_document_is_served(self, client):
        response = await client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        assert response.json()["issuer"]

    async def test_it_matches_the_openid_document(self, client):
        oauth = await client.get("/.well-known/oauth-authorization-server")
        oidc = await client.get("/.well-known/openid-configuration")
        assert oauth.json() == oidc.json()


class TestIssuerIdentification:
    """RFC 9207 — which provider answered, on every authorization response."""

    async def test_a_successful_response_carries_iss(self, client):
        _, challenge = pkce_pair()
        response = await start(client, challenge)
        challenge_id = query_of(response)["challenge"]

        from tests.flows import sign_in

        login = await sign_in(client, challenge_id)
        resumed = await client.get(login.json()["resumeUrl"])

        assert query_of(resumed)["iss"] == "http://localhost:8000"

    async def test_an_error_response_carries_iss(self, client):
        """A client that validates `iss` on success but not on failure has
        closed only half the mix-up."""
        _, challenge = pkce_pair()
        response = await start(client, challenge, response_type="token")

        assert query_of(response)["error"] == "unsupported_response_type"
        assert query_of(response)["iss"] == "http://localhost:8000"

    async def test_it_is_advertised(self, client):
        body = (await client.get("/.well-known/openid-configuration")).json()
        assert body["authorization_response_iss_parameter_supported"] is True


class TestOfflineAccess:
    """C-8 · OIDC Core Section 11 — a refresh token is asked for, not assumed."""

    async def test_a_refresh_token_is_issued_when_asked_for(self, client):
        tokens = await get_tokens(client, scope="openid offline_access")
        assert tokens.get("refresh_token")

    async def test_no_refresh_token_without_the_scope(self, client):
        """The client is still *configured* for the grant. What changed is that
        it now has to ask, and is told what it got."""
        tokens = await get_tokens(client, scope="openid profile")
        assert tokens.get("refresh_token") is None

    async def test_the_granted_scope_reports_it(self, client):
        tokens = await get_tokens(client, scope="openid offline_access")
        assert "offline_access" in tokens["scope"].split()

    async def test_it_is_advertised_as_supported(self, client):
        body = (await client.get("/.well-known/openid-configuration")).json()
        assert "offline_access" in body["scopes_supported"]

    async def test_rotation_survives_it(self, client):
        """The grant carries the scope, so a rotation does not have to re-ask."""
        tokens = await get_tokens(client, scope="openid offline_access")

        rotated = (
            await client.post(
                "/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                    "client_id": "dashboard",
                },
            )
        ).json()

        assert rotated.get("refresh_token")


class TestTokenTypeHint:
    """RFC 7009 Section 2.1 — accepted and acted on, rather than accepted and ignored."""

    async def test_a_correct_hint_revokes(self, client):
        tokens = await get_tokens(client)

        response = await client.post(
            "/oauth2/revoke",
            data={
                "token": tokens["refresh_token"],
                "token_type_hint": "refresh_token",
                "client_id": "dashboard",
            },
        )

        assert response.status_code == 200
        replay = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": "dashboard",
            },
        )
        assert replay.status_code == 400

    async def test_a_wrong_hint_still_revokes(self, client):
        """The hint orders the lookups; it never decides which are allowed. A
        client that guesses wrong must not silently keep a live token."""
        tokens = await get_tokens(client)

        await client.post(
            "/oauth2/revoke",
            data={
                "token": tokens["refresh_token"],
                "token_type_hint": "access_token",  # wrong on purpose
                "client_id": "dashboard",
            },
        )

        replay = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": "dashboard",
            },
        )
        assert replay.status_code == 400


class TestDerivedAudience:
    """KI-10 · a scope outside IDEN's own APIs has no derivable audience."""

    def test_guessing_is_refused_rather_than_silently_wrong(self):
        """It used to compute a nonexistent audience and 401 every request that
        satisfied the scope. Failing when the router is built names the scope."""
        from provider.core.auth import require_scope

        with pytest.raises(ValueError, match="attendance"):
            require_scope("attendance:records:read")

    def test_an_explicit_audience_is_accepted(self):
        from provider.core.auth import require_scope

        assert require_scope(
            "attendance:records:read", audience="https://api.example.org/attendance"
        )

    def test_the_system_apis_still_derive(self):
        from provider.core.auth import require_scope

        for scope in ("admin:users:read", "entity:profile:read", "biometric:enroll"):
            assert require_scope(scope)
