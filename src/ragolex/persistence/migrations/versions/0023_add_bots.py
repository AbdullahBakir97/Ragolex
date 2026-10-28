"""Chat bots: a project's assistant in Telegram, Slack or WhatsApp.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("account", sa.String(length=255), nullable=False),
        sa.Column("credentials", sa.String(), nullable=False),
        sa.Column("webhook_secret", sa.String(length=255), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"),
                  nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('telegram', 'slack', 'whatsapp')",
                           name=op.f("ck_bots_kind")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                name=op.f("fk_bots_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bots")),
    )
    op.create_index(op.f("ix_bots_project_id"), "bots", ["project_id"])
    op.create_table(
        "bot_chats",
        sa.Column("bot_id", sa.String(length=32), nullable=False),
        sa.Column("chat_key", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"], name=op.f("fk_bot_chats_bot_id_bots"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"],
                                name=op.f("fk_bot_chats_conversation_id_conversations"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("bot_id", "chat_key", name=op.f("pk_bot_chats")),
    )
    op.create_index(op.f("ix_bot_chats_conversation_id"), "bot_chats", ["conversation_id"])
    op.create_table(
        "bot_deliveries",
        sa.Column("bot_id", sa.String(length=32), nullable=False),
        sa.Column("update_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["bot_id"], ["bots.id"],
                                name=op.f("fk_bot_deliveries_bot_id_bots"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("bot_id", "update_id", name=op.f("pk_bot_deliveries")),
    )


def downgrade() -> None:
    op.drop_table("bot_deliveries")
    op.drop_index(op.f("ix_bot_chats_conversation_id"), table_name="bot_chats")
    op.drop_table("bot_chats")
    op.drop_index(op.f("ix_bots_project_id"), table_name="bots")
    op.drop_table("bots")
