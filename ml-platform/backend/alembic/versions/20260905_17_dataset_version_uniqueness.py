"""Add the project/version uniqueness guard for immutable dataset versions."""

from alembic import op
import sqlalchemy as sa


revision = "20260905_17"
down_revision = "20260904_16"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_dataset_versions_project_version"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dataset_versions" not in inspector.get_table_names():
        return
    indexes = {item["name"] for item in inspector.get_indexes("dataset_versions")}
    if INDEX_NAME not in indexes:
        op.create_index(
            INDEX_NAME,
            "dataset_versions",
            ["project_id", "version"],
            unique=True,
        )


def downgrade() -> None:
    raise RuntimeError(
        "Refusing destructive downgrade of dataset version uniqueness guard"
    )
