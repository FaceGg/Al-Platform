"""Index source-version pages used by immutable annotation return acceptance."""

from alembic import op
import sqlalchemy as sa


revision = "20260916_54"
down_revision = "20260916_53"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dataset_samples" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("dataset_samples")}
    if "ix_dataset_samples_version_row_page" not in indexes:
        op.create_index(
            "ix_dataset_samples_version_row_page",
            "dataset_samples",
            ["dataset_version_id", "row_index", "id"],
        )


def downgrade():
    raise RuntimeError("Refusing destructive downgrade of annotation return paging index")
