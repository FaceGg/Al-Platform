"""Announcements table for the portal notices panel (admin-managed).

Revision ID: 20261026_83
Revises: 20261023_82
Create Date: 2026-10-26
"""

import datetime as dt
import uuid

import sqlalchemy as sa
from alembic import op

revision = "20261026_83"
down_revision = "20261023_82"
branch_labels = None
depends_on = None

# The three notices previously hardcoded on the portal page.
_SEED_ANNOUNCEMENTS = [
    {
        "title": "智能体中心上线",
        "content": "建模智能体向导开放，欢迎试用",
        "pinned": True,
    },
    {
        "title": "大模型管理切换 DeepSeek",
        "content": "默认档案已切换 deepseek-chat，连通验证通过",
        "pinned": False,
    },
    {
        "title": "五视图改版上线",
        "content": "门户 / 算法平台 / 智能体中心 / 基础设施 / 系统管理",
        "pinned": False,
    },
]


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("pinned", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index(
        "ix_announcements_created", "announcements", ["created_at"],
    )
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    op.execute(
        sa.table(
            "announcements",
            sa.column("id", sa.UUID),
            sa.column("title", sa.String),
            sa.column("content", sa.Text),
            sa.column("pinned", sa.Boolean),
            sa.column("created_by", sa.String),
            sa.column("created_at", sa.DateTime),
            sa.column("updated_at", sa.DateTime),
        ).insert().values(
            [
                {
                    "id": str(uuid.uuid4()),
                    "title": item["title"],
                    "content": item["content"],
                    "pinned": item["pinned"],
                    "created_by": "admin",
                    "created_at": now,
                    "updated_at": now,
                }
                for item in _SEED_ANNOUNCEMENTS
            ]
        )
    )


def downgrade() -> None:
    op.drop_index("ix_announcements_created", table_name="announcements")
    op.drop_table("announcements")
