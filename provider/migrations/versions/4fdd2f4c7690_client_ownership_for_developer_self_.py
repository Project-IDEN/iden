"""client ownership for developer self-service

Nullable by design: every client that exists before this migration belongs to
the organization, which is what NULL means. Only `/developer/clients` sets it.

The foreign key is named rather than left to autogenerate, which emitted
`None` — readable in `\\d clients`, and a downgrade cannot drop a constraint
whose name it does not know.

Revision ID: 4fdd2f4c7690
Revises: af3233085cc3
Create Date: 2026-09-22 11:42:45.615280
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4fdd2f4c7690"
down_revision: str | None = "af3233085cc3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_clients_owner_user_id_users"


def upgrade() -> None:
    op.add_column("clients", sa.Column("owner_user_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_clients_owner_user_id"), "clients", ["owner_user_id"], unique=False
    )
    op.create_foreign_key(
        FK_NAME, "clients", "users", ["owner_user_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(FK_NAME, "clients", type_="foreignkey")
    op.drop_index(op.f("ix_clients_owner_user_id"), table_name="clients")
    op.drop_column("clients", "owner_user_id")
