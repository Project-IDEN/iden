"""The gate every resource-server route in Phase 2 onward depends on.

No such route exists yet, so these tests mount a minimal app of their own —
which is also the clearest way to show what the dependency actually enforces.
"""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from provider.authz.services import token_service as tokens
from provider.core.auth import AccessToken, require_scope
from provider.core.redis import get_redis

pytestmark = pytest.mark.usefixtures("catalogue")


@pytest.fixture
async def guarded(redis):
    app = FastAPI()

    @app.get("/admin/users")
    async def admin_route(
        token: AccessToken = Depends(require_scope("admin:users:read")),
    ):
        return {"sub": token.subject}

    @app.get("/entity/profile")
    async def entity_route(
        token: AccessToken = Depends(require_scope("entity:profile:read")),
    ):
        return {"sub": token.subject}

    app.dependency_overrides[get_redis] = lambda: redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://guarded") as http:
        yield http


@pytest.fixture
async def mint(db, admin_user, dashboard):
    async def _mint(*scopes: str):
        token, jti, _ = await tokens.mint_access_token(
            db,
            subject=str(admin_user.id),
            client=dashboard,
            scopes=set(scopes),
            acr="urn:iden:acr:sfa",
            amr=["pwd"],
        )
        return token, jti

    return _mint


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_valid_token_with_the_scope_is_allowed(guarded, mint, admin_user):
    token, _ = await mint("admin:users:read")
    response = await guarded.get("/admin/users", headers=bearer(token))

    assert response.status_code == 200
    assert response.json()["sub"] == str(admin_user.id)


async def test_missing_token_is_401_with_a_challenge_header(guarded):
    """401 means authenticate again, so the client is told how."""
    response = await guarded.get("/admin/users")

    assert response.status_code == 401
    assert "www-authenticate" in response.headers


async def test_wrong_auth_scheme_is_401(guarded, mint):
    token, _ = await mint("admin:users:read")
    response = await guarded.get(
        "/admin/users", headers={"Authorization": f"Basic {token}"}
    )

    assert response.status_code == 401


async def test_right_audience_but_missing_scope_is_403(guarded, mint):
    """403 means authentication will not help — retrying a login cannot add a
    scope the user does not hold."""
    token, _ = await mint("admin:groups:read")
    response = await guarded.get("/admin/users", headers=bearer(token))

    assert response.status_code == 403
    # `detail`, not `message`: this fixture mounts a bare app to isolate the
    # dependency, so the provider's error-shape handler is not in the way.
    assert "admin:users:read" in response.json()["detail"]


async def test_token_for_another_api_is_401_not_403(guarded, mint):
    """Audience is part of validating the token, so it is checked before scopes.
    An entity token at an admin route is not a permission problem — that token
    was never meant for this API at all."""
    token, _ = await mint("entity:profile:read")
    response = await guarded.get("/admin/users", headers=bearer(token))

    assert response.status_code == 401


async def test_tampered_signature_is_401(guarded, mint):
    token, _ = await mint("admin:users:read")
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")

    response = await guarded.get("/admin/users", headers=bearer(tampered))
    assert response.status_code == 401


async def test_revoked_token_is_401(guarded, mint, redis):
    token, jti = await mint("admin:users:read")
    assert (await guarded.get("/admin/users", headers=bearer(token))).status_code == 200

    await tokens.denylist_access_token(redis, jti, 9_999_999_999)

    assert (await guarded.get("/admin/users", headers=bearer(token))).status_code == 401


async def test_expired_token_is_401(guarded, mint, monkeypatch):
    from datetime import UTC, datetime, timedelta

    past = datetime.now(UTC) - timedelta(hours=1)
    monkeypatch.setattr(tokens, "now", lambda: past)
    token, _ = await mint("admin:users:read")
    monkeypatch.undo()

    assert (await guarded.get("/admin/users", headers=bearer(token))).status_code == 401
