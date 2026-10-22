"""Pipeline Recipe + ExperienceEntry tables (AutoML Agent plan, Task A3.1).

Revision ID: 20261022_77
Revises: 20261022_76
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_77"
down_revision = "20261022_76"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_recipes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=True),
        sa.Column("target_column", sa.String(length=256), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="ux_pipeline_recipes_scope_name"),
    )
    op.create_table(
        "pipeline_recipe_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recipe_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("change_note", sa.String(length=500), nullable=True),
        sa.Column("llm_profile_id", sa.UUID(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["recipe_id"], ["pipeline_recipes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["llm_profile_id"], ["llm_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('current','superseded')", name="ck_recipe_versions_status"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "version", name="ux_recipe_versions_number"),
    )
    op.create_index(
        "ix_recipe_versions_recipe", "pipeline_recipe_versions", ["recipe_id", "version"]
    )
    op.create_table(
        "experience_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("domain", sa.String(length=64), nullable=False),
        sa.Column("situation", sa.Text(), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("generality", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scope_project_ids", sa.JSON(), nullable=False),
        sa.Column("source_tasks", sa.JSON(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("human_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('shadow','active','retired','superseded')",
            name="ck_experience_entries_status",
        ),
        sa.CheckConstraint(
            "origin IN ('distilled','human')", name="ck_experience_entries_origin"
        ),
        sa.CheckConstraint(
            "generality IN ('domain','cross-domain')",
            name="ck_experience_entries_generality",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_experience_entries_confidence",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experience_entries_retrieval",
        "experience_entries",
        ["domain", "status", "confidence"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_experience_entries_retrieval", table_name="experience_entries"
    )
    op.drop_table("experience_entries")
    op.drop_index("ix_recipe_versions_recipe", table_name="pipeline_recipe_versions")
    op.drop_table("pipeline_recipe_versions")
    op.drop_table("pipeline_recipes")
