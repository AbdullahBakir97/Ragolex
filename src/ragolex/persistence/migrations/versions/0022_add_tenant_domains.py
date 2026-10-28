"""Custom domains: a workspace serves on a domain it proves it owns.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_domains",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("domain", sa.String(length=253), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_tenant_domains_tenant_id_tenants"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_domains")),
        sa.UniqueConstraint("tenant_id", "domain", name=op.f("uq_tenant_domains_tenant_id_domain")),
    )
    op.create_index(op.f("ix_tenant_domains_tenant_id"), "tenant_domains", ["tenant_id"])
    op.create_index("uq_tenant_domains_verified_domain", "tenant_domains", ["domain"],
                    unique=True, postgresql_where=sa.text("verified_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_tenant_domains_verified_domain", table_name="tenant_domains",
                  postgresql_where=sa.text("verified_at IS NOT NULL"))
    op.drop_index(op.f("ix_tenant_domains_tenant_id"), table_name="tenant_domains")
    op.drop_table("tenant_domains")
