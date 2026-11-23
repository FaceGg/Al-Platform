# -*- coding: utf-8 -*-
"""KG pipeline: ontology / fusion / llm-extraction jobs + entity disambiguation columns.

五阶段知识图谱流水线的存储底座：
- knowledge_bases.kg_ontology：按库覆盖的实体/关系类型本体（空=用默认工业本体）。
- graph_entities.merged_into / aliases：知识融合的合并指针（指向存活实体）与
  别名表；同名归一由融合层负责，存储层用部分唯一索引（WHERE merged_into IS NULL）
  挡住同库同名节点的再次产生。
- kg_extraction_jobs / kg_unit_results：LLM 深度抽取的异步任务与单元结果缓存
  （幂等键 kb_id+chunk_id+content_hash，支持断点续抽）。
- kg_merge_suggestions：融合建议队列（自动归并留痕 / LLM 仲裁待审 / 属性冲突）。

历史脏数据治理：迁移内先把同库同名重复实体确定性合并（保留最早一行，重指其全部
关系，其余置 merged_into），随后才建部分唯一索引——否则存量重名会让索引创建失败。
properties->>'source' 表达式索引仅 PostgreSQL 创建（SQLite 测试库无数据量需求，
且旧 SQLite 版本可能不认 ->> 操作符）。
"""
from alembic import op
import sqlalchemy as sa

revision = "20261120_103"
down_revision = "20261119_102"
branch_labels = None
depends_on = None


def _dedupe_same_name_entities() -> None:
    """Merge exact same-name entity rows per KB before the unique index.

    保留策略：created_at 最早者存活（并列取 id 字典序最小，保证确定性）。
    关系重指必须在置 merged_into 之前完成，否则外键语义断裂。
    """
    conn = op.get_bind()
    dup_rows = conn.execute(sa.text(
        """
        SELECT kb_id, name FROM graph_entities
        GROUP BY kb_id, name HAVING count(*) > 1
        """
    )).fetchall()
    for kb_id, name in dup_rows:
        rows = conn.execute(sa.text(
            """
            SELECT id FROM graph_entities
            WHERE kb_id = :kb_id AND name = :name
            ORDER BY created_at ASC, id ASC
            """
        ), {"kb_id": kb_id, "name": name}).fetchall()
        survivor = str(rows[0][0])
        losers = [str(r[0]) for r in rows[1:]]
        for loser in losers:
            conn.execute(sa.text(
                "UPDATE graph_relations SET source_id = :s WHERE source_id = :l"
            ), {"s": survivor, "l": loser})
            conn.execute(sa.text(
                "UPDATE graph_relations SET target_id = :s WHERE target_id = :l"
            ), {"s": survivor, "l": loser})
            conn.execute(sa.text(
                "UPDATE graph_entities SET merged_into = :s WHERE id = :l"
            ), {"s": survivor, "l": loser})


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("kg_ontology", sa.JSON(), nullable=True),
    )
    op.add_column(
        "graph_entities",
        sa.Column("merged_into", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "graph_entities",
        sa.Column(
            "aliases", sa.JSON(), nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    _dedupe_same_name_entities()
    # SQLite 不支持 ALTER 加约束：batch 模式（copy-and-move）在测试库的
    # 小数据量上无碍；PostgreSQL 生产走原生 ALTER（graph_entities 7915 行
    # 级别，batch 复制表不可接受）
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_graph_entities_merged_into", "graph_entities", "graph_entities",
            ["merged_into"], ["id"], ondelete="CASCADE",
        )
    else:
        with op.batch_alter_table("graph_entities") as batch:
            batch.create_foreign_key(
                "fk_graph_entities_merged_into", "graph_entities",
                ["merged_into"], ["id"], ondelete="CASCADE",
            )
    op.create_index("ix_graph_entities_merged_into", "graph_entities", ["merged_into"])

    if op.get_bind().dialect.name == "postgresql":
        # _clear_auto_layer 按 properties->>'source' 过滤，无索引时是全表扫描
        # （graph_relations 67 万行级别）。表达式索引仅 PG 需要。
        op.create_index(
            "ix_graph_entities_source_prop", "graph_entities",
            [sa.text("((properties->>'source'))")],
            unique=False,
        )

    op.create_index(
        "uq_graph_entities_kb_name", "graph_entities", ["kb_id", "name"],
        unique=True,
        postgresql_where=sa.text("merged_into IS NULL"),
        sqlite_where=sa.text("merged_into IS NULL"),
    )

    op.create_table(
        "kg_extraction_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kb_id", sa.Uuid(),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="llm"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("params", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("total_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entities_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relations_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_kg_extraction_jobs_kb_id", "kg_extraction_jobs", ["kb_id"])
    op.create_index("ix_kg_extraction_jobs_status", "kg_extraction_jobs", ["status"])

    op.create_table(
        "kg_unit_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kb_id", sa.Uuid(),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("chunk_id", sa.Uuid(),
                  sa.ForeignKey("kb_chunks.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("kb_id", "chunk_id", "content_hash", name="uq_kg_unit_result"),
    )
    op.create_index("ix_kg_unit_results_kb_id", "kg_unit_results", ["kb_id"])
    op.create_index("ix_kg_unit_results_content_hash", "kg_unit_results", ["content_hash"])

    op.create_table(
        "kg_merge_suggestions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kb_id", sa.Uuid(),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("method", sa.String(16), nullable=False, server_default="auto"),
        sa.Column("entity_a_id", sa.Uuid(),
                  sa.ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("entity_b_id", sa.Uuid(),
                  sa.ForeignKey("graph_entities.id", ondelete="CASCADE"), nullable=True),
        sa.Column("canonical_name", sa.String(256), nullable=True),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("apply_record", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_kg_merge_suggestions_kb_id", "kg_merge_suggestions", ["kb_id"])
    op.create_index("ix_kg_merge_suggestions_status", "kg_merge_suggestions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_kg_merge_suggestions_status", table_name="kg_merge_suggestions")
    op.drop_index("ix_kg_merge_suggestions_kb_id", table_name="kg_merge_suggestions")
    op.drop_table("kg_merge_suggestions")
    op.drop_index("ix_kg_unit_results_content_hash", table_name="kg_unit_results")
    op.drop_index("ix_kg_unit_results_kb_id", table_name="kg_unit_results")
    op.drop_table("kg_unit_results")
    op.drop_index("ix_kg_extraction_jobs_kb_id", table_name="kg_extraction_jobs")
    op.drop_table("kg_extraction_jobs")
    op.drop_index("uq_graph_entities_kb_name", table_name="graph_entities")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_graph_entities_source_prop", table_name="graph_entities")
    op.drop_index("ix_graph_entities_merged_into", table_name="graph_entities")
    # SQLite 不支持裸 ALTER 约束——与 upgrade 的 batch 形态对称（CI 首跑
    # 2026-11-23：裸 drop_constraint 使所有降级扫描用例在 SQLite 全灭）。
    with op.batch_alter_table("graph_entities") as batch:
        batch.drop_constraint("fk_graph_entities_merged_into", type_="foreignkey")
    op.drop_column("graph_entities", "aliases")
    op.drop_column("graph_entities", "merged_into")
    op.drop_column("knowledge_bases", "kg_ontology")
