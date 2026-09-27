import asyncio

import jwt
import pytest

from provider.core.security import hash_secret
from tests.conftest import ADMIN_EMAIL
from tests.flows import get_tokens

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")


def decode(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


async def refresh(client, token: str, **extra):
    return await client.post(
        "/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": token,
            "client_id": "dashboard",
            **extra,
        },
    )


class TestRefreshRotation:
    async def test_refresh_returns_a_different_token(self, client):
        tokens = await get_tokens(client)
        rotated = (await refresh(client, tokens["refresh_token"])).json()

        assert rotated["refresh_token"] != tokens["refresh_token"]
        assert rotated["access_token"] != tokens["access_token"]

    async def test_reuse_of_a_rotated_token_is_detected(self, client, no_grace):
        tokens = await get_tokens(client)
        await refresh(client, tokens["refresh_token"])

        replay = await refresh(client, tokens["refresh_token"])

        assert replay.status_code == 400
        assert "reuse" in replay.json()["error_description"].lower()

    async def test_reuse_revokes_the_whole_family(self, client, no_grace):
        """Two parties holding one token means only one of them is legitimate,
        so the safe move is to invalidate the lineage rather than guess."""
        tokens = await get_tokens(client)
        rotated = (await refresh(client, tokens["refresh_token"])).json()

        await refresh(client, tokens["refresh_token"])
        after = await refresh(client, rotated["refresh_token"])

        assert after.status_code == 400

    async def test_refresh_token_is_not_stored_in_the_clear(self, client, db):
        from sqlalchemy import select

        from provider.shared.models import RefreshToken

        tokens = await get_tokens(client)
        stored = (await db.scalars(select(RefreshToken))).all()

        assert stored and all(r.token_hash != tokens["refresh_token"] for r in stored)

    async def test_refresh_carries_the_original_authentication_context(self, client):
        tokens = await get_tokens(client)
        rotated = (await refresh(client, tokens["refresh_token"])).json()
        claims = decode(rotated["access_token"])

        assert claims["acr"] == "iden:loa:1"
        assert claims["amr"] == ["pwd"]

    async def test_permissions_are_re_resolved_on_refresh(self, client, db, admin_user):
        """Revoking a role takes effect here — this is why access tokens are
        short-lived rather than long-lived."""
        tokens = await get_tokens(client)
        assert "admin:users:read" in decode(tokens["access_token"])["scope"]

        admin_user.roles = []
        db.add(admin_user)
        await db.commit()

        rotated = (await refresh(client, tokens["refresh_token"])).json()

        assert "admin:users:read" not in rotated["scope"]
        assert "openid" in rotated["scope"]

    async def test_scope_narrowing_applies_to_one_response_only(self, client):
        """KI-2. `scope` narrows the response; it must not shrink the grant.

        The refresh token represents the original grant (RFC 6749 Section 6). A client
        that once asked for less has to be able to get the rest back, or a single
        narrow request silently downgrades it forever.
        """
        tokens = await get_tokens(
            client, scope="openid offline_access admin:users:read"
        )

        narrowed = (
            await refresh(
                client, tokens["refresh_token"], scope="openid offline_access"
            )
        ).json()
        assert set(narrowed["scope"].split()) == {"openid", "offline_access"}

        restored = (await refresh(client, narrowed["refresh_token"])).json()
        assert "admin:users:read" in restored["scope"].split()

    async def test_scope_cannot_be_widened_beyond_the_original_grant(self, client):
        """RFC 6749 Section 6 — a refresh must not gain scopes the original lacked."""
        tokens = await get_tokens(
            client, scope="openid offline_access admin:users:read"
        )

        widened = (
            await refresh(
                client,
                tokens["refresh_token"],
                scope="openid offline_access admin:roles:write",
            )
        ).json()
        assert "admin:roles:write" not in widened["scope"]

    async def test_unknown_refresh_token_is_rejected(self, client):
        assert (await refresh(client, "not-a-token")).status_code == 400

    async def test_inactive_user_cannot_refresh(self, client, db, admin_user):
        tokens = await get_tokens(client)

        admin_user.is_active = False
        db.add(admin_user)
        await db.commit()

        response = await refresh(client, tokens["refresh_token"])
        assert response.status_code == 400


