"""Add missing server defaults for audit timestamps (migrations 75-80 drift).

The ORM models for llm_profiles, agent_runs, experience_entries, kb_bindings,
pipeline_recipes, pipeline_recipe_versions, prompt_templates and
skill_revisions all declare ``server_default=func.now()`` on created_at /
updated_at, but the create-table migrations omitted it. Any INSERT that relies
on the server default (e.g. the LLM profile env bootstrap) fails with a
NotNullViolation on PostgreSQL deployments. SQLite tests never saw this
because ``Base.metadata.create_all`` builds columns from the models.

Revision ID: 20261023_81
Revises: 20261022_80
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_81"
down_revision = "20261022_80"
branch_labels = None
depends_on = None

# (table, column) pairs whose ORM model declares server_default=func.now().
_AUDIT_TIMESTAMP_COLUMNS = [
    ("llm_profiles", "created_at"),
    ("llm_profiles", "updated_at"),
    ("agent_runs", "created_at"),
    ("agent_runs", "updated_at"),
    ("experience_entries", "created_at"),
    ("experience_entries", "updated_at"),
    ("kb_bindings", "created_at"),
    ("kb_bindings", "updated_at"),
    ("pipeline_recipes", "created_at"),
    ("pipeline_recipes", "updated_at"),
    ("pipeline_recipe_versions", "created_at"),
    ("prompt_templates", "created_at"),
    ("prompt_templates", "updated_at"),
    ("skill_revisions", "created_at"),
    ("skill_revisions", "updated_at"),
]


def upgrade() -> None:
    # batch_alter_table: native ALTER on PostgreSQL, table-rebuild on SQLite.
    for table, column in _AUDIT_TIMESTAMP_COLUMNS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.DateTime(),
                existing_nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )


def downgrade() -> None:
    for table, column in _AUDIT_TIMESTAMP_COLUMNS:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                column,
                existing_type=sa.DateTime(),
                existing_nullable=False,
                server_default=None,
            )
