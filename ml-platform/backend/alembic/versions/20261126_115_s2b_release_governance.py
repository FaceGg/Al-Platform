# -*- coding: utf-8 -*-
"""S2b release governance: shadow reports / release checks / preauth / receipts (B2-09/02/03/G2/G3).

补齐路线第二批 S2b（技术方案 §7.1，迁移 _115）：
- 四新表：shadow_comparisons（E14 不可变对照报告）、release_checks（门禁随
  发布单归档）、release_preauthorizations（G2）、rollout_receipts（G3 回执契约）；
- DeploymentTarget.role CHECK 重建：('stable','candidate') → + 'challenger'
  （B2-09 别名在既有部署目标机制上扩展，challenger 权重恒 0 不进生产路由）。
SQLite batch；PG 原生。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261126_115"
down_revision = "20261126_114"
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
        "shadow_comparisons",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("deployment_id", sa.Uuid(), nullable=True),
        sa.Column("champion_version_id", sa.Uuid(), nullable=True),
        sa.Column("challenger_version_id", sa.Uuid(), nullable=True),
        sa.Column("window_start", sa.DateTime(), nullable=True),
        sa.Column("window_end", sa.DateTime(), nullable=True),
        sa.Column("sample_source", sa.String(length=16), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("agreement_rate", sa.Float(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("report_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "sample_source IN ('random_sample', 'traffic_mirror')",
            name="ck_shadow_comparisons_source",
        ),
    )
    op.create_index(
        "ix_shadow_comparisons_deployment", "shadow_comparisons",
        ["deployment_id", "created_at"],
    )

    op.create_table(
        "release_checks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "approval_id", sa.Uuid(),
            sa.ForeignKey("approval_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check_key", sa.String(length=64), nullable=False),
        sa.Column("threshold", sa.JSON(), nullable=True),
        sa.Column("observed", sa.JSON(), nullable=True),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "verdict IN ('passed', 'failed', 'not_applicable')",
            name="ck_release_checks_verdict",
        ),
    )
    op.create_index("ix_release_checks_approval", "release_checks", ["approval_id"])

    op.create_table(
        "release_preauthorizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("deployment_id", sa.Uuid(), nullable=True),
        sa.Column("station_id", sa.Uuid(), nullable=True),
        sa.Column("acceptance_gates_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "valid_from", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("max_releases", sa.Integer(), nullable=False),
        sa.Column("releases_used", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "granted_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_release_preauth_status",
        ),
    )
    op.create_index(
        "ix_release_preauth_project", "release_preauthorizations",
        ["project_id", "status"],
    )

    op.create_table(
        "rollout_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rollout_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=True),
        sa.Column("routing_key", sa.String(length=256), nullable=True),
        sa.Column("effective_alias", sa.String(length=256), nullable=False),
        sa.Column("scored_count", sa.BigInteger(), nullable=False),
        sa.Column("artifact_digest", sa.String(length=64), nullable=True),
        sa.Column("window_start", sa.DateTime(), nullable=True),
        sa.Column("window_end", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "reported_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reported_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('valid', 'digest_mismatch')",
            name="ck_rollout_receipts_status",
        ),
    )
    op.create_index(
        "ix_rollout_receipts_rollout", "rollout_receipts",
        ["rollout_id", "reported_at"],
    )

    # DeploymentTarget.role CHECK 重建：+ 'challenger'（存量行 stable/candidate 天然满足）
    with op.batch_alter_table("deployment_targets") as batch:
        batch.drop_constraint("ck_deployment_targets_role", type_="check")
        batch.create_check_constraint(
            "ck_deployment_targets_role",
            "role IN ('stable', 'candidate', 'challenger')",
        )

    assert {
        "shadow_comparisons", "release_checks",
        "release_preauthorizations", "rollout_receipts",
    } <= _table_names()
    assert "ck_shadow_comparisons_source" in _constraint_names("shadow_comparisons")
    assert "ck_release_checks_verdict" in _constraint_names("release_checks")
    assert "ck_release_preauth_status" in _constraint_names("release_preauthorizations")
    assert "ck_rollout_receipts_status" in _constraint_names("rollout_receipts")
    assert "ck_deployment_targets_role" in _constraint_names("deployment_targets")


def downgrade() -> None:
    op.drop_index("ix_rollout_receipts_rollout", table_name="rollout_receipts")
    op.drop_table("rollout_receipts")
    op.drop_index("ix_release_preauth_project", table_name="release_preauthorizations")
    op.drop_table("release_preauthorizations")
    op.drop_index("ix_release_checks_approval", table_name="release_checks")
    op.drop_table("release_checks")
    op.drop_index("ix_shadow_comparisons_deployment", table_name="shadow_comparisons")
    op.drop_table("shadow_comparisons")
    with op.batch_alter_table("deployment_targets") as batch:
        batch.drop_constraint("ck_deployment_targets_role", type_="check")
        batch.create_check_constraint(
            "ck_deployment_targets_role",
            "role IN ('stable', 'candidate')",
        )