class TestClientCredentials:
    async def test_confidential_client_gets_a_token(self, client, kiosk):
        _, secret = kiosk
        response = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "kiosk",
                "client_secret": secret,
                "scope": "entity:profile:read",
            },
        )

        assert response.status_code == 200
        assert response.json()["scope"] == "entity:profile:read"

    async def test_subject_is_the_client_and_there_is_no_authentication_context(
        self, client, kiosk
    ):
        _, secret = kiosk
        body = (
            await client.post(
                "/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "kiosk",
                    "client_secret": secret,
                },
            )
        ).json()
        claims = decode(body["access_token"])

        assert claims["sub"] == "kiosk"
        assert "acr" not in claims and "amr" not in claims

    async def test_no_refresh_or_id_token_is_issued(self, client, kiosk):
        _, secret = kiosk
        body = (
            await client.post(
                "/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "kiosk",
                    "client_secret": secret,
                },
            )
        ).json()

        assert body.get("refresh_token") is None
        assert body.get("id_token") is None

    async def test_only_scopes_the_client_holds_are_granted(self, client, kiosk):
        _, secret = kiosk
        body = (
            await client.post(
                "/oauth2/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": "kiosk",
                    "client_secret": secret,
                    "scope": "admin:users:write entity:profile:read",
                },
            )
        ).json()

        assert body["scope"] == "entity:profile:read"

    async def test_basic_authentication_is_accepted(self, client, kiosk):
        import base64

        _, secret = kiosk
        header = base64.b64encode(f"kiosk:{secret}".encode()).decode()
        response = await client.post(
            "/oauth2/token",
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {header}"},
        )

        assert response.status_code == 200

    async def test_wrong_secret_is_rejected(self, client, kiosk):
        response = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "kiosk",
                "client_secret": "no",
            },
        )

        assert response.status_code == 401
        assert response.json()["error"] == "invalid_client"

    async def test_public_client_cannot_use_this_grant(self, client):
        """A public client has no secret, so it has nothing to prove with."""
        response = await client.post(
            "/oauth2/token",
            data={"grant_type": "client_credentials", "client_id": "dashboard"},
        )

        assert response.status_code == 401

    async def test_unsupported_grant_type_is_rejected(self, client, kiosk):
        _, secret = kiosk
        response = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "password",
                "client_id": "kiosk",
                "client_secret": secret,
            },
        )

        assert response.status_code == 401


