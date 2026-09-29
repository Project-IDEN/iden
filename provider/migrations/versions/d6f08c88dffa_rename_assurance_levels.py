"""rename assurance levels

`iden:loa:1`, `:2` and `:3` become `urn:iden:acr:sfa`, `:mfa` and `:mfa-face`.

Authorization codes and refresh tokens carry the level they were issued at, and
a refresh copies it into the new tokens — so without this, a session signed in
before the upgrade would keep reporting the old names for as long as its
refresh token lives.

Revision ID: d6f08c88dffa
Revises: 512b1a4a9967
Create Date: 2026-09-29 14:47:14.786778
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6f08c88dffa"
down_revision: str | None = "512b1a4a9967"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMES = {
    "iden:loa:1": "urn:iden:acr:sfa",
    "iden:loa:2": "urn:iden:acr:mfa",
    "iden:loa:3": "urn:iden:acr:mfa-face",
}


def _rename(mapping: dict[str, str]) -> None:
    for table in ("authorization_codes", "refresh_tokens"):
        for old, new in mapping.items():
            op.execute(
                sa.text(f"UPDATE {table} SET acr = :new WHERE acr = :old").bindparams(
                    old=old, new=new
                )
            )


def upgrade() -> None:
    _rename(RENAMES)


def downgrade() -> None:
    _rename({new: old for old, new in RENAMES.items()})
