"""SAML 2.0 identity providers, and what one vouched for on a sign-in in progress.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sso_providers", sa.Column("protocol", sa.String(length=8),
                                             server_default="oidc", nullable=False))
    op.add_column("sso_providers", sa.Column("sso_url", sa.Text(), nullable=True))
    op.add_column("sso_providers", sa.Column("certificate", sa.Text(), nullable=True))
    op.create_check_constraint(op.f("ck_sso_providers_protocol"), "sso_providers",
                               "protocol IN ('oidc', 'saml')")
    op.add_column("sso_requests", sa.Column("vouched_email", sa.String(length=254),
                                            nullable=True))
    op.add_column("sso_requests", sa.Column("vouched_name", sa.String(length=200),
                                            nullable=True))


def downgrade() -> None:
    op.drop_column("sso_requests", "vouched_name")
    op.drop_column("sso_requests", "vouched_email")
    op.drop_constraint(op.f("ck_sso_providers_protocol"), "sso_providers", type_="check")
    op.drop_column("sso_providers", "certificate")
    op.drop_column("sso_providers", "sso_url")
    op.drop_column("sso_providers", "protocol")
