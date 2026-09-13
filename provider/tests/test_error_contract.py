"""One body shape for every refusal, and what a caller sees in an outage."""

import pytest
from redis.exceptions import ConnectionError
from sqlalchemy.exc import OperationalError

from tests.flows import pkce_pair, query_of, sign_in, start


class TestErrorContract:
    """One body shape everywhere except the OAuth endpoints, which keep the
    RFC 6749 format because a client library will not understand anything else."""

    async def test_a_domain_error_uses_the_contract(self, client, admin_headers):
        response = await client.get(
            "/admin/apis/00000000-0000-0000-0000-000000000000",
            headers=admin_headers,
        )

        assert response.status_code == 404
        assert set(response.json()) == {"code", "message", "details"}

    async def test_a_dependency_failure_uses_the_same_shape(self, client, catalogue):
        """`require_scope` raises HTTPException, which Starlette renders as
        `{"detail": ...}` — a second dialect from the same server."""
        response = await client.get("/admin/users")

        assert response.status_code == 401
        assert set(response.json()) == {"code", "message", "details"}
        assert response.json()["code"] == "unauthorized"

    async def test_the_authenticate_header_survives(self, client, catalogue):
        """RFC 6750 puts the machine-readable part of a 401 in the header, so
        reshaping the body must not drop it."""
        response = await client.get("/admin/users")

        assert response.headers["www-authenticate"] == 'Bearer realm="iden"'

    async def test_an_unrouted_path_uses_the_contract(self, client):
        response = await client.get("/nope")

        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    async def test_a_malformed_body_names_the_fields(self, client, admin_headers):
        response = await client.post(
            "/admin/apis", json={"name": "x"}, headers=admin_headers
        )

        body = response.json()
        assert response.status_code == 422
        assert body["code"] == "validation_error"
        assert any("audience" in field["field"] for field in body["details"]["fields"])

    async def test_a_malformed_oauth_request_stays_rfc_6749(self, client, catalogue):
        """FastAPI's validation error would hand a client library a body it has
        no way to read. RFC 6749 Section 5.2 calls this `invalid_request`."""
        response = await client.post("/oauth2/token", data={})

        assert response.status_code == 400
        assert response.json()["error"] == "invalid_request"
        assert "code" not in response.json()


@pytest.mark.usefixtures("admin_user", "dashboard")
class TestSignInRefusalsKeepTheirCode:
    """The sign-in steps choose their own status, and the domain code has to
    survive that: a wrong code and a missing authenticator are both a 400, and
    the Auth UI can tell them apart by nothing else."""

    async def test_a_wrong_password(self, client):
        _, challenge = pkce_pair()
        challenge_id = query_of(await start(client, challenge))["challenge"]

        response = await sign_in(client, challenge_id, password="not-the-password")

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"

    async def test_a_code_from_someone_with_no_authenticator(self, client):
        _, challenge = pkce_pair()
        challenge_id = query_of(await start(client, challenge))["challenge"]
        await sign_in(client, challenge_id)

        response = await client.post(
            "/api/v1/auth/totp", json={"challengeId": challenge_id, "code": "000000"}
        )

        assert response.status_code == 400
        assert response.json()["code"] == "totp_not_enrolled"

    async def test_an_expired_challenge(self, client):
        response = await client.get("/api/v1/auth/challenge/gone")

        assert response.status_code == 404
        assert response.json()["code"] == "challenge_not_found"


class TestDependencyOutage:
    """Failure injection: what a caller sees when a store is unreachable.

    The answer has to be a documented one. An unhandled exception reaches the
    ASGI server, which answers `Internal Server Error` as plain text — a body
    shape that appears for the first time at the worst possible moment.
    """

    async def test_redis_down_is_503_not_500(self, client, catalogue, redis):
        """Login needs Redis for the rate-limit counter before it does anything
        else, so this is the first thing a caller hits in an outage."""
        working = redis.connection_pool
        redis.connection_pool = _Refusing()
        try:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "someone@localhost", "password": "whatever"},
            )
        finally:
            # Restored here rather than by monkeypatch: the `redis` fixture
            # flushes on the way out, and it does that before monkeypatch undoes
            # anything.
            redis.connection_pool = working

        assert response.status_code == 503
        assert response.json()["code"] == "service_unavailable"
        assert response.headers["retry-after"] == "5"

    async def test_the_database_down_is_503_not_500(self, client, admin_headers):
        from provider.core.app import app
        from provider.core.db import get_db_session

        async def refusing():
            raise OperationalError("select 1", {}, ConnectionRefusedError())
            yield  # pragma: no cover — unreachable, but this must be a generator

        app.dependency_overrides[get_db_session] = refusing

        response = await client.get("/admin/users", headers=admin_headers)

        assert response.status_code == 503
        assert response.json()["code"] == "service_unavailable"

    async def test_a_programming_error_is_still_a_500(self, client, monkeypatch):
        """503 says *try again*. A bug will fail identically on the retry, so
        reporting one as the other sends an operator hunting an outage that is
        not happening."""
        from provider.core import router as router_module

        async def broken(*args, **kwargs):
            raise ValueError("this is a bug, not an outage")

        monkeypatch.setattr(router_module, "_dependencies", broken)

        with pytest.raises(ValueError):
            await client.get("/health/ready")


class _Refusing:
    """A connection pool that cannot hand out a connection."""

    async def get_connection(self, *args, **kwargs):
        raise ConnectionError("Error connecting to Redis.")

    def get_encoder(self):
        raise ConnectionError("Error connecting to Redis.")

    async def disconnect(self, *args, **kwargs):
        return None
