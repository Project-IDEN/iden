"""TDS section B: boundary values and negative cases on the provider.

These assert the correct, secure behaviour. Where the provider does something
else, the test is marked `xfail(strict=True)` with the finding as its reason: it
stays green until the provider is fixed, then fails so the marker comes off.

`raw` is the in-process client with `raise_app_exceptions=False`, so an
unhandled exception surfaces as the 500 a browser would see instead of
crashing the test.
"""

import base64
import hashlib
import re
from datetime import UTC, datetime

import jwt
import pyotp
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from provider.core.config import settings
from provider.core.security import encrypt_secret
from provider.shared.models import FaceTemplate, TotpCredential, User
from tests.conftest import REDIRECT_URI
from tests.flows import query_of, sign_in, start

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")

MEMBER_EMAIL = "student@test.local"
MEMBER_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
async def raw(client):
    """The app in-process, answering 500 for an unhandled exception rather than raising it."""
    from provider.core.app import app

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url=settings.iden_issuer) as http:
        yield http


def challenge_of(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def authorize_through_login(
    http, challenge: str, email=None, password=None, **params
):
    """Start /authorize, sign in on the challenge, and follow the resume URL once."""
    first = await start(http, challenge, **params)
    if first.status_code != 303 or "challenge" not in query_of(first):
        return first
    login = await sign_in(
        http,
        query_of(first)["challenge"],
        **({"email": email} if email else {}),
        **({"password": password} if password else {}),
    )
    assert login.status_code == 200, login.text
    return await http.get(login.json()["resumeUrl"])


async def exchange(http, code: str, verifier: str):
    return await http.post(
        "/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "client_id": "dashboard",
        },
    )


def refused_without_500(response) -> bool:
    """A 4xx, or an OAuth error delivered to the redirect URI."""
    if response.status_code == 303:
        return "error=" in response.headers["location"]
    return 400 <= response.status_code < 500


class TestB1VerifierLength:
    """RFC 7636 Section 4.1: a code_verifier is 43 to 128 characters."""

    @pytest.mark.parametrize("length", [43, 128])
    async def test_a_verifier_inside_the_range_is_accepted(self, raw, length):
        """A code_verifier of 43 or 128 unreserved characters (the RFC 7636 bounds) is accepted and yields tokens."""
        verifier = "a" * length
        code = query_of(await authorize_through_login(raw, challenge_of(verifier)))[
            "code"
        ]

        response = await exchange(raw, code, verifier)

        assert response.status_code == 200, response.text

    @pytest.mark.parametrize("length", [42, 129])
    @pytest.mark.xfail(
        strict=True,
        reason="TDS B1: a code_verifier outside 43-128 characters is accepted",
    )
    async def test_a_verifier_outside_the_range_is_rejected(self, raw, length):
        """A code_verifier of 42 or 129 characters is rejected with 400, even when it hashes to the challenge."""
        verifier = "a" * length
        code = query_of(await authorize_through_login(raw, challenge_of(verifier)))[
            "code"
        ]

        response = await exchange(raw, code, verifier)

        assert response.status_code == 400, (
            f"{length}-character verifier accepted: {response.status_code}, "
            f"keys {sorted(response.json())}"
        )


class TestB2NonAsciiVerifier:
    @pytest.mark.xfail(
        strict=True, reason="TDS B2: a non-ASCII code_verifier answers 500"
    )
    async def test_a_non_ascii_verifier_is_a_400_not_a_500(self, raw):
        """A code_verifier containing non-ASCII characters is rejected with 400 invalid_grant/invalid_request, not a 500."""
        verifier = "é" * 43
        code = query_of(await authorize_through_login(raw, challenge_of(verifier)))[
            "code"
        ]

        response = await exchange(raw, code, verifier)

        assert response.status_code == 400, (
            f"{response.status_code}: {response.text[:200]}"
        )


class TestB3LongChallenge:
    @pytest.mark.xfail(
        strict=True, reason="TDS B3: a 129-character code_challenge answers 500"
    )
    async def test_a_129_character_code_challenge_is_refused_without_a_500(self, raw):
        """A code_challenge of 129 characters at /oauth2/authorize is answered with an error, not a 500."""
        response = await authorize_through_login(raw, "A" * 129)

        assert refused_without_500(response), (
            f"{response.status_code}: {response.headers.get('location') or response.text[:200]}"
        )


