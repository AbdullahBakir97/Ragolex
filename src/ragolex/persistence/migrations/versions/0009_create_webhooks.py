"""Create the tables for webhooks and their deliveries.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("events", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("secret", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                name=op.f("fk_webhooks_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhooks")),
    )
    op.create_index(op.f("ix_webhooks_project_id"), "webhooks", ["project_id"])
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("webhook_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'delivered', 'failed')",
                           name=op.f("ck_webhook_deliveries_status")),
        sa.ForeignKeyConstraint(["webhook_id"], ["webhooks.id"],
                                name=op.f("fk_webhook_deliveries_webhook_id_webhooks"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )
    op.create_index("ix_webhook_deliveries_webhook_id_created_at", "webhook_deliveries",
                    ["webhook_id", "created_at"])
    op.create_index("ix_webhook_deliveries_next_attempt_at", "webhook_deliveries",
                    ["next_attempt_at"], postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_next_attempt_at", table_name="webhook_deliveries",
                  postgresql_where=sa.text("status = 'pending'"))
    op.drop_index("ix_webhook_deliveries_webhook_id_created_at", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index(op.f("ix_webhooks_project_id"), table_name="webhooks")
    op.drop_table("webhooks")
