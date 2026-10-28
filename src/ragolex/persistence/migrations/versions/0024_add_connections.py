"""Connections: a tenant's sign-in to Notion or Google Drive, and the sources that use one.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("account", sa.String(length=255), nullable=False),
        sa.Column("credentials", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('notion', 'google_drive')",
                           name=op.f("ck_connections_kind")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_connections_tenant_id_tenants"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"],
                                name=op.f("fk_connections_created_by_user_id_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connections")),
    )
    op.create_index(op.f("ix_connections_tenant_id"), "connections", ["tenant_id"])
    op.create_index(op.f("ix_connections_created_by_user_id"), "connections",
                    ["created_by_user_id"])
    op.create_table(
        "connection_requests",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("return_to", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("browser_hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_connection_requests_tenant_id_tenants"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                name=op.f("fk_connection_requests_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_hash", name=op.f("pk_connection_requests")),
    )
    op.create_index(op.f("ix_connection_requests_tenant_id"), "connection_requests",
                    ["tenant_id"])
    op.create_index(op.f("ix_connection_requests_user_id"), "connection_requests", ["user_id"])
    op.add_column("sources", sa.Column("connection_id", sa.String(length=32), nullable=True))
    op.create_foreign_key(op.f("fk_sources_connection_id_connections"), "sources",
                          "connections", ["connection_id"], ["id"])
    op.create_index(op.f("ix_sources_connection_id"), "sources", ["connection_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_sources_connection_id"), table_name="sources")
    op.drop_constraint(op.f("fk_sources_connection_id_connections"), "sources",
                       type_="foreignkey")
    # Sources that read through a connection cannot be read without one.
    op.execute("DELETE FROM sources WHERE connection_id IS NOT NULL")
    op.drop_column("sources", "connection_id")
    op.drop_index(op.f("ix_connection_requests_user_id"), table_name="connection_requests")
    op.drop_index(op.f("ix_connection_requests_tenant_id"), table_name="connection_requests")
    op.drop_table("connection_requests")
    op.drop_index(op.f("ix_connections_created_by_user_id"), table_name="connections")
    op.drop_index(op.f("ix_connections_tenant_id"), table_name="connections")
    op.drop_table("connections")
