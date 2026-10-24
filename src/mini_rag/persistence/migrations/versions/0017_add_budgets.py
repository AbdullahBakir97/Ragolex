"""Add a monthly budget per tenant, and the budget alerts sent each month.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("budget_usd_per_month", sa.Numeric(12, 2), nullable=True))
    op.create_table(
        "budget_alerts",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_budget_alerts_tenant_id_tenants"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "period_start", "threshold",
                                name=op.f("pk_budget_alerts")),
    )
    # Usage and the cost history read a project's answers since a date.
    op.create_index("ix_answers_project_id_created_at", "answers", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_answers_project_id_created_at", table_name="answers")
    op.drop_table("budget_alerts")
    op.drop_column("tenants", "budget_usd_per_month")
