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
    with op.batch_alter_table("agent_tasks") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.UUID(), nullable=True))
        batch_op.add_column(sa.Column("created_by_id", sa.UUID(), nullable=True))
        batch_op.create_foreign_key(
            "fk_agent_tasks_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_agent_tasks_created_by_id_users",
            "users",
            ["created_by_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_agent_tasks_project_id", ["project_id"])
        batch_op.create_index("ix_agent_tasks_created_by_id", ["created_by_id"])
    op.execute(sa.text("""
        UPDATE agent_tasks
        SET project_id = workflows.project_id,
            created_by_id = workflows.created_by
        FROM workflows
        WHERE agent_tasks.workflow_id = workflows.id
          AND agent_tasks.project_id IS NULL
    """))


def downgrade() -> None:
    with op.batch_alter_table("agent_tasks") as batch_op:
        batch_op.drop_index("ix_agent_tasks_created_by_id")
        batch_op.drop_index("ix_agent_tasks_project_id")
        batch_op.drop_constraint("fk_agent_tasks_created_by_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_agent_tasks_project_id_projects", type_="foreignkey")
        batch_op.drop_column("created_by_id")
        batch_op.drop_column("project_id")
