# -*- coding: utf-8 -*-
"""Graph FK indexes: graph_relations.kb_id/source_id/target_id + graph_entities.kb_id.

重抽自动层时先删旧实体再批量插入。graph_relations 三个外键列与 graph_entities.kb_id
此前没有任何索引，PostgreSQL 也不给 FK 自动建索引：每删一个实体都要对子表做
存在性全表扫描，关系表膨胀后（多次重抽各写删 8.8 万行）单次重建劣化到数分钟、
并发重抽互相持锁（2026-11-19 观测，见 DEVELOPMENT_PLAN）。
为四个过滤/外键列补索引，实体删除的 FK 触发器检查从全表扫描降为索引点查。
"""
from alembic import op

revision = "20261119_102"
down_revision = "20261114_101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_graph_relations_kb_id", "graph_relations", ["kb_id"])
    op.create_index("ix_graph_relations_source_id", "graph_relations", ["source_id"])
    op.create_index("ix_graph_relations_target_id", "graph_relations", ["target_id"])
    op.create_index("ix_graph_entities_kb_id", "graph_entities", ["kb_id"])


def downgrade() -> None:
    op.drop_index("ix_graph_entities_kb_id", table_name="graph_entities")
    op.drop_index("ix_graph_relations_target_id", table_name="graph_relations")
    op.drop_index("ix_graph_relations_source_id", table_name="graph_relations")
    op.drop_index("ix_graph_relations_kb_id", table_name="graph_relations")
