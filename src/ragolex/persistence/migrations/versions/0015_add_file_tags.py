"""Add tags to files, grouping them into collections, and to the sources and widgets using them.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("files", sa.Column("tags", postgresql.ARRAY(sa.Text()),
                                     server_default=sa.text("'{}'"), nullable=False))
    op.create_index("ix_files_tags", "files", ["tags"], postgresql_using="gin")
    for table in ("sources", "widgets"):
        op.add_column(table, sa.Column("tags", postgresql.ARRAY(sa.Text()),
                                       server_default=sa.text("'{}'"), nullable=False))


def downgrade() -> None:
    for table in ("sources", "widgets"):
        op.drop_column(table, "tags")
    op.drop_index("ix_files_tags", table_name="files")
    op.drop_column("files", "tags")
