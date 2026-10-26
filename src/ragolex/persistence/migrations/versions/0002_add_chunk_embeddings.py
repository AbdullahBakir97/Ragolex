"""Add an embedding vector and an HNSW index to chunks.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed here on purpose: a migration must create the same schema whenever it
# runs, even after tables.EMBEDDING_DIMENSIONS changes in a later migration.
DIMENSIONS = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("chunks", sa.Column("embedding", Vector(DIMENSIONS), nullable=True))
    op.create_index(
        op.f("ix_chunks_embedding"), "chunks", ["embedding"], unique=False,
        postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_chunks_embedding"), table_name="chunks")
    op.drop_column("chunks", "embedding")
    # The extension stays: other database objects may use it, and creating
    # it again needs more privileges than the app normally has.
