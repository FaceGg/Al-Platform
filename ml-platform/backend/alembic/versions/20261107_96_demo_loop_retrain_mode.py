"""Demo loop agent-retrain mode columns.

Revision ID: 20261107_96
Revises: 20261107_95
Create Date: 2026-11-07

闭环「智能体重训模式」（P1）：retrain_mode 开关（engine 默认行为不变）+
agent 重放所需的配方绑定 / AgentRun 引用 / 轮询超时基点 / 冷却期 /
已消费报错基线（增量边沿触发判据，防突发回流连环重训）。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261107_96"
down_revision = "20261107_95"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.add_column(
            sa.Column("retrain_mode", sa.String(length=16), nullable=False,
                      server_default="engine")
        )
        batch_op.add_column(sa.Column("retrain_agent_recipe_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("retrain_agent_run_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("retrain_agent_started_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("retrain_cool_until", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("retrain_trained_baseline_count", sa.Integer(),
                      nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.drop_column("retrain_trained_baseline_count")
        batch_op.drop_column("retrain_cool_until")
        batch_op.drop_column("retrain_agent_started_at")
        batch_op.drop_column("retrain_agent_run_id")
        batch_op.drop_column("retrain_agent_recipe_id")
        batch_op.drop_column("retrain_mode")
