"""Bind export idempotency to a non-null scope."""

from alembic import op
import sqlalchemy as sa

revision = "20260909_38"
down_revision = "20260909_37"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "model_exports" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("model_exports")}
    if "idempotency_scope" not in columns:
        op.add_column("model_exports", sa.Column("idempotency_scope", sa.String(256), nullable=False, server_default="model"))
    if "request_hash" not in columns:
        op.add_column("model_exports", sa.Column("request_hash", sa.String(64), nullable=False, server_default=""))
    constraints = {item.get("name") for item in inspector.get_unique_constraints("model_exports")}
    if "uq_model_exports_idempotency" in constraints:
        with op.batch_alter_table("model_exports", recreate="always") as batch:
            batch.drop_constraint("uq_model_exports_idempotency", type_="unique")
            batch.create_unique_constraint("uq_model_exports_idempotency", ["idempotency_scope", "idempotency_key"])
    else:
        with op.batch_alter_table("model_exports") as batch:
            batch.create_unique_constraint("uq_model_exports_idempotency", ["idempotency_scope", "idempotency_key"])


def downgrade():
    pass
