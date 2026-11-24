"""add unique constraint to labels

Revision ID: d5e9f1a2b303
Revises: c4d8e2a1b902
Create Date: 2026-11-23 22:50:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "d5e9f1a2b303"
down_revision: str | None = "c4d8e2a1b902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_labels_project_name", "labels", ["project_id", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_labels_project_name", "labels", type_="unique")