class TestB4FieldLengths:
    async def test_a_255_character_nonce_round_trips(self, raw):
        """A nonce of 255 characters is accepted and returned unchanged in the ID token."""
        verifier = "v" * 64
        nonce = "n" * 255
        response = await authorize_through_login(
            raw, challenge_of(verifier), nonce=nonce
        )
        tokens = (await exchange(raw, query_of(response)["code"], verifier)).json()

        claims = jwt.decode(tokens["id_token"], options={"verify_signature": False})
        assert claims["nonce"] == nonce

    @pytest.mark.xfail(strict=True, reason="TDS B4: a 256-character nonce answers 500")
    async def test_a_256_character_nonce_is_refused_without_a_500(self, raw):
        """A nonce of 256 characters is refused with a 4xx (or an OAuth error redirect), not a 500."""
        response = await authorize_through_login(
            raw, challenge_of("v" * 64), nonce="n" * 256
        )

        assert refused_without_500(response), (
            f"{response.status_code}: {response.headers.get('location') or response.text[:200]}"
        )

    async def test_a_255_character_display_name_is_accepted(self, raw, admin_headers):
        """An administrator can create a user whose displayName is 255 characters."""
        response = await raw.post(
            "/admin/users",
            headers=admin_headers,
            json={
                "emailLocalPart": "long1",
                "username": "long1",
                "displayName": "d" * 255,
            },
        )

        assert response.status_code == 201, response.text

    @pytest.mark.xfail(
        strict=True, reason="TDS B4: a 256-character displayName answers 500"
    )
    async def test_a_256_character_display_name_is_a_4xx_not_a_500(
        self, raw, admin_headers
    ):
        """Creating a user with a 256-character displayName is refused with a 4xx validation error, not a 500."""
        response = await raw.post(
            "/admin/users",
            headers=admin_headers,
            json={
                "emailLocalPart": "long2",
                "username": "long2",
                "displayName": "d" * 256,
            },
        )

        assert 400 <= response.status_code < 500, (
            f"{response.status_code}: {response.text[:200]}"
        )


class TestB5EmailCase:
    @pytest.mark.xfail(
        strict=True, reason="TDS B5: sign-in treats the email as case-sensitive"
    )
    async def test_the_email_signs_in_whatever_its_capitalisation(self, raw):
        """Signing in as Admin@Test.Local reaches the account admin@test.local (email addresses are case-insensitive)."""
        first = await start(raw, challenge_of("c" * 64))

        response = await sign_in(
            raw, query_of(first)["challenge"], email="Admin@Test.Local"
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] in ("complete", "method_required")


class TestB6DisabledAccount:
    @pytest.mark.xfail(
        strict=True,
        reason="TDS B6: a disabled account answers 403 only for the right password",
    )
    async def test_a_disabled_account_answers_the_same_for_any_password(
        self, raw, db, member
    ):
        """A disabled account gives the same status to a wrong and a right password, so it cannot be told apart from a wrong guess."""
        await db.execute(
            update(User).where(User.id == member.id).values(is_active=False)
        )
        await db.commit()
        challenge_id = query_of(await start(raw, challenge_of("d" * 64)))["challenge"]

        wrong = await sign_in(
            raw, challenge_id, email=MEMBER_EMAIL, password="not-the-password"
        )
        right = await sign_in(
            raw, challenge_id, email=MEMBER_EMAIL, password=MEMBER_PASSWORD
        )

        assert wrong.status_code == right.status_code, (
            f"wrong password -> {wrong.status_code} {wrong.json().get('code')}, "
            f"right password -> {right.status_code} {right.json().get('code')}"
        )


class TestB7UserInfoAfterDeactivation:
    @pytest.mark.xfail(
        strict=True, reason="TDS B7: userinfo still answers a deactivated account"
    )
    async def test_userinfo_refuses_a_deactivated_account(
        self, raw, member, admin_headers
    ):
        """After an administrator deactivates an account, /oauth2/userinfo with its still-unexpired access token answers 401."""
        verifier = "u" * 64
        response = await authorize_through_login(
            raw, challenge_of(verifier), email=MEMBER_EMAIL, password=MEMBER_PASSWORD
        )
        tokens = (await exchange(raw, query_of(response)["code"], verifier)).json()

        deactivated = await raw.patch(
            f"/admin/users/{member.id}", headers=admin_headers, json={"isActive": False}
        )
        assert deactivated.status_code == 200, deactivated.text

        userinfo = await raw.get(
            "/oauth2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert userinfo.status_code == 401, (
            f"{userinfo.status_code}: {userinfo.text[:200]}"
        )


