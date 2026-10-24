"""Add each project's assistant (its name and instructions) and widgets' logos.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("assistant_name", sa.String(length=60), nullable=True))
    op.add_column("projects", sa.Column("instructions", sa.Text(), nullable=True))
    op.add_column("widgets", sa.Column("logo_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("widgets", "logo_url")
    op.drop_column("projects", "instructions")
    op.drop_column("projects", "assistant_name")
