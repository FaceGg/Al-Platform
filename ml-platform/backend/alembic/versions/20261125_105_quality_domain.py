# -*- coding: utf-8 -*-
"""Quality domain: scenes / stations / spec-limits + edge device shadow columns.

补齐路线第一批 F1（B1-10 领域模型，技术方案 §2）：
- quality_scenes / quality_stations / quality_spec_limits 三新表：
  项目 → 场景 → 工位 → 设备的领域模型落库。规格定义是 E27 单一来源
  （字段 + 波形统计量 + 上下限 + 单位，uq (scene_id, field, statistic)）。
- edge_devices 补 shadow_desired / shadow_reported 两列：设备影子双状态
  （诚实设计⑤预留，B4-02 正式落地），本批不读写。

场景的外部数据源绑定列（data_source_id）随 _107 建表后同批加入。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261125_105"
down_revision = "20261120_104"
branch_labels = None
depends_on = None


def _edge_device_count() -> int:
    # 表达式构造（无字符串 SQL）：加列前后行数一致断言用
    conn = op.get_bind()
    devices = sa.table("edge_devices", sa.column("id"))
    return int(conn.execute(sa.select(sa.func.count()).select_from(devices)).scalar() or 0)


def upgrade() -> None:
    # 旧数据保留断言：edge_devices 加列前后行数一致（三新表无存量数据）
    devices_before = _edge_device_count()

    with op.batch_alter_table("edge_devices") as batch:
        batch.add_column(sa.Column("shadow_desired", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("shadow_reported", sa.JSON(), nullable=True))

    devices_after = _edge_device_count()
    assert devices_after == devices_before, (
        f"edge_devices row count changed during migration: "
        f"{devices_before} -> {devices_after}"
    )

    op.create_table(
        "quality_scenes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "deployment_id", sa.Uuid(),
            sa.ForeignKey("inference_deployments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("condition_column", sa.String(128), nullable=True),
        sa.Column("field_roles", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("waveform_column", sa.String(256), nullable=True),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "project_id", "code", name="uq_quality_scenes_project_code",
        ),
    )
    op.create_index("ix_quality_scenes_project_id", "quality_scenes", ["project_id"])

    op.create_table(
        "quality_stations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "scene_id", sa.Uuid(),
            sa.ForeignKey("quality_scenes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("factory", sa.String(128), nullable=True),
        sa.Column("workshop", sa.String(128), nullable=True),
        sa.Column("production_line", sa.String(128), nullable=True),
        sa.Column(
            "edge_device_id", sa.Uuid(),
            sa.ForeignKey("edge_devices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "responsible_user_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true(),
        ),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "scene_id", "code", name="uq_quality_stations_scene_code",
        ),
    )
    op.create_index("ix_quality_stations_scene_id", "quality_stations", ["scene_id"])
    op.create_index(
        "ix_quality_stations_location",
        "quality_stations",
        ["factory", "workshop", "production_line"],
    )

    op.create_table(
        "quality_spec_limits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "scene_id", sa.Uuid(),
            sa.ForeignKey("quality_scenes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field", sa.String(256), nullable=False),
        sa.Column("statistic", sa.String(16), nullable=False, server_default="value"),
        sa.Column("usl", sa.Float(), nullable=True),
        sa.Column("lsl", sa.Float(), nullable=True),
        sa.Column("target", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "scene_id", "field", "statistic",
            name="uq_quality_spec_limits_scene_field_statistic",
        ),
        sa.CheckConstraint(
            "statistic IN ('value', 'mean', 'min', 'max', 'rms')",
            name="ck_quality_spec_limits_statistic",
        ),
    )
    op.create_index("ix_quality_spec_limits_scene_id", "quality_spec_limits", ["scene_id"])


def downgrade() -> None:
    op.drop_index("ix_quality_spec_limits_scene_id", table_name="quality_spec_limits")
    op.drop_table("quality_spec_limits")
    op.drop_index("ix_quality_stations_location", table_name="quality_stations")
    op.drop_index("ix_quality_stations_scene_id", table_name="quality_stations")
    op.drop_table("quality_stations")
    op.drop_index("ix_quality_scenes_project_id", table_name="quality_scenes")
    op.drop_table("quality_scenes")
    with op.batch_alter_table("edge_devices") as batch:
        batch.drop_column("shadow_reported")
        batch.drop_column("shadow_desired")
