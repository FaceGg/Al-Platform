"""Workflow global templates: allow platform-wide templates without a project.

Revision ID: 20261014_69
Revises: 20261010_68
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op

revision = "20261014_69"
down_revision = "20261010_68"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # project_id 为空 = 平台通用模板（不归属项目，全平台可见可实例化）。
    # batch 模式保证 SQLite 重建表与 PostgreSQL 原生 ALTER 双方言兼容。
    with op.batch_alter_table("workflows") as batch_op:
        batch_op.alter_column("project_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    # 前置条件：须先处理掉通用模板行（project_id 为空的 workflows 行），
    # 否则数据库会因违反 NOT NULL 约束拒绝本次收紧。
    with op.batch_alter_table("workflows") as batch_op:
        batch_op.alter_column("project_id", existing_type=sa.UUID(), nullable=False)
