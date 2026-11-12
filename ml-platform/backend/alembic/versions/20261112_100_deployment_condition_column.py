"""Deployment condition column declaration for sharded routing (§6.3).

Revision ID: 20261112_100
Revises: 20261112_99
Create Date: 2026-11-12

工况分片路由（二期 M7）：InferenceDeployment 增 condition_column——部署级
工况路由声明（NULL=普通部署，灰度/立即语义不变）。非空即进入工况分片
路由模式：predict 按请求记录的该列取值精确匹配 target（condition_value），
与灰度路由互斥挂载（方案 §6.5）。闭环分片换模时自动写入（取自训练任务
metrics.condition_column），无需手动配置。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261112_100"
down_revision = "20261112_99"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("inference_deployments") as batch_op:
        batch_op.add_column(sa.Column("condition_column", sa.String(length=128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("inference_deployments") as batch_op:
        batch_op.drop_column("condition_column")
