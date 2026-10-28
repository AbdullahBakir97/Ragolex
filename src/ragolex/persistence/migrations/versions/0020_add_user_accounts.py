"""User accounts: people sign in with an email and password, with a role per workspace.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_logins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "memberships",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.CheckConstraint("role IN ('owner', 'admin', 'editor', 'viewer')",
                           name=op.f("ck_memberships_role")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                name=op.f("fk_memberships_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_memberships_tenant_id_tenants"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "tenant_id", name=op.f("pk_memberships")),
    )
    op.create_index(op.f("ix_memberships_tenant_id"), "memberships", ["tenant_id"])
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"],
                                name=op.f("fk_user_sessions_user_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_user_sessions_tenant_id_tenants"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash")),
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"])
    op.create_index(op.f("ix_user_sessions_tenant_id"), "user_sessions", ["tenant_id"])
    op.add_column("audit_events", sa.Column("actor_user_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(op.f("fk_audit_events_actor_user_id_users"), "audit_events", "users",
                          ["actor_user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint(op.f("fk_audit_events_actor_user_id_users"), "audit_events",
                       type_="foreignkey")
    op.drop_column("audit_events", "actor_user_id")
    op.drop_index(op.f("ix_user_sessions_tenant_id"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_user_id"), table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index(op.f("ix_memberships_tenant_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("users")
