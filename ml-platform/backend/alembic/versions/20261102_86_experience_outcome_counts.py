"""experience entries: outcome feedback counters (success_count/fail_count)

Revision ID: 20261102_86
Revises: 20261029_85
Create Date: 2026-11-02

§10.1 经验生命周期闭环：注入过教训的任务终态成败回写，需要按条目累计
成功/失败计数（知识中心展示 + 后续结果驱动调分的审计依据）。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261102_86"
down_revision = "20261029_85"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "experience_entries",
        sa.Column("success_count", sa.Integer(), nullable=True, server_default=sa.text("0")),
    )
    op.add_column(
        "experience_entries",
        sa.Column("fail_count", sa.Integer(), nullable=True, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("experience_entries", "fail_count")
    op.drop_column("experience_entries", "success_count")
