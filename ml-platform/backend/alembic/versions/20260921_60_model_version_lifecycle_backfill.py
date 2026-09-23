"""Reconcile legacy approved model versions with the lifecycle enabled state."""

from alembic import op


revision = "20260921_60"
down_revision = "20260921_59"
branch_labels = None
depends_on = None


def upgrade():
    # Legacy approve()/archive() calls predate lifecycle_state (default
    # 'pending_review'), leaving approved versions failing the enabled gate
    # used by automatic annotation. Heal only inconsistent rows; versions
    # explicitly disabled or revoked keep their state.
    op.execute(
        "UPDATE model_versions SET lifecycle_state = 'enabled' "
        "WHERE approval_status = 'approved' "
        "AND (lifecycle_state IS NULL OR lifecycle_state = 'pending_review')"
    )
    op.execute(
        "UPDATE model_versions SET lifecycle_state = 'archived' "
        "WHERE approval_status = 'archived' "
        "AND (lifecycle_state IS NULL OR lifecycle_state = 'pending_review')"
    )


def downgrade():
    # Rows healed here cannot be distinguished from versions enabled through
    # the regular transition flow, so downgrade is a deliberate no-op.
    pass
