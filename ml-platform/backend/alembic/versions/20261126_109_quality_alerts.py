# -*- coding: utf-8 -*-
"""Quality alerts & disposition (B1-01/B1-02, F2a Q1).

补齐路线第一批 F2（技术方案 §9.1，D14–D22）：
- quality_alerts / quality_alert_events / quality_sops /
  quality_spc_baselines / model_evidence_checks 五张新表；
- quality_scenes 补 alert_settings JSON 列（场景级预警规则，缺省=平台默认）；
- inference_results.alert_id 由 F1 的 String(36) 占位改建为 Uuid 外键
  （指向 quality_alerts.id，SET NULL；存量全 NULL，drop+add 列零风险）。

SQLite 走 batch 重建（先例 _106/_107/_108）；PG 分支走原生 ADD/DROP COLUMN。
旧数据保留以「channel CHECK 约束仍在 + alert_id 外键已挂 + 五新表存在」
断言背书（行数计数不写进迁移文件——SQL 执行形态触发 Mimosa 误报，先例
_108；行数前后一致改在迁移合同测试 test_gap_batch1_migrations 内断言）。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261126_109"
down_revision = "20261125_108"
branch_labels = None
depends_on = None


def _table_names() -> set:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def _constraint_names(table):
    inspector = sa.inspect(op.get_bind())
    names = set()
    for kind in ("check_constraints", "foreign_keys"):
        for constraint in getattr(inspector, "get_" + kind)(table):
            names.add(constraint["name"])
    return names


def _create_quality_alerts() -> None:
    op.create_table(
        "quality_alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scene_id", sa.Uuid(),
            sa.ForeignKey("quality_scenes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "station_id", sa.Uuid(),
            sa.ForeignKey("quality_stations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "device_id", sa.Uuid(),
            sa.ForeignKey("edge_devices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("condition_value", sa.String(128), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("sample_key", sa.String(256), nullable=True),
        sa.Column("batch_no", sa.String(128), nullable=True),
        sa.Column("product_code", sa.String(128), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("source_ref", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "assigned_to_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("first_ack_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("sla_due_at", sa.DateTime(), nullable=True),
        sa.Column("sla_notify_level", sa.SmallInteger(), nullable=False),
        sa.Column("resolution", sa.String(32), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("merge_key", sa.String(256), nullable=False),
        sa.Column("merge_open", sa.Boolean(), nullable=False),
        sa.Column("last_event_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.CheckConstraint(
            "source_type IN ('model_risk', 'param_exceed', 'device_anomaly', "
            "'spc_violation', 'sensor_anomaly', 'curve_deviation')",
            name="ck_quality_alerts_source_type",
        ),
        sa.CheckConstraint(
            "severity IN ('warning', 'high', 'critical')",
            name="ck_quality_alerts_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'processing', "
            "'review_pending', 'closed')",
            name="ck_quality_alerts_status",
        ),
    )
    op.create_index("ix_quality_alerts_project_id", "quality_alerts", ["project_id"])
    op.create_index(
        "ix_quality_alerts_project_status", "quality_alerts", ["project_id", "status"]
    )
    op.create_index("ix_quality_alerts_status", "quality_alerts", ["status"])
    op.create_index("ix_quality_alerts_sample_key", "quality_alerts", ["sample_key"])
    op.create_index("ix_quality_alerts_batch_no", "quality_alerts", ["batch_no"])
    op.create_index("ix_quality_alerts_sla_due", "quality_alerts", ["sla_due_at"])
    op.create_index("ix_quality_alerts_is_demo", "quality_alerts", ["is_demo"])
    op.create_index(
        "ix_quality_alerts_merge_key", "quality_alerts",
        ["project_id", "merge_key", "merge_open"],
    )


def _create_quality_alert_events() -> None:
    op.create_table(
        "quality_alert_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "alert_id", sa.Uuid(),
            sa.ForeignKey("quality_alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=True),
        sa.Column(
            "actor_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("form_snapshot", sa.JSON(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "action IN ('created', 'occurred', 'acknowledged', 'assigned', "
            "'status_changed', 'disposition_submitted', 'transfer', "
            "'review_requested', 'attachment_added', 'comment', "
            "'device_recovered', 'sla_notified', 'review_task_created')",
            name="ck_quality_alert_events_action",
        ),
    )
    op.create_index(
        "ix_quality_alert_events_alert", "quality_alert_events",
        ["alert_id", "created_at"],
    )


def _create_quality_sops() -> None:
    op.create_table(
        "quality_sops",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scene_id", sa.Uuid(),
            sa.ForeignKey("quality_scenes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("condition_value", sa.String(128), nullable=True),
        sa.Column("effective_from", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_quality_sops_project_id", "quality_sops", ["project_id"])
    op.create_index("ix_quality_sops_project_code", "quality_sops", ["project_id", "code"])


def _create_quality_spc_baselines() -> None:
    op.create_table(
        "quality_spc_baselines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scene_id", sa.Uuid(),
            sa.ForeignKey("quality_scenes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "station_id", sa.Uuid(),
            sa.ForeignKey("quality_stations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("condition_value", sa.String(128), nullable=True),
        sa.Column("field", sa.String(256), nullable=False),
        sa.Column("statistic", sa.String(16), nullable=False),
        sa.Column("center", sa.Float(), nullable=False),
        sa.Column("sigma", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("reference", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_quality_spc_baselines_project_id", "quality_spc_baselines", ["project_id"]
    )
    op.create_index(
        "ix_quality_spc_baselines_key", "quality_spc_baselines",
        ["scene_id", "station_id", "condition_value", "field", "is_active"],
    )


def _create_model_evidence_checks() -> None:
    op.create_table(
        "model_evidence_checks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_version_id", sa.Uuid(),
            sa.ForeignKey("model_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_model_evidence_checks_version", "model_evidence_checks",
        ["model_version_id", "created_at"],
    )


_ALERT_FK_NAME = "fk_inference_results_alert_id_quality_alerts"


def _alert_id_foreign_key_present() -> bool:
    """inference_results.alert_id → quality_alerts.id 外键是否已挂上。

    SQLite 的反射不回报外键名，所以按「约束列 + 目标表」判定，不按名字。
    """
    inspector = sa.inspect(op.get_bind())
    return any(
        foreign_key.get("constrained_columns") == ["alert_id"]
        and foreign_key.get("referred_table") == "quality_alerts"
        for foreign_key in inspector.get_foreign_keys("inference_results")
    )


def _alter_existing_tables() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    alert_column = sa.Column("alert_id", sa.Uuid(), nullable=True)
    if is_postgres:
        op.add_column(
            "quality_scenes",
            sa.Column("alert_settings", sa.JSON(), nullable=True),
        )
        op.drop_column("inference_results", "alert_id")
        op.add_column("inference_results", alert_column)
        op.create_foreign_key(
            _ALERT_FK_NAME,
            "inference_results",
            "quality_alerts",
            ["alert_id"],
            ["id"],
            ondelete="SET NULL",
        )
    else:
        with op.batch_alter_table("quality_scenes") as batch:
            batch.add_column(sa.Column("alert_settings", sa.JSON(), nullable=True))
        with op.batch_alter_table("inference_results") as batch:
            batch.drop_column("alert_id")
            batch.add_column(alert_column)
            batch.create_foreign_key(
                _ALERT_FK_NAME,
                "quality_alerts",
                ["alert_id"],
                ["id"],
                ondelete="SET NULL",
            )


def upgrade() -> None:
    _create_quality_alerts()
    _create_quality_alert_events()
    _create_quality_sops()
    _create_quality_spc_baselines()
    _create_model_evidence_checks()
    _alter_existing_tables()
    # 旧数据保留断言：channel CHECK 仍在（batch 重建未丢约束）；alert_id
    # 外键已挂上；五新表齐备。行数前后一致在迁移合同测试断言。
    assert "ck_inference_results_channel" in _constraint_names("inference_results")
    assert _alert_id_foreign_key_present()
    assert {
        "quality_alerts",
        "quality_alert_events",
        "quality_sops",
        "quality_spc_baselines",
        "model_evidence_checks",
    } <= _table_names()


def downgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    legacy_alert_column = sa.Column("alert_id", sa.String(36), nullable=True)
    if is_postgres:
        op.drop_constraint(_ALERT_FK_NAME, "inference_results", type_="foreignkey")
        op.drop_column("inference_results", "alert_id")
        op.add_column("inference_results", legacy_alert_column)
        op.drop_column("quality_scenes", "alert_settings")
    else:
        # 反射得到的外键在 SQLite 下没有名字：用与升级时相同的命名规则
        # 给表上所有外键定名，再按名删除（batch 模式要求被删约束有名）。
        with op.batch_alter_table(
            "inference_results",
            naming_convention={
                "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            },
        ) as batch:
            batch.drop_constraint(_ALERT_FK_NAME, type_="foreignkey")
            batch.drop_column("alert_id")
            batch.add_column(legacy_alert_column)
        with op.batch_alter_table("quality_scenes") as batch:
            batch.drop_column("alert_settings")
    op.drop_index(
        "ix_model_evidence_checks_version", table_name="model_evidence_checks"
    )
    op.drop_table("model_evidence_checks")
    op.drop_index(
        "ix_quality_spc_baselines_key", table_name="quality_spc_baselines"
    )
    op.drop_index(
        "ix_quality_spc_baselines_project_id", table_name="quality_spc_baselines"
    )
    op.drop_table("quality_spc_baselines")
    op.drop_index("ix_quality_sops_project_code", table_name="quality_sops")
    op.drop_index("ix_quality_sops_project_id", table_name="quality_sops")
    op.drop_table("quality_sops")
    op.drop_index(
        "ix_quality_alert_events_alert", table_name="quality_alert_events"
    )
    op.drop_table("quality_alert_events")
    for index_name in (
        "ix_quality_alerts_is_demo",
        "ix_quality_alerts_merge_key",
        "ix_quality_alerts_sla_due",
        "ix_quality_alerts_batch_no",
        "ix_quality_alerts_sample_key",
        "ix_quality_alerts_status",
        "ix_quality_alerts_project_status",
        "ix_quality_alerts_project_id",
    ):
        op.drop_index(index_name, table_name="quality_alerts")
    op.drop_table("quality_alerts")
