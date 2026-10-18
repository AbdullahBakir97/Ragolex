"""Add decks of flashcards, scheduled by spaced repetition.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decks",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                name=op.f("fk_decks_project_id_projects"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decks")),
    )
    op.create_index(op.f("ix_decks_project_id"), "decks", ["project_id"])
    op.create_table(
        "cards",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("deck_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("file_key", sa.String(length=255), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("interval_days", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("ease", sa.Float(), server_default=sa.text("2.5"), nullable=False),
        sa.Column("repetitions", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lapses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.ForeignKeyConstraint(["deck_id"], ["decks.id"], name=op.f("fk_cards_deck_id_decks"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cards")),
    )
    op.create_index("ix_cards_deck_id_due_at", "cards", ["deck_id", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_cards_deck_id_due_at", table_name="cards")
    op.drop_table("cards")
    op.drop_index(op.f("ix_decks_project_id"), table_name="decks")
    op.drop_table("decks")
