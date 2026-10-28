"""Single sign-on: a workspace's OpenID Connect provider, and sign-ins in progress.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sso_providers",
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("client_secret", sa.String(), nullable=False),
        sa.Column("default_role", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.CheckConstraint("default_role IN ('admin', 'editor', 'viewer')",
                           name=op.f("ck_sso_providers_default_role")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_sso_providers_tenant_id_tenants"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_sso_providers")),
    )
    op.create_table(
        "sso_requests",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("nonce", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("next_url", sa.Text(), nullable=False),
        sa.Column("browser_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_sso_requests_tenant_id_tenants"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_hash", name=op.f("pk_sso_requests")),
    )
    op.create_index(op.f("ix_sso_requests_tenant_id"), "sso_requests", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_sso_requests_tenant_id"), table_name="sso_requests")
    op.drop_table("sso_requests")
    op.drop_table("sso_providers")
