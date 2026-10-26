"""Keep a SHA-256 of each file's content, so the same content is stored once per project.

Files uploaded before have none, and are not compared.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("files", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    op.create_index("uq_files_project_id_content_sha256", "files", ["project_id", "content_sha256"],
                    unique=True, postgresql_where=sa.text("content_sha256 IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_files_project_id_content_sha256", table_name="files",
                  postgresql_where=sa.text("content_sha256 IS NOT NULL"))
    op.drop_column("files", "content_sha256")
