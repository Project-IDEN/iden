"""kiosks, one client each

A kiosk is now a registered device with a client of its own, paired from the
dashboard. The single shared `kiosk` client the seed used to create goes: a
secret every device held could not be revoked for one of them. Faces it
enrolled keep its name in `face_templates.enrolled_by`.

The downgrade does not bring that client back; re-running an older seed does.

Revision ID: 67f4d4854aac
Revises: 642d49881873
Create Date: 2026-10-13 13:55:33.058744
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "67f4d4854aac"
down_revision: str | None = "642d49881873"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kiosks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("paired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_version", sa.String(length=64), nullable=True),
        sa.Column("last_seen_camera", sa.String(length=255), nullable=True),
        sa.Column("last_seen_address", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )
    op.create_index(
        "ix_audit_events_actor_client", "audit_events", ["actor_client"], unique=False
    )
    op.execute("DELETE FROM clients WHERE client_id = 'kiosk' AND is_system")


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor_client", table_name="audit_events")
    op.drop_table("kiosks")
