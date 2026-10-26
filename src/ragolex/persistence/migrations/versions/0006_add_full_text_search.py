"""Add full-text search to chunks, for hybrid search.

A stored generated column keeps each chunk's words (English stemming),
with a GIN index. Adding it computes the column for existing chunks.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column(
        "search_vector", postgresql.TSVECTOR(),
        sa.Computed("to_tsvector('english', text)", persisted=True), nullable=True))
    op.create_index("ix_chunks_search_vector", "chunks", ["search_vector"], unique=False,
                    postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_chunks_search_vector", table_name="chunks", postgresql_using="gin")
    op.drop_column("chunks", "search_vector")
