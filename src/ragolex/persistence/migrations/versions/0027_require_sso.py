"""Workspaces that require single sign-on, and which provider signed a session in.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sso_providers", sa.Column("required", sa.Boolean(),
                                             server_default=sa.text("false"), nullable=False))
    op.add_column("user_sessions", sa.Column("sso_tenant_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(op.f("fk_user_sessions_sso_tenant_id_tenants"), "user_sessions",
                          "tenants", ["sso_tenant_id"], ["id"], ondelete="SET NULL")
    op.create_index(op.f("ix_user_sessions_sso_tenant_id"), "user_sessions", ["sso_tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_sessions_sso_tenant_id"), table_name="user_sessions")
    op.drop_constraint(op.f("fk_user_sessions_sso_tenant_id_tenants"), "user_sessions",
                       type_="foreignkey")
    op.drop_column("user_sessions", "sso_tenant_id")
    op.drop_column("sso_providers", "required")
