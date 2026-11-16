"""add password_changed_at to users

Revision ID: c4d8e2a1b902
Revises: b3c9e1f2a401
Create Date: 2026-11-12 23:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "c4d8e2a1b902"
down_revision: str | None = "b3c9e1f2a401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "password_changed_at",
            sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
