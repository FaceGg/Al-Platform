"""Enforce one immutable revision number per task sample."""

from alembic import op
import sqlalchemy as sa

revision = "20260907_24"
down_revision = "20260907_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    names = {item.get("name") for item in sa.inspect(op.get_bind()).get_unique_constraints("annotation_revisions")}
    if "uq_annotation_revision_number" not in names:
        with op.batch_alter_table("annotation_revisions") as batch:
            batch.create_unique_constraint("uq_annotation_revision_number", ["task_id", "sample_id", "revision_no"])


def downgrade() -> None:
    bind = op.get_bind()
    if "annotation_revisions" not in sa.inspect(bind).get_table_names():
        return
    with op.batch_alter_table("annotation_revisions") as batch:
        batch.drop_constraint("uq_annotation_revision_number", type_="unique")
