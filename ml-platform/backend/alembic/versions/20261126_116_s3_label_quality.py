# -*- coding: utf-8 -*-
"""S3 label quality: active learning / consistency rounds / arbitrations / pseudo labels (B2-05/06/G4).

补齐路线第二批 S3（技术方案 §8.1，迁移 _116）：
- active_learning_selections：九策略选样运行（策略/预算/命中统计）；
- consistency_rounds + annotation_blind_labels：并行一致性通道（逐标注员独立
  盲标——门户共享单通道零改动，§12.13）；
- label_arbitrations：分歧仲裁队列（终审写回规范通道）；
- pseudo_label_batches：伪标签批与凭证（红线：永不进开发验证与独立盲测）。
全部新建表，不动数据。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261126_116"
down_revision = "20261126_115"
branch_labels = None
depends_on = None


def _table_names() -> set:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def _constraint_names(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    names: set = set()
    for kind in ("check_constraints", "foreign_keys", "unique_constraints"):
        for constraint in getattr(inspector, f"get_{kind}")(table):
            names.add(constraint.get("name"))
    return names


def upgrade() -> None:
    op.create_table(
        "active_learning_selections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("model_version_id", sa.Uuid(), nullable=True),
        sa.Column("strategy", sa.JSON(), nullable=False),
        sa.Column("budget_initial", sa.Integer(), nullable=False),
        sa.Column("budget_per_round", sa.Integer(), nullable=False),
        sa.Column("selected_sample_ids", sa.JSON(), nullable=False),
        sa.Column("strategy_stats", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
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
        "consistency_rounds",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("label_schema_id", sa.Uuid(), nullable=True),
        sa.Column("annotator_subject_ids", sa.JSON(), nullable=False),
        sa.Column("sample_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("kappa_pairwise", sa.JSON(), nullable=True),
        sa.Column("kappa_average", sa.Float(), nullable=True),
        sa.Column("kappa_threshold", sa.Float(), nullable=False),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('open', 'completed', 'arbitrated')",
            name="ck_consistency_rounds_status",
        ),
    )

    op.create_table(
        "annotation_blind_labels",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "round_id", sa.Uuid(),
            sa.ForeignKey("consistency_rounds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("sample_id", sa.String(length=128), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "round_id", "subject_id", "sample_id",
            name="uq_blind_labels_round_subject_sample",
        ),
    )

    op.create_table(
        "label_arbitrations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "round_id", sa.Uuid(),
            sa.ForeignKey("consistency_rounds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sample_id", sa.String(length=128), nullable=False),
        sa.Column("conflict", sa.JSON(), nullable=False),
        sa.Column("decision_values", sa.JSON(), nullable=True),
        sa.Column("decision_note", sa.String(length=256), nullable=True),
        sa.Column(
            "arbiter_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'decided')",
            name="ck_label_arbitrations_status",
        ),
    )
    op.create_index(
        "ix_label_arbitrations_round_status", "label_arbitrations",
        ["round_id", "status"],
    )

    op.create_table(
        "pseudo_label_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("model_version_id", sa.Uuid(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("per_class_quota", sa.JSON(), nullable=False),
        sa.Column("selected", sa.JSON(), nullable=False),
        sa.Column("dev_comparison", sa.JSON(), nullable=True),
        sa.Column("winner", sa.Integer(), nullable=False),
        sa.Column("credential_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )

    assert {
        "active_learning_selections", "consistency_rounds", "annotation_blind_labels",
        "label_arbitrations", "pseudo_label_batches",
    } <= _table_names()
    assert "ck_consistency_rounds_status" in _constraint_names("consistency_rounds")
    assert "ck_label_arbitrations_status" in _constraint_names("label_arbitrations")
    assert "uq_blind_labels_round_subject_sample" in _constraint_names(
        "annotation_blind_labels"
    )


def downgrade() -> None:
    op.drop_table("pseudo_label_batches")
    op.drop_index("ix_label_arbitrations_round_status", table_name="label_arbitrations")
    op.drop_table("label_arbitrations")
    op.drop_table("annotation_blind_labels")
    op.drop_table("consistency_rounds")
    op.drop_table("active_learning_selections")
