"""Bot deliveries name their chat, so a chat that sends too many messages is slowed down.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bot_deliveries", sa.Column("chat_key", sa.String(length=255), nullable=True))
    op.create_index("ix_bot_deliveries_chat", "bot_deliveries",
                    ["bot_id", "chat_key", "created_at"])
    op.create_index("ix_bot_deliveries_created_at", "bot_deliveries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_bot_deliveries_created_at", table_name="bot_deliveries")
    op.drop_index("ix_bot_deliveries_chat", table_name="bot_deliveries")
    op.drop_column("bot_deliveries", "chat_key")
