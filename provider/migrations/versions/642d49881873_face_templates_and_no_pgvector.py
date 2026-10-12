"""face templates, and no pgvector

Faces are enrolled as encrypted embeddings, several per person, and compared
1:1 in the engine. Nothing searches them, so the pgvector extension the initial
schema created goes: IDEN then runs on any PostgreSQL 18.

The downgrade does not recreate the extension. Nothing before this revision
used it either, and recreating it would fail on a server without it installed.

Revision ID: 642d49881873
Revises: d6f08c88dffa
Create Date: 2026-10-12 20:47:43.717780
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "642d49881873"
down_revision: str | None = "d6f08c88dffa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "face_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("embedding_encrypted", sa.Text(), nullable=False),
        sa.Column("quality", sa.Float(), nullable=False),
        sa.Column("enrolled_by", sa.String(length=255), nullable=False),
        sa.Column("image_key", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_face_templates_user_id"), "face_templates", ["user_id"], unique=False
    )
    op.execute("DROP EXTENSION IF EXISTS vector")


def downgrade() -> None:
    op.drop_index(op.f("ix_face_templates_user_id"), table_name="face_templates")
    op.drop_table("face_templates")
