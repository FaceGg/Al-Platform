"""Create saved_annotation_strategies for reusable automatic-annotation strategies."""

from alembic import op
import sqlalchemy as sa

revision = "20260921_59"
down_revision = "20260917_58"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saved_annotation_strategies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_saved_strategy_project_name"),
    )


def downgrade():
    op.drop_table("saved_annotation_strategies")
