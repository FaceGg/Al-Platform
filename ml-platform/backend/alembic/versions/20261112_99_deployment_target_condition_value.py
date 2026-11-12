"""Deployment target condition value for unsupervised sharded routing (§6.3).

Revision ID: 20261112_99
Revises: 20261112_98
Create Date: 2026-11-12

工况分片路由（二期 M7）：DeploymentTarget 增 condition_value——该 target
服务的工况值（NULL=默认/通配分片）。ConditionValueRouter 按请求工况精确
匹配 target；未命中走默认分片。灰度路由（WeightedTargetRouter）语义不变，
二者互斥挂载。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261112_99"
down_revision = "20261112_98"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deployment_targets") as batch_op:
        batch_op.add_column(sa.Column("condition_value", sa.String(length=128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("deployment_targets") as batch_op:
        batch_op.drop_column("condition_value")