class TestUserInfo:
    async def test_returns_claims_for_the_granted_scopes(self, client):
        tokens = await get_tokens(client)
        body = (
            await client.get(
                "/oauth2/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
        ).json()

        assert body["email"] == ADMIN_EMAIL
        assert body["preferred_username"] == "admin"

    async def test_withholds_claims_whose_scope_was_not_granted(self, client):
        tokens = await get_tokens(client, scope="openid")
        body = (
            await client.get(
                "/oauth2/userinfo",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
        ).json()

        assert "email" not in body and "name" not in body
        assert body["sub"]

    async def test_requires_the_openid_scope(self, client):
        tokens = await get_tokens(client, scope="admin:users:read")
        response = await client.get(
            "/oauth2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )

        assert response.status_code == 403

    async def test_garbage_token_is_rejected(self, client):
        response = await client.get(
            "/oauth2/userinfo", headers={"Authorization": "Bearer not.a.token"}
        )
        assert response.status_code == 401

    async def test_missing_token_is_rejected(self, client):
        assert (await client.get("/oauth2/userinfo")).status_code == 401


class TestRevocation:
    async def test_revoked_access_token_stops_working(self, client):
        tokens = await get_tokens(client)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        assert (
            await client.get("/oauth2/userinfo", headers=headers)
        ).status_code == 200

        await client.post(
            "/oauth2/revoke",
            data={"token": tokens["access_token"], "client_id": "dashboard"},
        )

        assert (
            await client.get("/oauth2/userinfo", headers=headers)
        ).status_code == 401

    async def test_revoking_a_refresh_token_kills_the_family(self, client):
        tokens = await get_tokens(client)
        await client.post(
            "/oauth2/revoke",
            data={"token": tokens["refresh_token"], "client_id": "dashboard"},
        )

        assert (await refresh(client, tokens["refresh_token"])).status_code == 400

    async def test_public_client_may_revoke_its_own_token(self, client):
        """KI-1. Permitted by RFC 7009 Section 2.1 — the caller already holds the token,
        so there is nothing to learn, and nothing is disclosed either way."""
        tokens = await get_tokens(client)

        response = await client.post(
            "/oauth2/revoke",
            data={"token": tokens["refresh_token"], "client_id": "dashboard"},
        )

        assert response.status_code == 200
        assert (await refresh(client, tokens["refresh_token"])).status_code == 400

    async def test_one_client_cannot_revoke_another_clients_token(self, client, kiosk):
        _, secret = kiosk
        tokens = await get_tokens(client)

        await client.post(
            "/oauth2/revoke",
            data={
                "token": tokens["refresh_token"],
                "client_id": "kiosk",
                "client_secret": secret,
            },
        )

        assert (await refresh(client, tokens["refresh_token"])).status_code == 200

    async def test_unknown_client_cannot_revoke(self, client):
        response = await client.post(
            "/oauth2/revoke", data={"token": "x", "client_id": "does-not-exist"}
        )
        assert response.status_code == 401

    async def test_unknown_token_still_returns_200(self, client):
        """RFC 7009 Section 2.2 — otherwise this endpoint reports which tokens exist."""
        response = await client.post(
            "/oauth2/revoke", data={"token": "nonsense", "client_id": "dashboard"}
        )
        assert response.status_code == 200


async def kiosk_token(client, secret: str) -> str:
    """An access token the kiosk holds in its own right, so it may introspect it."""
    body = (
        await client.post(
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "kiosk",
                "client_secret": secret,
                "scope": "entity:profile:read",
            },
        )
    ).json()
    return body["access_token"]


class TestIntrospection:
    async def test_reports_an_active_token(self, client, kiosk):
        _, secret = kiosk
        token = await kiosk_token(client, secret)

        body = (
            await client.post(
                "/oauth2/introspect",
                data={
                    "token": token,
                    "client_id": "kiosk",
                    "client_secret": secret,
                },
            )
        ).json()

        assert body["active"] is True
        assert body["client_id"] == "kiosk"

    async def test_reports_a_revoked_token_as_inactive(self, client, kiosk):
        _, secret = kiosk
        token = await kiosk_token(client, secret)
        await client.post(
            "/oauth2/revoke",
            data={"token": token, "client_id": "kiosk", "client_secret": secret},
        )

        body = (
            await client.post(
                "/oauth2/introspect",
                data={
                    "token": token,
                    "client_id": "kiosk",
                    "client_secret": secret,
                },
            )
        ).json()

        assert body["active"] is False

    async def test_a_client_cannot_introspect_another_clients_token(
        self, client, kiosk
    ):
        """RFC 7662 Section 4. Any confidential client could previously read the
        contents of any token IDEN had issued, including who it was for and
        what it could do."""
        _, secret = kiosk
        tokens = await get_tokens(client)  # issued to `dashboard`

        body = (
            await client.post(
                "/oauth2/introspect",
                data={
                    "token": tokens["access_token"],
                    "client_id": "kiosk",
                    "client_secret": secret,
                },
            )
        ).json()

        # Inactive rather than refused: the answer must not distinguish
        # "someone else's" from "never existed".
        assert body == {"active": False}

    async def test_a_refresh_token_can_be_introspected_by_its_own_client(
        self, client, kiosk, db, catalogue
    ):
        """RFC 7662 accepts any token type the server issues, not only JWTs."""
        from provider.shared.enums import ClientType, GrantType
        from provider.shared.models import Client, ClientScope

        secret = "confidential-app-secret"
        app = Client(
            client_id="reporting",
            name="Reporting",
            client_type=ClientType.CONFIDENTIAL,
            client_secret_hash=hash_secret(secret),
            allowed_grants=[GrantType.AUTHORIZATION_CODE, GrantType.REFRESH_TOKEN],
            redirect_uris=["https://reporting.example.org/callback"],
            skip_consent=True,
        )
        db.add(app)
        await db.flush()
        for value in ("openid", "entity:profile:read"):
            if value in catalogue["scopes"]:
                db.add(
                    ClientScope(
                        client_id=app.id,
                        scope_id=catalogue["scopes"][value].id,
                        grantable=True,
                    )
                )
        await db.commit()

        tokens = await get_tokens(
            client,
            client_id="reporting",
            redirect_uri="https://reporting.example.org/callback",
            scope="openid offline_access entity:profile:read",
            client_secret=secret,
        )

        body = (
            await client.post(
                "/oauth2/introspect",
                data={
                    "token": tokens["refresh_token"],
                    "token_type_hint": "refresh_token",
                    "client_id": "reporting",
                    "client_secret": secret,
                },
            )
        ).json()

        assert body["active"] is True
        assert body["token_type"] == "refresh_token"

    async def test_garbage_is_inactive_not_an_error(self, client, kiosk):
        _, secret = kiosk
        body = (
            await client.post(
                "/oauth2/introspect",
                data={
                    "token": "nonsense",
                    "client_id": "kiosk",
                    "client_secret": secret,
                },
            )
        ).json()

        assert body == {"active": False}

    async def test_requires_client_authentication(self, client):
        response = await client.post(
            "/oauth2/introspect", data={"token": "x", "client_id": "nope"}
        )
        assert response.status_code == 401

    async def test_public_client_cannot_introspect(self, client):
        """KI-1. The response describes someone else's token, and a client_id is
        public by definition — so it is not a credential (RFC 7662 Section 2.1)."""
        tokens = await get_tokens(client)

        response = await client.post(
            "/oauth2/introspect",
            data={"token": tokens["access_token"], "client_id": "dashboard"},
        )

        assert response.status_code == 401
        assert response.json()["error"] == "invalid_client"

    async def test_confidential_client_without_its_secret_cannot_introspect(
        self, client, kiosk
    ):
        tokens = await get_tokens(client)

        response = await client.post(
            "/oauth2/introspect",
            data={"token": tokens["access_token"], "client_id": "kiosk"},
        )
        assert response.status_code == 401

    async def test_client_with_no_grants_does_not_crash(self, client, kiosk, db):
        """KI-5. The endpoint used to index allowed_grants[0] and 500."""
        from sqlalchemy import select

        from provider.shared.models import Client

        record = await db.scalar(select(Client).where(Client.client_id == "kiosk"))
        record.allowed_grants = []
        db.add(record)
        await db.commit()

        _, secret = kiosk
        response = await client.post(
            "/oauth2/introspect",
            data={"token": "x", "client_id": "kiosk", "client_secret": secret},
        )
        assert response.status_code == 200


class TestLogout:
    async def test_clears_the_session(self, client):
        await get_tokens(client)

        await client.get("/oauth2/logout")

        # A fresh authorize now has to send the browser back to the login page.
        from tests.flows import pkce_pair, start

        _, challenge = pkce_pair()
        response = await start(client, challenge)
        assert "/auth/login" in response.headers["location"]

    async def test_redirects_only_to_a_registered_uri(self, client):
        await get_tokens(client)

        allowed = await client.get(
            "/oauth2/logout",
            params={
                "client_id": "dashboard",
                "post_logout_redirect_uri": "http://localhost:5173/",
            },
        )
        assert allowed.status_code == 303

        blocked = await client.get(
            "/oauth2/logout",
            params={
                "client_id": "dashboard",
                "post_logout_redirect_uri": "http://evil.test/",
            },
        )
        assert blocked.status_code == 204


class TestConcurrentRefresh:
    """KI-16. Rotation makes theft detectable, but two browser tabs refreshing
    in the same instant — or one request that timed out and was retried —
    present the same token twice for entirely honest reasons."""

    async def test_a_retry_gets_the_same_answer(self, client):
        tokens = await get_tokens(client)

        first = (await refresh(client, tokens["refresh_token"])).json()
        retry = (await refresh(client, tokens["refresh_token"])).json()

        assert retry["refresh_token"] == first["refresh_token"]
        assert retry["access_token"] == first["access_token"]

    async def test_a_retry_does_not_sign_the_user_out(self, client):
        """The failure this fixes: an honest double refresh used to look like
        theft, and revoking the family logged the person out of everything."""
        tokens = await get_tokens(client)
        first = (await refresh(client, tokens["refresh_token"])).json()

        await refresh(client, tokens["refresh_token"])

        assert (await refresh(client, first["refresh_token"])).status_code == 200

    async def test_simultaneous_refreshes_both_succeed(self, client):
        tokens = await get_tokens(client)

        both = await asyncio.gather(
            refresh(client, tokens["refresh_token"]),
            refresh(client, tokens["refresh_token"]),
        )

        assert [response.status_code for response in both] == [200, 200]
        assert both[0].json()["refresh_token"] == both[1].json()["refresh_token"]

    async def test_the_replayed_access_token_expires_when_it_always_would(self, client):
        """Repeating the original `expires_in` would overstate the token's life
        by however long the window has been running, and a client trusting that
        would use it past its expiry."""
        tokens = await get_tokens(client)
        first = (await refresh(client, tokens["refresh_token"])).json()

        retry = (await refresh(client, tokens["refresh_token"])).json()

        assert retry["expires_in"] <= first["expires_in"]

    async def test_another_client_gets_no_replay(self, client, third_party):
        """A different client holding the same token is not a retry — it is the
        case rotation exists to catch, so it falls through to detection."""
        tokens = await get_tokens(client)
        await refresh(client, tokens["refresh_token"])

        response = await client.post(
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": "library",
            },
        )

        assert response.status_code == 400
        assert "reuse" in response.json()["error_description"].lower()

    async def test_theft_is_still_caught_once_the_window_passes(self, client, no_grace):
        tokens = await get_tokens(client)
        await refresh(client, tokens["refresh_token"])

        stolen = await refresh(client, tokens["refresh_token"])

        assert stolen.status_code == 400
        assert "reuse" in stolen.json()["error_description"].lower()