class TestB8DeletionErasesBlobs:
    @pytest.mark.xfail(
        strict=True,
        reason="TDS B8: deleting a user leaves their avatar and face images in storage",
    )
    async def test_deleting_a_user_removes_their_photo_and_face_images(
        self, raw, db, member, storage, admin_headers
    ):
        """DELETE /admin/users/{id} removes the person's avatars/ and faces/ objects from blob storage."""
        storage.objects["avatars/tds-photo.webp"] = b"avatar"
        storage.objects["faces/tds-face"] = b"encrypted frame"
        await db.execute(
            update(User)
            .where(User.id == member.id)
            .values(picture_key="tds-photo.webp")
        )
        db.add(
            FaceTemplate(
                user_id=member.id,
                model_version="tds-model",
                embedding_encrypted="v1:placeholder",
                quality=1.0,
                enrolled_by="kiosk",
                image_key="faces/tds-face",
            )
        )
        await db.commit()

        response = await raw.delete(f"/admin/users/{member.id}", headers=admin_headers)

        assert response.status_code == 204, response.text
        left = [
            key
            for key in ("avatars/tds-photo.webp", "faces/tds-face")
            if key in storage.objects
        ]
        assert not left, f"objects left in storage after deleting the user: {left}"


@pytest.fixture
async def member_with_totp(db, member) -> str:
    """The member, with a confirmed authenticator. Returns the TOTP secret."""
    secret = pyotp.random_base32()
    db.add(
        TotpCredential(
            user_id=member.id,
            secret_encrypted=encrypt_secret(secret, context=str(member.id)),
            confirmed_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return secret


class TestB9ResetKeepsTotp:
    async def test_after_a_password_reset_the_authenticator_is_still_demanded(
        self, raw, member_with_totp, mail
    ):
        """A password reset leaves the confirmed authenticator in place: the next sign-in with the new password still answers method_required ["otp"]."""
        requested = await raw.post(
            "/api/v1/auth/password-reset", json={"email": MEMBER_EMAIL}
        )
        assert requested.status_code == 202
        link = re.search(r"token=([\w-]+)", mail[0]["body"])
        assert link is not None, f"no reset link in {mail[0]['body']!r}"
        token = link.group(1)
        new_password = "a-brand-new-password-0001"
        confirmed = await raw.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "newPassword": new_password},
        )
        assert confirmed.status_code == 204, confirmed.text

        challenge_id = query_of(await start(raw, challenge_of("r" * 64)))["challenge"]
        login = await sign_in(
            raw, challenge_id, email=MEMBER_EMAIL, password=new_password
        )

        assert login.status_code == 200, login.text
        assert login.json()["status"] == "method_required"
        assert login.json()["methods"] == ["otp"]


class TestB11CookieAfterTotp:
    @pytest.mark.xfail(
        strict=True, reason="TDS B11: the TOTP step does not re-set iden_session"
    )
    async def test_the_totp_step_refreshes_the_session_cookie(
        self, raw, member_with_totp
    ):
        """After the TOTP step the response re-sets iden_session with Max-Age equal to the sliding session TTL."""
        challenge_id = query_of(await start(raw, challenge_of("t" * 64)))["challenge"]
        await sign_in(raw, challenge_id, email=MEMBER_EMAIL, password=MEMBER_PASSWORD)

        response = await raw.post(
            "/api/v1/auth/totp",
            json={
                "challengeId": challenge_id,
                "code": pyotp.TOTP(member_with_totp).now(),
            },
        )

        assert response.status_code == 200, response.text
        cookie = response.headers.get("set-cookie", "")
        assert "iden_session=" in cookie, (
            f"no Set-Cookie for iden_session after TOTP: {cookie!r}"
        )
        assert f"Max-Age={settings.iden_session_ttl}" in cookie
