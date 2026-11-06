"""Group LLM profiles by provider identity (provider_group per provider).

Revision ID: 20261107_95
Revises: 20261107_94
Create Date: 2026-11-07

档案缺供应商身份 → 前端只能按 host 聚合，重复添加同名供应商会并入已有组。
加 provider_group 列：存量按 (api_url, api_key_encrypted) 相同归入同组；
此后添加供应商模板每张卡生成新组，供应商内添加模型/克隆继承组。
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "20261107_95"
down_revision = "20261107_94"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("llm_profiles") as batch_op:
        batch_op.add_column(sa.Column("provider_group", sa.String(64), nullable=True))
    # 索引建在 batch 块外：SQLite batch 重建表基于加列前的镜像，块内建索引会报列不存在
    op.create_index("ix_llm_profiles_provider_group", "llm_profiles", ["provider_group"])

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "select id, api_url, api_key_encrypted, provider_group "
            "from llm_profiles order by created_at"
        )
    ).fetchall()
    groups: dict[tuple, str] = {}
    for row_id, api_url, api_key, group in rows:
        if group:
            continue
        key = (api_url or "", api_key or "")
        if key not in groups:
            groups[key] = uuid.uuid4().hex
        conn.execute(
            sa.text("update llm_profiles set provider_group = :g where id = :rid"),
            {"g": groups[key], "rid": row_id},
        )


def downgrade() -> None:
    op.drop_index("ix_llm_profiles_provider_group", table_name="llm_profiles")
    with op.batch_alter_table("llm_profiles") as batch_op:
        batch_op.drop_column("provider_group")
