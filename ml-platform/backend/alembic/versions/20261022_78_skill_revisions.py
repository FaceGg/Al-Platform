"""Bounded RSI: skill revision proposals (AutoML Agent plan, Task A4.1).

Revision ID: 20261022_78
Revises: 20261022_77
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_78"
down_revision = "20261022_77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("skill_name", sa.String(length=64), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("new_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("regression_passed", sa.Boolean(), nullable=True),
        sa.Column("proposal_json", sa.JSON(), nullable=False),
        sa.Column("regression_json", sa.JSON(), nullable=False),
        sa.Column("basis_entries", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('proposed','regression_running','regression_failed',"
            "'pending_approval','auto_activated','activated','rejected','rolled_back')",
            name="ck_skill_revisions_status",
        ),
        sa.CheckConstraint(
            "risk_level IN ('low','medium','high')",
            name="ck_skill_revisions_risk",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_skill_revisions_skill_status",
        "skill_revisions",
        ["skill_name", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_skill_revisions_skill_status", table_name="skill_revisions"
    )
    op.drop_table("skill_revisions")
