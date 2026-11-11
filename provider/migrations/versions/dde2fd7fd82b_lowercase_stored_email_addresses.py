"""lowercase stored email addresses

Sign-in and password recovery now lowercase the address they are given, so a
stored address with a capital in it could never be matched again. Only the
bootstrap administrator could have one: its address came from the environment
as typed, where every other account's was lowercased when it was created.

Not reversible: the original capitalisation is not kept.

Revision ID: dde2fd7fd82b
Revises: 76afaedf7362
Create Date: 2026-11-11 11:17:45.754302
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dde2fd7fd82b"
down_revision: str | None = "76afaedf7362"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Two accounts that differ only by case would both become one address, and
    # the unique index would stop the upgrade halfway with an IntegrityError
    # that names neither. Stop first, and say which.
    clashes = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT lower(email) FROM users GROUP BY lower(email) "
                "HAVING count(*) > 1"
            )
        )
        .scalars()
        .all()
    )
    if clashes:
        raise RuntimeError(
            "These addresses belong to more than one account, differing only by "
            f"capitalisation: {', '.join(clashes)}. Delete or rename one account "
            "of each, then upgrade again."
        )
    op.execute("UPDATE users SET email = lower(email) WHERE email <> lower(email)")


def downgrade() -> None:
    pass
