# -*- coding: utf-8 -*-
"""Monitoring indexes (B1-03/04/05, F3).

补齐路线第一批 F3（技术方案 §9B）：
- inference_results (station_id, occurred_at)：实时监控的工位卡按工位取最新一条结果；
- quality_alerts (project_id, created_at)：驾驶舱与趋势页按时间窗聚合预警；
- quality_alerts (station_id, created_at)：工位风险排名与工位卡的最近预警。

纯索引迁移：不建表、不改列、不动数据。索引是否建成以反射结果断言。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261126_110"
down_revision = "20261126_109"
branch_labels = None
depends_on = None


def _index_names(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    op.create_index(
        "ix_inference_results_station_occurred", "inference_results",
        ["station_id", "occurred_at"],
    )
    op.create_index(
        "ix_quality_alerts_project_created", "quality_alerts",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_quality_alerts_station_created", "quality_alerts",
        ["station_id", "created_at"],
    )
    assert "ix_inference_results_station_occurred" in _index_names("inference_results")
    assert {
        "ix_quality_alerts_project_created", "ix_quality_alerts_station_created",
    } <= _index_names("quality_alerts")


def downgrade() -> None:
    op.drop_index("ix_quality_alerts_station_created", table_name="quality_alerts")
    op.drop_index("ix_quality_alerts_project_created", table_name="quality_alerts")
    op.drop_index("ix_inference_results_station_occurred", table_name="inference_results")
