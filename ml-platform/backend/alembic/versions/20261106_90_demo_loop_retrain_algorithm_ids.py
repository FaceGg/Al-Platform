"""Demo loop retrain algorithm whitelist (wizard guidance → engine families).

Revision ID: 20261106_90
Revises: 20261106_89
Create Date: 2026-11-06

向导「算法白名单」此前无消费方（勾选形同虚设）：随配方固化/服务化带入
闭环配置，闭环重训按白名单缩小引擎搜索族（空 = 全族）。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261106_90"
down_revision = "20261106_89"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.add_column(sa.Column("retrain_algorithm_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.drop_column("retrain_algorithm_ids")
