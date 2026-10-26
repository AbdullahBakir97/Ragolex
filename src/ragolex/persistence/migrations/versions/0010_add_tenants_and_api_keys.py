"""Add tenants with API keys, and give every project a tenant.

Existing projects go to the tenant "default", and keep their folder under
FILES_DIR (storage_name is their name).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("name", name=op.f("uq_tenants_name")),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"],
                                name=op.f("fk_api_keys_tenant_id_tenants"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
    )
    op.create_index(op.f("ix_api_keys_tenant_id"), "api_keys", ["tenant_id"])

    op.execute("INSERT INTO tenants (name) VALUES ('default')")
    op.add_column("projects", sa.Column("tenant_id", sa.BigInteger(), nullable=True))
    op.add_column("projects", sa.Column("storage_name", sa.String(length=100), nullable=True))
    op.execute("UPDATE projects SET tenant_id = (SELECT id FROM tenants WHERE name = 'default'), "
               "storage_name = name")
    op.alter_column("projects", "tenant_id", nullable=False)
    op.alter_column("projects", "storage_name", nullable=False)
    op.create_foreign_key(op.f("fk_projects_tenant_id_tenants"), "projects", "tenants",
                          ["tenant_id"], ["id"], ondelete="CASCADE")
    op.drop_constraint("uq_projects_name", "projects", type_="unique")
    op.create_unique_constraint(op.f("uq_projects_tenant_id_name"), "projects",
                                ["tenant_id", "name"])
    op.create_unique_constraint(op.f("uq_projects_storage_name"), "projects", ["storage_name"])


def downgrade() -> None:
    # Projects of other tenants could clash by name, so only the default tenant's survive.
    op.execute("DELETE FROM projects WHERE tenant_id <> "
               "(SELECT id FROM tenants WHERE name = 'default')")
    op.drop_constraint(op.f("uq_projects_storage_name"), "projects", type_="unique")
    op.drop_constraint(op.f("uq_projects_tenant_id_name"), "projects", type_="unique")
    op.create_unique_constraint("uq_projects_name", "projects", ["name"])
    op.drop_constraint(op.f("fk_projects_tenant_id_tenants"), "projects", type_="foreignkey")
    op.drop_column("projects", "storage_name")
    op.drop_column("projects", "tenant_id")
    op.drop_index(op.f("ix_api_keys_tenant_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("tenants")
