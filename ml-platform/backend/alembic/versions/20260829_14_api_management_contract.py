"""Add source and publication metadata to platform APIs.

Revision ID: 20260829_14
Revises: 20260826_13
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20260829_14"
down_revision = "20260826_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("platform_apis") as batch_op:
        batch_op.add_column(sa.Column("source_kind", sa.String(length=32), nullable=False, server_default="custom"))
        batch_op.add_column(sa.Column("source_id", sa.UUID(), nullable=True))
        batch_op.add_column(sa.Column("published_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_platform_api_source_version",
            ["source_kind", "source_id", "version"],
        )


def downgrade() -> None:
    with op.batch_alter_table("platform_apis") as batch_op:
        batch_op.drop_constraint("uq_platform_api_source_version", type_="unique")
        batch_op.drop_column("last_error")
        batch_op.drop_column("published_at")
        batch_op.drop_column("source_id")
        batch_op.drop_column("source_kind")
