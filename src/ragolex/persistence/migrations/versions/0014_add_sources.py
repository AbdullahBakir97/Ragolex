"""Add sources (websites crawled into a project) and the pages they stored.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("max_pages", sa.Integer(), nullable=False),
        sa.Column("sync_interval_hours", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                name=op.f("fk_sources_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
    )
    op.create_index(op.f("ix_sources_project_id"), "sources", ["project_id"])
    op.create_index("ix_sources_next_sync_at", "sources", ["next_sync_at"],
                    postgresql_where=sa.text("next_sync_at IS NOT NULL"))
    op.create_table(
        "source_pages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("owns_file", sa.Boolean(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"],
                                name=op.f("fk_source_pages_file_id_files"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"],
                                name=op.f("fk_source_pages_source_id_sources"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_pages")),
        sa.UniqueConstraint("source_id", "url", name=op.f("uq_source_pages_source_id_url")),
    )
    op.create_index(op.f("ix_source_pages_file_id"), "source_pages", ["file_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_source_pages_file_id"), table_name="source_pages")
    op.drop_table("source_pages")
    op.drop_index("ix_sources_next_sync_at", table_name="sources")
    op.drop_index(op.f("ix_sources_project_id"), table_name="sources")
    op.drop_table("sources")
