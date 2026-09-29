"""`scripts/cleanup.py` — the only thing that stops two tables growing
for the life of the deployment."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from provider.shared.models import RefreshToken


class TestCleanup:
    """`scripts/cleanup.py` — the only thing that stops two tables growing for
    the life of the deployment."""

    async def test_it_deletes_what_has_expired(self, db, admin_user, dashboard):
        from scripts.cleanup import MARGIN, delete_expired

        stale = _refresh_token(admin_user, dashboard, expires_in=-MARGIN * 2)
        db.add(stale)
        await db.commit()

        counts = await delete_expired(db, datetime.now(UTC) - MARGIN)

        assert counts["refresh_tokens"] == 1
        assert await db.get(RefreshToken, stale.id) is None

    async def test_it_leaves_a_live_token_alone(self, db, admin_user, dashboard):
        from scripts.cleanup import MARGIN, delete_expired

        live = _refresh_token(admin_user, dashboard, expires_in=timedelta(days=30))
        db.add(live)
        await db.commit()

        await delete_expired(db, datetime.now(UTC) - MARGIN)

        assert await db.get(RefreshToken, live.id) is not None

    async def test_it_keeps_a_revoked_token_until_it_expires(
        self, db, admin_user, dashboard
    ):
        """Reuse detection works by finding the spent row and revoking its
        family. Delete it early and a detectable theft becomes an ordinary
        `invalid_grant`."""
        from scripts.cleanup import MARGIN, delete_expired

        spent = _refresh_token(admin_user, dashboard, expires_in=timedelta(days=30))
        spent.revoked_at = datetime.now(UTC)
        db.add(spent)
        await db.commit()

        await delete_expired(db, datetime.now(UTC) - MARGIN)

        assert await db.get(RefreshToken, spent.id) is not None

    async def test_a_dry_run_changes_nothing(self, db, admin_user, dashboard):
        from scripts.cleanup import MARGIN, expired_before

        stale = _refresh_token(admin_user, dashboard, expires_in=-MARGIN * 2)
        db.add(stale)
        await db.commit()

        counts = await expired_before(db, datetime.now(UTC) - MARGIN)

        assert counts["refresh_tokens"] == 1
        assert await db.get(RefreshToken, stale.id) is not None


def _refresh_token(user, client, *, expires_in) -> RefreshToken:
    now = datetime.now(UTC)
    return RefreshToken(
        token_hash=secrets.token_hex(32),
        client_id=client.id,
        user_id=user.id,
        scope="openid",
        acr="urn:iden:acr:sfa",
        amr=["pwd"],
        authenticated_at=now,
        family_id=uuid.uuid4(),
        expires_at=now + expires_in,
    )
