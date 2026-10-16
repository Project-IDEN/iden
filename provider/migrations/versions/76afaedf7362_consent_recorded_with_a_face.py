"""consent recorded with a face

When a person agreed at the kiosk, and to which wording. Nullable: faces
enrolled before consent was asked for have neither.

Revision ID: 76afaedf7362
Revises: cec867ddacde
Create Date: 2026-10-16 13:30:15.941937
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "76afaedf7362"
down_revision: str | None = "cec867ddacde"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "face_templates",
        sa.Column("consent_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "face_templates",
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("face_templates", "consented_at")
    op.drop_column("face_templates", "consent_version")
