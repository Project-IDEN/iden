"""consent wordings

The words behind each consent version, so a face's `consent_version` still
names readable words after the text changes. Seeded with the wording kiosks
showed until now, in both its forms (photos kept or not), so faces already
enrolled under it resolve.

Revision ID: b096f481ce07
Revises: dde2fd7fd82b
Create Date: 2026-11-13 17:54:44
"""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b096f481ce07"
down_revision: str | None = "dde2fd7fd82b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TITLE = "Before we take your photos"


def _first_wording(kept: bool) -> list[str]:
    photos = (
        "The photos are also kept, encrypted, so your face can be processed "
        "again when the system is upgraded."
        if kept
        else "The photos themselves are not kept."
    )
    return [
        "This kiosk will take a few photos of your face while you follow the "
        "instructions on the screen.",
        "IDEN turns them into a face template — numbers that describe your face — "
        "and stores it, encrypted, with your account. " + photos,
        "You can then use your face as a second step when you sign in. A face "
        "already enrolled on your account is replaced, and we email you to confirm.",
        "Taking part is your choice. You can remove your face at any time from "
        "Security in your account, and without it you sign in as you do today.",
    ]


def _version(statements: list[str]) -> str:
    words = json.dumps([TITLE, *statements], ensure_ascii=False)
    return hashlib.sha256(words.encode()).hexdigest()[:16]


def upgrade() -> None:
    table = op.create_table(
        "consent_wordings",
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "statements", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("version"),
    )
    rows = []
    for kept in (False, True):
        statements = _first_wording(kept)
        rows.append(
            {"version": _version(statements), "title": TITLE, "statements": statements}
        )
    op.bulk_insert(table, rows)


def downgrade() -> None:
    op.drop_table("consent_wordings")
