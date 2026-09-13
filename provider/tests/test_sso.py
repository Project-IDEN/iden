"""Phase 3.1 and 3.2 — the session behind single sign-on, and the parameters a
relying party uses to steer it."""

from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from provider.authz.services import session_store
from tests.conftest import ADMIN_EMAIL, THIRD_PARTY_REDIRECT
from tests.flows import (
    REDIRECT_URI,
    authorize_params,
    get_tokens,
    pkce_pair,
    query_of,
    sign_in,
)

pytestmark = pytest.mark.usefixtures("admin_user", "dashboard")


def decode(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def query_of_url(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def authorize(client, **overrides):
    """One /authorize hop with an existing cookie, following no redirects."""
    _, challenge = pkce_pair()
    return await client.get(
        "/oauth2/authorize", params=authorize_params(challenge, **overrides)
    )


class TestSingleSignOn:
    async def test_a_second_application_needs_no_prompt(self, client, kiosk, db):
        """The property the whole phase exists to protect: one login, and the
        next client gets a code straight back."""
        await get_tokens(client)  # signs in through the dashboard

        second = await authorize(client, client_id="dashboard", state="second")

        assert second.status_code == 303
        assert "code" in query_of(second)

    async def test_the_session_is_named_in_the_id_token(self, client):
        tokens = await get_tokens(client)
        claims = decode(tokens["id_token"])

        assert claims["sid"]
        assert claims["auth_time"] <= claims["iat"]

    async def test_both_applications_are_told_the_same_session(self, client):
        """A shared `sid` is what lets one logout end both."""
        first = decode((await get_tokens(client))["id_token"])
        second = decode((await get_tokens(client))["id_token"])

        assert first["sid"] == second["sid"]

    async def test_auth_time_is_the_login_not_the_code(self, client):
        """On the second application these differ by the age of the session.
        A client's `max_age` is measured against `auth_time`, so taking it from
        the code's creation would make every session look freshly authenticated."""
        first = decode((await get_tokens(client))["id_token"])
        second = decode((await get_tokens(client))["id_token"])

        assert first["auth_time"] == second["auth_time"]
        assert second["iat"] >= second["auth_time"]

    async def test_the_session_records_which_clients_it_reached(self, client, redis):
        await get_tokens(client)
        cookie = client.cookies["iden_session"]

        assert await session_store.clients_for(redis, cookie) == {"dashboard"}

    async def test_the_sid_claim_is_not_the_session_cookie(self, client):
        """The cookie is a bearer credential. Publishing it as `sid` would hand
        every client, and anyone reading a token in transit, the ability to
        become the user."""
        tokens = await get_tokens(client)
        sid = decode(tokens["id_token"])["sid"]

        assert sid != client.cookies["iden_session"]

        # Present the published sid as though it were the cookie.
        client.cookies.set("iden_session", sid)
        response = await authorize(client)

        assert "/auth/login" in response.headers["location"]


class TestPromptNone:
    async def test_returns_a_code_when_a_session_exists(self, client):
        await get_tokens(client)

        response = await authorize(client, prompt="none")

        assert response.status_code == 303
        assert "code" in query_of(response)

    async def test_returns_login_required_with_no_session(self, client):
        response = await authorize(client, prompt="none")

        assert response.headers["location"].startswith(REDIRECT_URI)
        assert query_of(response)["error"] == "login_required"

    async def test_creates_no_challenge(self, client, redis):
        """A challenge is the pending half of an interaction. One left behind
        for an interaction that will never happen is a leak and a lie."""
        await authorize(client, prompt="none")

        assert await redis.keys("challenge:*") == []

    async def test_returns_consent_required_when_consent_is_missing(
        self, client, third_party
    ):
        await get_tokens(client)

        response = await authorize(
            client,
            client_id="library",
            redirect_uri=THIRD_PARTY_REDIRECT,
            prompt="none",
            scope="openid entity:profile:read",
        )

        assert query_of(response)["error"] == "consent_required"

    async def test_cannot_be_combined_with_other_values(self, client):
        response = await authorize(client, prompt="none login")

        assert query_of(response)["error"] == "invalid_request"

    async def test_an_unknown_prompt_value_is_refused(self, client):
        assert query_of(await authorize(client, prompt="teleport"))["error"] == (
            "invalid_request"
        )

    async def test_the_state_comes_back_with_the_error(self, client):
        """Without it the client cannot match the refusal to the request it made."""
        response = await authorize(client, prompt="none", state="xyz")

        assert query_of(response)["state"] == "xyz"


class TestMaxAge:
    async def test_zero_forces_a_fresh_login(self, client):
        await get_tokens(client)

        response = await authorize(client, max_age=0)

        assert "/auth/login" in response.headers["location"]

    async def test_a_generous_value_leaves_the_session_alone(self, client):
        await get_tokens(client)

        response = await authorize(client, max_age=3600)

        assert "code" in query_of(response)

    async def test_a_stale_session_is_login_required_when_silent(self, client):
        await get_tokens(client)

        response = await authorize(client, max_age=0, prompt="none")

        assert query_of(response)["error"] == "login_required"

    async def test_re_authenticating_keeps_the_session_id(self, client):
        """`prompt=login` must not mint a new session: the old one would be
        stranded in Redis, and every client holding the old sid would never be
        signed out."""
        before = decode((await get_tokens(client))["id_token"])["sid"]

        response = await authorize(client, prompt="login")
        challenge_id = query_of(response)["challenge"]
        await sign_in(client, challenge_id)

        after = decode((await get_tokens(client))["id_token"])["sid"]
        assert before == after


class TestPromptLoginAndConsent:
    async def test_login_prompts_despite_a_live_session(self, client):
        await get_tokens(client)

        response = await authorize(client, prompt="login")

        assert "/auth/login" in response.headers["location"]

    async def test_select_account_is_treated_as_login(self, client):
        await get_tokens(client)

        response = await authorize(client, prompt="select_account")

        assert "/auth/login" in response.headers["location"]

    async def test_consent_asks_again_for_a_first_party_client(self, client):
        """`skip_consent` is the client's default, not a veto over the request."""
        await get_tokens(client)

        response = await authorize(client, prompt="consent")

        assert "/auth/consent" in response.headers["location"]


async def play_the_auth_ui(client, response) -> tuple[dict[str, str], list[str]]:
    """Sign in or approve whatever is asked, following the way back each time,
    until the client has its answer. Returns that answer and the screens shown.

    A screen shown twice fails at once rather than looping: that is the bug this
    exists to catch.
    """
    shown: list[str] = []
    while "/auth/" in response.headers["location"]:
        screen = urlparse(response.headers["location"]).path
        assert screen not in shown, f"{screen} asked for again after {shown}"
        shown.append(screen)

        challenge_id = query_of(response)["challenge"]
        if screen == "/auth/login":
            step = await sign_in(client, challenge_id)
            onward = step.json()["resumeUrl"]
        else:
            step = await client.post(
                "/api/v1/auth/consent",
                json={"challengeId": challenge_id, "approved": True},
            )
            onward = step.json()["redirectUrl"]
        response = await client.get(onward)

    return query_of(response), shown


class TestTheWayBack:
    """The resume URL carries the original request, `prompt` and `max_age`
    included. Each of these once demanded again the interaction it had just
    been given, forever — and the tests above never noticed, because they stop
    at the first redirect."""

    @pytest.mark.parametrize(
        ("prompt", "screens"),
        [
            ("login", ["/auth/login"]),
            ("select_account", ["/auth/login"]),
            ("consent", ["/auth/consent"]),
            ("login consent", ["/auth/login", "/auth/consent"]),
        ],
    )
    async def test_a_prompt_is_satisfied_once(self, client, prompt, screens):
        await get_tokens(client)

        answer, shown = await play_the_auth_ui(
            client, await authorize(client, prompt=prompt)
        )

        assert shown == screens
        assert "code" in answer

    async def test_max_age_zero_is_met_by_the_sign_in_it_asked_for(self, client):
        await get_tokens(client)

        answer, shown = await play_the_auth_ui(
            client, await authorize(client, max_age=0)
        )

        assert shown == ["/auth/login"]
        assert "code" in answer

    async def test_max_age_zero_from_a_cold_browser_signs_in_once(self, client):
        answer, shown = await play_the_auth_ui(
            client, await authorize(client, max_age=0)
        )

        assert shown == ["/auth/login"]
        assert "code" in answer

    async def test_a_consent_does_not_carry_over_to_another_request(self, client):
        """The challenge vouches for one request. Presented with different
        parameters it vouches for nothing."""
        await get_tokens(client)
        asked = await authorize(client, prompt="consent")
        approved = await client.post(
            "/api/v1/auth/consent",
            json={"challengeId": query_of(asked)["challenge"], "approved": True},
        )

        params = query_of_url(approved.json()["redirectUrl"])
        response = await client.get(
            "/oauth2/authorize", params={**params, "scope": "openid"}
        )

        assert "/auth/consent" in response.headers["location"]

    async def test_a_spent_resume_url_vouches_for_nothing(self, client):
        """Replayed after the code was issued, the resume URL is a new request
        again — and `prompt=login` asks again, as it should."""
        await get_tokens(client)
        asked = await authorize(client, prompt="login")
        step = await sign_in(client, query_of(asked)["challenge"])
        resume_url = step.json()["resumeUrl"]
        assert "code" in query_of(await client.get(resume_url))

        replayed = await client.get(resume_url)

        assert "/auth/login" in replayed.headers["location"]


MEMBER = {"email": "student@test.local", "password": "correct-horse-battery-staple"}


async def id_token_of_member(client) -> str:
    """A real ID token for the member, from a browser of its own."""
    client.cookies.clear()
    verifier, challenge = pkce_pair()
    response = await client.get("/oauth2/authorize", params=authorize_params(challenge))
    step = await sign_in(client, query_of(response)["challenge"], **MEMBER)
    code = query_of(await client.get(step.json()["resumeUrl"]))["code"]
    tokens = await client.post(
        "/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "client_id": "dashboard",
        },
    )
    client.cookies.clear()
    return tokens.json()["id_token"]


class TestIdTokenHint:
    async def test_a_matching_hint_is_transparent(self, client):
        tokens = await get_tokens(client)

        response = await authorize(client, id_token_hint=tokens["id_token"])

        assert "code" in query_of(response)

    async def test_a_hint_for_someone_else_ignores_the_session(self, client, db):
        """The client is asking about a different account, so the session in
        hand is not the one it wants."""
        tokens = await get_tokens(client)
        claims = decode(tokens["id_token"])

        # Not signed with IDEN's key, so it fails verification — which counts as
        # a mismatch rather than as no hint at all: an unverifiable hint is not
        # a statement IDEN ever made.
        forged = jwt.encode({**claims, "sub": str(claims["sid"])}, "k" * 32)
        response = await authorize(client, id_token_hint=forged)

        assert "/auth/login" in response.headers["location"]

    async def test_the_person_named_signing_in_gets_a_code(self, client, member):
        hint = await id_token_of_member(client)
        await get_tokens(client)  # the administrator, in this browser

        response = await authorize(client, id_token_hint=hint)
        step = await sign_in(client, query_of(response)["challenge"], **MEMBER)
        answer = query_of(await client.get(step.json()["resumeUrl"]))

        assert "code" in answer

    async def test_someone_else_signing_in_ends_the_request(self, client, member):
        """The administrator signs in again, and is still not the member the
        client asked about. Showing the form again would show it forever."""
        hint = await id_token_of_member(client)
        await get_tokens(client)

        response = await authorize(client, id_token_hint=hint)
        step = await sign_in(client, query_of(response)["challenge"])
        answer = query_of(await client.get(step.json()["resumeUrl"]))

        assert answer["error"] == "login_required"
        assert answer["state"] == "xyz"

    async def test_an_expired_hint_still_counts(self, client):
        """ID tokens live ten minutes; a hint about a past login is expected to
        be expired, and rejecting it would break SSO for anyone who paused."""
        tokens = await get_tokens(client)
        claims = decode(tokens["id_token"])
        assert claims["exp"] > 0

        response = await authorize(client, id_token_hint=tokens["id_token"])
        assert "code" in query_of(response)


class TestLoginHint:
    async def test_reaches_the_auth_ui_through_the_challenge(self, client):
        response = await authorize(client, login_hint=ADMIN_EMAIL)
        challenge_id = query_of(response)["challenge"]

        body = (await client.get(f"/api/v1/auth/challenge/{challenge_id}")).json()

        assert body["loginHint"] == ADMIN_EMAIL

    async def test_is_not_an_assertion_of_identity(self, client):
        """A hint prefills a form. It must not sign anyone in."""
        response = await authorize(client, login_hint=ADMIN_EMAIL)

        assert "/auth/login" in response.headers["location"]
