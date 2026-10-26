"""Create the tables for conversations and their messages.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                name=op.f("fk_conversations_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
    )
    op.create_index("ix_conversations_project_id_updated_at", "conversations",
                    ["project_id", "updated_at"], unique=False)
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()),
                  server_default="[]", nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("search_question", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"],
                                name=op.f("fk_conversation_messages_conversation_id_conversations"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
    )
    op.create_index(op.f("ix_conversation_messages_conversation_id"), "conversation_messages",
                    ["conversation_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_conversation_messages_conversation_id"),
                  table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_project_id_updated_at", table_name="conversations")
    op.drop_table("conversations")
