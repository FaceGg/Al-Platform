# -*- coding: utf-8 -*-
"""KG: per-KB extraction LLM profile selection (knowledge_bases.kg_llm_profile_id).

深度抽取此前只能跟随平台默认档案（网关 purpose 只是审计标签，不参与选型），
而默认档案的模型可能是推理型（思考重、分片慢）。加按库可选的抽取专用档案：
空 = 跟随平台默认（行为不变）；指定 = 抽取/融合仲裁按该档案调用。

SQLite 不支持 ALTER 加约束：FK 走 batch_alter_table（测试库小数据无碍），
PostgreSQL 走原生 ALTER，与 20261120_103 的做法一致。
"""
from alembic import op
import sqlalchemy as sa

revision = "20261120_104"
down_revision = "20261120_103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("kg_llm_profile_id", sa.Uuid(), nullable=True),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_knowledge_bases_kg_llm_profile", "knowledge_bases", "llm_profiles",
            ["kg_llm_profile_id"], ["id"], ondelete="SET NULL",
        )
    else:
        with op.batch_alter_table("knowledge_bases") as batch:
            batch.create_foreign_key(
                "fk_knowledge_bases_kg_llm_profile", "llm_profiles",
                ["kg_llm_profile_id"], ["id"], ondelete="SET NULL",
            )
    op.create_index(
        "ix_knowledge_bases_kg_llm_profile_id", "knowledge_bases", ["kg_llm_profile_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_bases_kg_llm_profile_id", table_name="knowledge_bases")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "fk_knowledge_bases_kg_llm_profile", "knowledge_bases", type_="foreignkey",
        )
    else:
        with op.batch_alter_table("knowledge_bases") as batch:
            batch.drop_constraint("fk_knowledge_bases_kg_llm_profile", type_="foreignkey")
    op.drop_column("knowledge_bases", "kg_llm_profile_id")
