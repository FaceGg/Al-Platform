"""Demo loop retrain ensemble: weighted soft-voting final-selection on retrain.

Revision ID: 20261106_89
Revises: 20261104_88
Create Date: 2026-11-06

闭环重训可开启终选层集成：重训 AutoML 任务按主指标取前 K 名家族做
soft-voting，不低于单模型冠军才成为任务冠军并参与换模（仅单输出分类）。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261106_89"
down_revision = "20261104_88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "retrain_ensemble_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "retrain_ensemble_top_k",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("3"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.drop_column("retrain_ensemble_top_k")
        batch_op.drop_column("retrain_ensemble_enabled")
