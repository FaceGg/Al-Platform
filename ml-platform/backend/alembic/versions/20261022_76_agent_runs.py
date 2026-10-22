"""Agent run state machine and memory (AutoML Agent plan, Task A2.2).

Revision ID: 20261022_76
Revises: 20261022_75
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_76"
down_revision = "20261022_75"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("dataset_artifact_id", sa.UUID(), nullable=True),
        sa.Column("target_column", sa.String(length=256), nullable=True),
        sa.Column("llm_profile_id", sa.UUID(), nullable=True),
        sa.Column("llm_model_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_stage", sa.String(length=16), nullable=False),
        sa.Column("round_count", sa.Integer(), nullable=False),
        sa.Column("token_used", sa.Integer(), nullable=False),
        sa.Column("token_budget", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("memory_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["llm_profile_id"], ["llm_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('pending','running','waiting_guidance','waiting_escalate',"
            "'accepted','failed','cancelled')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint(
            "current_stage IN ('s1','s2','s3','s4','done')",
            name="ck_agent_runs_stage",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_runs_project_created", "agent_runs", ["project_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_project_created", table_name="agent_runs")
    op.drop_table("agent_runs")
