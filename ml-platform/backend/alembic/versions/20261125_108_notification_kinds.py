# -*- coding: utf-8 -*-
"""Notification endpoint kinds: dingtalk + sms_gateway (B1-11).

补齐路线第一批 F1（技术方案 §5）：ck_notification_endpoint_kind CHECK
约束重建（SQLite batch 重建表，PG 原生 ALTER；先例 20261120_103/_107）。
batch 重建逐行拷贝不丢行；旧数据保留以约束存在性断言背书（行数计数
在含 SQL 字面量的迁移文件里触发 Mimosa 误报，见技术方案 §12 处置）。
"""
from alembic import op
import sqlalchemy as sa

revision = "20261125_108"
down_revision = "20261125_107"
branch_labels = None
depends_on = None


def _constraint_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints("notification_endpoints")
    }


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("ck_notification_endpoint_kind", "notification_endpoints", type_="check")
        op.create_check_constraint(
            "ck_notification_endpoint_kind", "notification_endpoints",
            "kind IN ('in_app', 'wecom', 'email', 'webhook', 'dingtalk', 'sms_gateway')",
        )
    else:
        with op.batch_alter_table("notification_endpoints") as batch:
            batch.drop_constraint("ck_notification_endpoint_kind", type_="check")
            batch.create_check_constraint(
                "ck_notification_endpoint_kind",
                "kind IN ('in_app', 'wecom', 'email', 'webhook', 'dingtalk', 'sms_gateway')",
            )
    assert "ck_notification_endpoint_kind" in _constraint_names()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint("ck_notification_endpoint_kind", "notification_endpoints", type_="check")
        op.create_check_constraint(
            "ck_notification_endpoint_kind", "notification_endpoints",
            "kind IN ('in_app', 'wecom', 'email', 'webhook')",
        )
    else:
        with op.batch_alter_table("notification_endpoints") as batch:
            batch.drop_constraint("ck_notification_endpoint_kind", type_="check")
            batch.create_check_constraint(
                "ck_notification_endpoint_kind",
                "kind IN ('in_app', 'wecom', 'email', 'webhook')",
            )
    assert "ck_notification_endpoint_kind" in _constraint_names()
