"""Add chat widgets, and mark the conversations started in one.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "widgets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("welcome", sa.Text(), nullable=True),
        sa.Column("accent", sa.String(length=7), nullable=False),
        sa.Column("allowed_origins", postgresql.ARRAY(sa.String(length=255)), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                name=op.f("fk_widgets_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_widgets")),
    )
    op.create_index(op.f("ix_widgets_project_id"), "widgets", ["project_id"])
    op.add_column("conversations", sa.Column("widget_id", sa.String(length=32), nullable=True))
    op.create_foreign_key(op.f("fk_conversations_widget_id_widgets"), "conversations", "widgets",
                          ["widget_id"], ["id"], ondelete="SET NULL")
    op.create_index(op.f("ix_conversations_widget_id"), "conversations", ["widget_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_conversations_widget_id"), table_name="conversations")
    op.drop_constraint(op.f("fk_conversations_widget_id_widgets"), "conversations",
                       type_="foreignkey")
    op.drop_column("conversations", "widget_id")
    op.drop_index(op.f("ix_widgets_project_id"), table_name="widgets")
    op.drop_table("widgets")
