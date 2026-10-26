"""Add per-tenant limits, and a table that counts requests per minute.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("requests_per_minute", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("answers_per_month", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("storage_mb", sa.Integer(), nullable=True))
    op.create_table(
        "request_counts",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_request_counts_tenant_id_tenants"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", "window_start", name=op.f("pk_request_counts")),
    )


def downgrade() -> None:
    op.drop_table("request_counts")
    op.drop_column("tenants", "storage_mb")
    op.drop_column("tenants", "answers_per_month")
    op.drop_column("tenants", "requests_per_minute")
