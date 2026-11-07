"""Demo loop retrain input columns (sparse wide-table support).

Revision ID: 20261107_97
Revises: 20261107_96
Create Date: 2026-11-07

闭环重训特征列白名单：稀疏宽表引擎 dropna 全剔 0 行幸存（E2E 实证），
配置列集后引擎仅对选定列 dropna/取特征。空 = 全部数值列（行为不变）。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261107_97"
down_revision = "20261107_96"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.add_column(sa.Column("retrain_input_columns", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.drop_column("retrain_input_columns")
