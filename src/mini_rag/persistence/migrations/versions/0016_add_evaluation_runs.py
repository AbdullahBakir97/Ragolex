"""Keep the summary of each evaluation run, for the admin dashboard.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset", sa.String(length=255), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=True),
        sa.Column("cases", sa.Integer(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("answer_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_evaluation_runs_tenant_id_tenants"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_runs")),
    )
    op.create_index("ix_evaluation_runs_tenant_id_created_at", "evaluation_runs",
                    ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_tenant_id_created_at", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
