"""Add last_heartbeat to compute_nodes for agent heartbeat reporting."""

from alembic import op
import sqlalchemy as sa

revision = "20261006_65"
down_revision = "20261001_64"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("compute_nodes", sa.Column("last_heartbeat", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("compute_nodes", "last_heartbeat")
