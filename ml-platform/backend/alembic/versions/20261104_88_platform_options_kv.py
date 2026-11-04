"""platform options KV（聊天工具启停等全局配置存储）

Revision ID: 20261104_88
Revises: 20261104_87
Create Date: 2026-11-04

管理员级全局配置（首个消费者：AI 对话白名单工具启停，配置对全部
用户生效）。key 唯一，value 为 JSON。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261104_88"
down_revision = "20261104_87"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_options",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("platform_options")
