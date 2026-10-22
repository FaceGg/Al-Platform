"""LLM gateway model profiles (AutoML Agent plan, Task A1.2).

Revision ID: 20261022_75
Revises: 20261020_74
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_75"
down_revision = "20261020_74"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("api_url", sa.String(length=512), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("purpose_tags", sa.JSON(), nullable=False),
        sa.Column("deployment", sa.String(length=16), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "provider IN ('openai_compatible', 'custom')",
            name="ck_llm_profiles_provider",
        ),
        sa.CheckConstraint(
            "deployment IN ('cloud', 'private')",
            name="ck_llm_profiles_deployment",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_profiles_name", "llm_profiles", ["name"], unique=True)
    op.create_index(
        "ux_llm_profiles_single_default",
        "llm_profiles",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default = 1"),
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index("ux_llm_profiles_single_default", table_name="llm_profiles")
    op.drop_index("ix_llm_profiles_name", table_name="llm_profiles")
    op.drop_table("llm_profiles")
