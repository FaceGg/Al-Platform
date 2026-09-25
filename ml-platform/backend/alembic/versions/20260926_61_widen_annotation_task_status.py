"""Widen annotation task status columns for long return states.

The return-freeze worker writes ``returned_pending_acceptance`` (27 chars)
into ``generic_annotation_tasks.status`` and ``paused_from_status``. Both
columns were created as VARCHAR(24), so PostgreSQL raised
StringDataRightTruncation and every annotation-return validation operation
failed with 409 RETURN_BATCH_NOT_READY. SQLite does not enforce VARCHAR
widths, which is why local and test environments never surfaced this.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260926_61"
down_revision = "20260921_60"
branch_labels = None
depends_on = None


def _current_length(inspector, table: str, column: str) -> int | None:
    for item in inspector.get_columns(table):
        if item["name"] != column:
            continue
        return getattr(item["type"], "length", None)
    return None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite does not enforce VARCHAR widths; nothing to widen.
        return
    inspector = sa.inspect(bind)
    for column in ("status", "paused_from_status"):
        length = _current_length(inspector, "generic_annotation_tasks", column)
        if length is not None and length < 32:
            op.execute(
                f'ALTER TABLE generic_annotation_tasks '
                f'ALTER COLUMN "{column}" TYPE VARCHAR(32)'
            )


def downgrade():
    # Existing 27-char values would be truncated; refuse to shrink.
    raise RuntimeError("Refusing destructive downgrade of annotation task status width")
