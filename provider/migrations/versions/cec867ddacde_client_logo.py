"""a logo per client, for the consent screen

The file name of the stored image; the image itself is in blob storage.

Revision ID: cec867ddacde
Revises: 67f4d4854aac
Create Date: 2026-10-13 15:15:13.653118
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cec867ddacde"
down_revision: str | None = "67f4d4854aac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("logo_key", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "logo_key")
