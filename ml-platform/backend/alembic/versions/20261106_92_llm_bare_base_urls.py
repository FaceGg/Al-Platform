"""Store bare base URLs for LLM profiles (ZCode-style model settings).

Revision ID: 20261106_92
Revises: 20261106_91
Create Date: 2026-11-06

91 曾把存量档案规范化为完整端点；对齐 ZCode 模型设置惯例后改为存裸 base
（Base URL 展示与供应商文档一致），协议路径由调用侧
normalize_llm_endpoint 内部拼接（探测/聊天/拉模型均已接入）。
本迁移把带已知后缀的存量 URL 剥回裸 base；已裸的行原样保留。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261106_92"
down_revision = "20261106_91"
branch_labels = None
depends_on = None

KNOWN_SUFFIXES = ("/v1/messages", "/chat/completions", "/responses")


def _strip(url: str) -> str:
    if not url:
        return url
    base = url.rstrip("/")
    for suffix in KNOWN_SUFFIXES:
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("select id, api_url from llm_profiles")
    ).fetchall()
    for row_id, api_url in rows:
        stripped = _strip(api_url or "")
        if stripped != api_url:
            conn.execute(
                sa.text("update llm_profiles set api_url = :url where id = :rid"),
                {"url": stripped, "rid": row_id},
            )


def downgrade() -> None:
    # 数据规范化迁移：无法可靠还原各行的协议格式，保持裸 base（调用侧兼容）
    pass
