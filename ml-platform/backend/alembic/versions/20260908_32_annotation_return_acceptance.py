"""Add review metadata for generic annotation return batches."""

from alembic import op
import sqlalchemy as sa

revision = "20260908_33"
down_revision = "20260908_32"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("annotation_return_batches")}
    with op.batch_alter_table("annotation_return_batches") as batch:
        if "rejection_reason" not in columns:
            batch.add_column(sa.Column("rejection_reason", sa.Text(), nullable=True))
        if "accepted_dataset_version_id" not in columns:
            batch.add_column(sa.Column("accepted_dataset_version_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key(
                "fk_annotation_return_batches_accepted_dataset_version",
                "dataset_versions",
                ["accepted_dataset_version_id"],
                ["id"],
            )
        if "reviewed_by" not in columns:
            batch.add_column(sa.Column("reviewed_by", sa.Uuid(), nullable=True))
            batch.create_foreign_key(
                "fk_annotation_return_batches_reviewed_by",
                "users",
                ["reviewed_by"],
                ["id"],
            )
        if "reviewed_at" not in columns:
            batch.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("annotation_return_batches") as batch:
        batch.drop_constraint("fk_annotation_return_batches_reviewed_by", type_="foreignkey")
        batch.drop_constraint("fk_annotation_return_batches_accepted_dataset_version", type_="foreignkey")
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by")
        batch.drop_column("accepted_dataset_version_id")
        batch.drop_column("rejection_reason")
