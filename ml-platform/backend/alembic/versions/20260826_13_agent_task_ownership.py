"""Add project and creator ownership to agent tasks.

Revision ID: 20260826_13
Revises: 20260819_12
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa


revision = "20260826_13"
down_revision = "20260819_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_tasks", sa.Column("project_id", sa.UUID(), nullable=True))
    op.add_column("agent_tasks", sa.Column("created_by_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_agent_tasks_project_id_projects",
        "agent_tasks",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_agent_tasks_created_by_id_users",
        "agent_tasks",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agent_tasks_project_id", "agent_tasks", ["project_id"])
    op.create_index("ix_agent_tasks_created_by_id", "agent_tasks", ["created_by_id"])
    op.execute(sa.text("""
        UPDATE agent_tasks
        SET project_id = workflows.project_id,
            created_by_id = workflows.created_by
        FROM workflows
        WHERE agent_tasks.workflow_id = workflows.id
          AND agent_tasks.project_id IS NULL
    """))


def downgrade() -> None:
    op.drop_index("ix_agent_tasks_created_by_id", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_project_id", table_name="agent_tasks")
    op.drop_constraint("fk_agent_tasks_created_by_id_users", "agent_tasks", type_="foreignkey")
    op.drop_constraint("fk_agent_tasks_project_id_projects", "agent_tasks", type_="foreignkey")
    op.drop_column("agent_tasks", "created_by_id")
    op.drop_column("agent_tasks", "project_id")
