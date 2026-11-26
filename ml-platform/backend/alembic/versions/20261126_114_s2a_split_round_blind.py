# -*- coding: utf-8 -*-
"""S2a split management + modeling rounds + blind-test ledger (B2-G1).

补齐路线第二批 S2a（技术方案 §6.1，迁移 _114）：
- dataset_splits：划分管理（策略/参数/指纹）；E04 入库即定——创建后无修改端点；
- dataset_split_members：划分归属（development/blind 两层），独立于不可变的
  数据集版本表组（C3/E04 实现约束）；
- modeling_rounds：建模轮次（创建即锁定）+ 盲测评估计数上限（E03 默认 2）；
- blind_test_usages：盲测历史台账（防旧盲测复用的比对源）。

全部为新建表，不动数据。SQLite batch；PG 原生。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261126_114"
down_revision = "20261126_113"
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


def _index_names(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    op.create_table(
        "dataset_splits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("strategy", sa.String(length=16), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("split_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "strategy IN ('random_stratified', 'group', 'temporal')",
            name="ck_dataset_splits_strategy",
        ),
    )
    op.create_index(
        "ix_dataset_splits_project_version", "dataset_splits",
        ["project_id", "dataset_version_id"],
    )

    op.create_table(
        "dataset_split_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "split_id", sa.Uuid(),
            sa.ForeignKey("dataset_splits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("sample_key", sa.String(length=256), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.UniqueConstraint("split_id", "row_index", name="uq_split_members_row"),
        sa.Index("ix_split_members_role", "split_id", "role"),
        sa.CheckConstraint(
            "role IN ('development', 'blind')",
            name="ck_split_members_role",
        ),
    )

    op.create_table(
        "modeling_rounds",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "split_id", sa.Uuid(),
            sa.ForeignKey("dataset_splits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("blind_eval_count", sa.Integer(), nullable=False),
        sa.Column("blind_eval_cap", sa.Integer(), nullable=False),
        sa.Column("blind_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "locked_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('open', 'locked', 'closed')",
            name="ck_modeling_rounds_status",
        ),
    )
    op.create_index(
        "ix_modeling_rounds_project_status", "modeling_rounds",
        ["project_id", "status"],
    )

    op.create_table(
        "blind_test_usages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "round_id", sa.Uuid(),
            sa.ForeignKey("modeling_rounds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "split_id", sa.Uuid(),
            sa.ForeignKey("dataset_splits.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("samples_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("ref", sa.JSON(), nullable=True),
        sa.Column("note", sa.String(length=256), nullable=True),
        sa.Column(
            "used_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "used_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )

    assert {"dataset_splits", "dataset_split_members", "modeling_rounds", "blind_test_usages"} <= _table_names()
    assert "ck_dataset_splits_strategy" in _constraint_names("dataset_splits")
    assert "uq_split_members_row" in _constraint_names("dataset_split_members")
    assert "ck_split_members_role" in _constraint_names("dataset_split_members")
    assert "ck_modeling_rounds_status" in _constraint_names("modeling_rounds")
    assert "ix_modeling_rounds_project_status" in _index_names("modeling_rounds")


def downgrade() -> None:
    op.drop_table("blind_test_usages")
    op.drop_index("ix_modeling_rounds_project_status", table_name="modeling_rounds")
    op.drop_table("modeling_rounds")
    op.drop_index("ix_split_members_role", table_name="dataset_split_members")
    op.drop_table("dataset_split_members")
    op.drop_index("ix_dataset_splits_project_version", table_name="dataset_splits")
    op.drop_table("dataset_splits")
