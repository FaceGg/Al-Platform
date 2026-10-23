"""Wizard prompt templates (AutoML Agent plan, Task A5.1).

Revision ID: 20261022_79
Revises: 20261022_78
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_79"
down_revision = "20261022_78"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id", "project_id", "name", name="ux_prompt_templates_scope_name"
        ),
    )
    op.create_index(
        "ix_prompt_templates_owner", "prompt_templates", ["owner_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_templates_owner", table_name="prompt_templates")
    op.drop_table("prompt_templates")
