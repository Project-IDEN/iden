"""client management needs full administrator

`admin:clients:write` is gone. Changing an OAuth client now requires every
restricted scope (`shared.scopes.FULL_ADMIN_SCOPES`), because a client's
configuration decides who receives its tokens. Deleting the scope row removes it
from every role, user and client through the foreign keys' `ON DELETE CASCADE`.

Restricted scopes are also stripped from developer-owned clients, which the admin
API now refuses to give them: the owner controls where those tokens are delivered.

Data only, and not reversed: the previous release's seed recreates the scope, and
the stripped links were the hole being closed.

Revision ID: 512b1a4a9967
Revises: 9f2512366bf8
Create Date: 2026-09-27 13:32:08.554680
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "512b1a4a9967"
down_revision: str | None = "9f2512366bf8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM scopes WHERE value = 'admin:clients:write'"))
    op.execute(
        sa.text(
            """
            DELETE FROM client_scopes
            WHERE client_id IN (SELECT id FROM clients WHERE owner_user_id IS NOT NULL)
              AND scope_id IN (
                SELECT id FROM scopes
                WHERE is_system
                  AND (value LIKE 'admin:%' OR value LIKE 'biometric:%')
              )
            """
        )
    )


def downgrade() -> None:
    pass
