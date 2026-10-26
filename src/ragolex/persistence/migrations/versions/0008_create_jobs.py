"""Create the table for background jobs that process and index files.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("overlap_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=True),
        sa.Column("progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("chunks_count", sa.Integer(), nullable=True),
        sa.Column("error_signal", sa.String(length=64), nullable=True),
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')",
                           name=op.f("ck_jobs_status")),
        sa.CheckConstraint("stage IN ('processing', 'indexing')", name=op.f("ck_jobs_stage")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                name=op.f("fk_jobs_project_id_projects"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"],
                                name=op.f("fk_jobs_file_id_files"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index("ix_jobs_project_id_created_at", "jobs", ["project_id", "created_at"])
    op.create_index(op.f("ix_jobs_file_id"), "jobs", ["file_id"])
    op.create_index("ix_jobs_run_after", "jobs", ["run_after"],
                    postgresql_where=sa.text("status = 'queued'"))
    op.create_index("ix_jobs_locked_until", "jobs", ["locked_until"],
                    postgresql_where=sa.text("status = 'running'"))


def downgrade() -> None:
    op.drop_index("ix_jobs_locked_until", table_name="jobs",
                  postgresql_where=sa.text("status = 'running'"))
    op.drop_index("ix_jobs_run_after", table_name="jobs",
                  postgresql_where=sa.text("status = 'queued'"))
    op.drop_index(op.f("ix_jobs_file_id"), table_name="jobs")
    op.drop_index("ix_jobs_project_id_created_at", table_name="jobs")
    op.drop_table("jobs")
