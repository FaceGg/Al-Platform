"""Persist AutoML training contract snapshot."""
from alembic import op
import sqlalchemy as sa

revision = "20260904_18"
down_revision = "20260905_17"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("training_jobs")}
    if "automl_contract" not in cols:
        op.add_column("training_jobs", sa.Column("automl_contract", sa.JSON(), nullable=True))

def downgrade() -> None:
    raise RuntimeError("Refusing destructive downgrade of AutoML contract")
