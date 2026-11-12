"""Demo loop unsupervised PSI drift detection config (技术方案 §3.6).

Revision ID: 20261112_98
Revises: 20261107_97
Create Date: 2026-11-12

无监督分数漂移治理：psi_enabled 开启后，回流分数分布对训练基线
（score_stats.json 分位表）的 PSI ≥ psi_threshold（默认 0.25）即触发
重拟合预警——分数漂移比单特征漂移更早发现模型失配。默认关闭=存量
闭环行为零变化（有监督任务不感知新列）。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261112_98"
down_revision = "20261107_97"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.add_column(sa.Column("psi_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("psi_threshold", sa.Float(), nullable=False, server_default="0.25"))
        # PSI 评估节流与最近结果（last_total/last_psi/level）——每条回流都
        # 物化数据集算 PSI 太贵，total_count 未变时跳过重算。
        batch_op.add_column(sa.Column("psi_state", sa.JSON(), nullable=True))
        # 报警确认反馈（弱监督回流 §3.6）：{"<artifact_id>": {"<row_index>":
        # "confirmed_fault"|"false_alarm"}}——标记存配置列而非回写工件（避免
        # 破坏存储完整性），物化时打 feedback 列供重拟合/换模门禁消费。
        batch_op.add_column(sa.Column("feedback_marks", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("demo_loop_configs") as batch_op:
        batch_op.drop_column("feedback_marks")
        batch_op.drop_column("psi_state")
        batch_op.drop_column("psi_threshold")
        batch_op.drop_column("psi_enabled")
