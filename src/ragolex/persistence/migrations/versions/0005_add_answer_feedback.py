"""Add thumbs up/down feedback, with a comment, to answers in conversations.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversation_messages", sa.Column("feedback_rating", sa.String(length=8), nullable=True))
    op.add_column("conversation_messages", sa.Column("feedback_comment", sa.Text(), nullable=True))
    op.add_column("conversation_messages",
                  sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(op.f("ck_conversation_messages_feedback_rating"),
                               "conversation_messages", "feedback_rating IN ('up', 'down')")
    op.create_index("ix_conversation_messages_feedback_at", "conversation_messages",
                    ["feedback_at"], unique=False,
                    postgresql_where=sa.text("feedback_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_conversation_messages_feedback_at", table_name="conversation_messages",
                  postgresql_where=sa.text("feedback_at IS NOT NULL"))
    op.drop_constraint(op.f("ck_conversation_messages_feedback_rating"), "conversation_messages",
                       type_="check")
    op.drop_column("conversation_messages", "feedback_at")
    op.drop_column("conversation_messages", "feedback_comment")
    op.drop_column("conversation_messages", "feedback_rating")
