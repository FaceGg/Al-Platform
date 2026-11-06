"""Normalize stored LLM endpoint URLs: bare base + format suffix.

Revision ID: 20261106_91
Revises: 20261106_90
Create Date: 2026-11-06

存量档案按供应商文档习惯填了裸 base（如 https://api.deepseek.com/anthropic/），
而平台合同是完整端点 → 探测/聊天 POST 到 base 全部 404（真机报障）。
按 provider 补全后缀；已带任一已知后缀的行原样保留。
"""

import sqlalchemy as sa
from alembic import op

revision = "20261106_91"
down_revision = "20261106_90"
branch_labels = None
depends_on = None

SUFFIXES = {
    "anthropic": "/v1/messages",
    "openai_compatible": "/chat/completions",
    "responses": "/responses",
}


def _normalize(url: str, provider: str | None) -> str:
    if not url:
        return url
    base = url.rstrip("/")
    known = list(SUFFIXES.values())
    if any(base.endswith(known_item) for known_item in known):
        return url
    suffix = SUFFIXES.get(provider or "")
    if not suffix:
        return url
    return base + suffix


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("select id, api_url, provider from llm_profiles")
    ).fetchall()
    for row_id, api_url, provider in rows:
        fixed = _normalize(api_url or "", provider)
        if fixed != api_url:
            conn.execute(
                sa.text("update llm_profiles set api_url = :url where id = :rid"),
                {"url": fixed, "rid": row_id},
            )


def downgrade() -> None:
    # 数据规范化迁移：无结构可回滚（完整端点本身就是正确形态）
    pass
