"""Knowledge base bindings (AutoML Agent plan, Task A6.1).

Revision ID: 20261022_80
Revises: 20261022_79
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_80"
down_revision = "20261022_79"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kb_bindings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kb_id", sa.UUID(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("scope_projects", sa.JSON(), nullable=False),
        sa.Column("scope_agent_tasks", sa.String(length=16), nullable=False),
        sa.Column("scope_agent_task_ids", sa.JSON(), nullable=False),
        sa.Column("scope_chat", sa.Boolean(), nullable=False),
        sa.Column("scope_agent_s1", sa.Boolean(), nullable=False),
        sa.Column("retrieval_top_k", sa.Integer(), nullable=False),
        sa.Column("retrieval_max_total_chars", sa.Integer(), nullable=False),
        sa.Column("retrieval_min_score", sa.Float(), nullable=False),
        sa.Column("retrieval_trigger", sa.String(length=16), nullable=False),
        sa.Column("sync_receive_experience", sa.Boolean(), nullable=False),
        sa.Column("sync_experience_min_confidence", sa.Float(), nullable=False),
        sa.Column("sync_human_review", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "retrieval_trigger IN ('auto','explicit')",
            name="ck_kb_bindings_trigger",
        ),
        sa.CheckConstraint(
            "sync_human_review IN ('auto','pending')",
            name="ck_kb_bindings_human_review",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kb_id", name="ux_kb_bindings_kb"),
    )


def downgrade() -> None:
    op.drop_table("kb_bindings")
