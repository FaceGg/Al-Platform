"""Add stable artifact storage URI.

Revision ID: 20260715_02
Revises: 20260715_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_02"
down_revision = "20260715_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column("storage_uri", sa.String(length=1024), nullable=True),
    )
    op.create_index(
        "ix_artifacts_storage_uri",
        "artifacts",
        ["storage_uri"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_artifacts_storage_uri", table_name="artifacts")
    op.drop_column("artifacts", "storage_uri")
