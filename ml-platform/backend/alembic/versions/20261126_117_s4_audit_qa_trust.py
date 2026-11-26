# -*- coding: utf-8 -*-
"""S4 audit QA reports + model trust score history (B2-01/B2-04)."""
import sqlalchemy as sa
from alembic import op

revision = "20261126_117"
down_revision = "20261126_116"
branch_labels = None
depends_on = None


def _table_names() -> set:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    op.create_table(
        "audit_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("template_key", sa.String(length=32), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("citation_errors", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "model_trust_scores",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("grade", sa.String(length=1), nullable=False),
        sa.Column("factors", sa.JSON(), nullable=False),
        sa.Column(
            "computed_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "computed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("grade IN ('A','B','C','D')", name="ck_model_trust_grade"),
    )
    op.create_index(
        "ix_model_trust_version_time", "model_trust_scores",
        ["model_version_id", "computed_at"],
    )
    # ModelCard 扩展两列（C6：11 章节化 + 数据指纹触发重建）
    with op.batch_alter_table("model_cards") as batch:
        batch.add_column(sa.Column("sections_v2", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("data_fingerprint", sa.String(length=64), nullable=True))
    assert {"audit_reports", "model_trust_scores"} <= _table_names()


def downgrade() -> None:
    with op.batch_alter_table("model_cards") as batch:
        batch.drop_column("data_fingerprint")
        batch.drop_column("sections_v2")
    op.drop_index("ix_model_trust_version_time", table_name="model_trust_scores")
    op.drop_table("model_trust_scores")
    op.drop_table("audit_reports")
