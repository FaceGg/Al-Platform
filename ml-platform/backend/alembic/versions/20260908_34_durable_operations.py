"""Add durable generic-operation lease state."""

from alembic import op
import sqlalchemy as sa


revision = "20260908_35"
down_revision = "20260908_34"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "durable_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resource_key", sa.String(length=256), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("result_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("checksum", sa.String(length=71), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_key", "idempotency_key", name="uq_durable_operations_resource_idempotency"),
    )
    op.create_index("ix_durable_operations_lease", "durable_operations", ["state", "lease_expires_at"])


def downgrade():
    op.drop_index("ix_durable_operations_lease", table_name="durable_operations")
    op.drop_table("durable_operations")
