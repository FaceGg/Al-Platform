# -*- coding: utf-8 -*-
"""Open API keys & ingest events (B1-13 / B1-07, F5).

补齐路线第一批 F5（技术方案 §9A，D43–D53）：
- inference_api_keys 加 project_id（项目级只读 Key 归属）与 grace_until（轮换宽限期），
  归属互斥 CHECK；既有部署级 Key 的 deployment_id 全部非空，CHECK 天然满足；
- ingest_events：事件接入契约的落库层（幂等去重、同键不同内容可追查、重放位置）。

全部为加列/新建，不动数据。SQLite batch；PG 原生 ALTER。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261126_112"
down_revision = "20261126_111"
branch_labels = None
depends_on = None


def _constraint_names(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    names: set = set()
    for kind in ("check_constraints", "foreign_keys", "unique_constraints"):
        for constraint in getattr(inspector, f"get_{kind}")(table):
            names.add(constraint.get("name"))
    return names


def _index_names(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table)}


def _table_names() -> set:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    with op.batch_alter_table("inference_api_keys") as batch:
        # 项目级 Key 的 deployment_id 为空（D43 互斥口径）：列改 nullable——
        # ORM 已同步改，漏改会被 alembic check 漂移门禁拦下
        batch.alter_column(
            "deployment_id", existing_type=sa.Uuid(), nullable=True,
        )
        batch.add_column(sa.Column("project_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("grace_until", sa.DateTime(), nullable=True))
        batch.create_check_constraint(
            "ck_inference_api_keys_owner_exclusive",
            "(deployment_id IS NOT NULL) <> (project_id IS NOT NULL)",
        )
        batch.create_index("ix_inference_api_keys_project_id", ["project_id"])
        # 显式命名 FK（不用 Column 内嵌——匿名 FK 在降级的 batch 重建时无法按名处理）
        batch.create_foreign_key(
            "fk_inference_api_keys_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.create_table(
        "ingest_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("topic", sa.String(128), nullable=True),
        sa.Column("partition", sa.Integer(), nullable=True),
        sa.Column("offset", sa.Integer(), nullable=True),
        sa.Column("business_event_id", sa.String(128), nullable=False),
        sa.Column("station", sa.String(128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("latency_seconds", sa.Integer(), nullable=True),
        sa.Column("payload_version", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reject_reason", sa.String(256), nullable=True),
        sa.Column("ingest_batch_id", sa.Uuid(), nullable=True),
        sa.Column("received_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "source", "business_event_id",
            name="uq_ingest_events_source_business_id",
        ),
        sa.CheckConstraint(
            "status IN ('accepted', 'rejected', 'duplicate')",
            name="ck_ingest_events_status",
        ),
    )
    op.create_index(
        "ix_ingest_events_project_id", "ingest_events", ["project_id"]
    )
    op.create_index(
        "ix_ingest_events_topic_partition_offset", "ingest_events",
        ["topic", "partition", "offset"],
    )
    op.create_index(
        "ix_ingest_events_source_received", "ingest_events",
        ["source", "received_at"],
    )

    # 旧数据保留断言：Key 表 CHECK 就位（存量行 deployment 非空、project 为空，天然满足）；
    # 新表存在；索引就位。
    assert "ck_inference_api_keys_owner_exclusive" in _constraint_names("inference_api_keys")
    assert "ix_inference_api_keys_project_id" in _index_names("inference_api_keys")
    assert "ingest_events" in _table_names()
    assert "ix_ingest_events_source_received" in _index_names("ingest_events")


def downgrade() -> None:
    op.drop_index("ix_ingest_events_source_received", table_name="ingest_events")
    op.drop_index("ix_ingest_events_topic_partition_offset", table_name="ingest_events")
    op.drop_index("ix_ingest_events_project_id", table_name="ingest_events")
    op.drop_table("ingest_events")
    # 反射得到的外键在 SQLite 下没有名字：只给 fk 定义命名规则——已有 CHECK/UNIQUE
    # 有自己的名字，给它们定规则反而会重命名导致按原名找不到（先例 20261126_109 只留 fk）
    with op.batch_alter_table(
        "inference_api_keys",
        naming_convention={
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        },
    ) as batch:
        batch.drop_index("ix_inference_api_keys_project_id")
        batch.drop_constraint(
            "fk_inference_api_keys_project_id_projects", type_="foreignkey"
        )
        batch.drop_constraint("ck_inference_api_keys_owner_exclusive", type_="check")
        batch.drop_column("grace_until")
        batch.drop_column("project_id")
        # 降级时存量 Key 全是部署级（project 全空），deployment_id 恢复 NOT NULL
        batch.alter_column(
            "deployment_id", existing_type=sa.Uuid(), nullable=False,
        )
