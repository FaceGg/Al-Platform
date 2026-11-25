# -*- coding: utf-8 -*-
"""External data sources (B1-08) + quality scene datasource binding column.

补齐路线第一批 F1（技术方案 §4）：
- external_data_sources 表：只读外部数据库直连（口令 Fernet 密文，
  独立 datasource_master_key）；SQL 白名单由 sqlglot 语法解析执行。
- quality_scenes.data_source_id：场景绑定外部数据源（建表与外键同迁移）。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261125_107"
down_revision = "20261125_106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_data_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("db_type", sa.String(16), nullable=False),
        sa.Column("host", sa.String(256), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database", sa.String(128), nullable=False),
        sa.Column("username", sa.String(128), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("ssl_mode", sa.String(16), nullable=False, server_default="prefer"),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column(
            "created_by_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_external_data_sources_project_name",
        ),
        sa.CheckConstraint(
            "db_type IN ('postgresql', 'mysql')",
            name="ck_external_data_sources_db_type",
        ),
    )
    op.create_index(
        "ix_external_data_sources_project_id",
        "external_data_sources",
        ["project_id"],
    )

    with op.batch_alter_table("quality_scenes") as batch:
        batch.add_column(sa.Column("data_source_id", sa.Uuid(), nullable=True))
    # SQLite 不支持裸 ALTER 约束——batch 形态（先例 20261120_103）；PG 走原生
    if op.get_bind().dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_quality_scenes_data_source",
            "quality_scenes",
            "external_data_sources",
            ["data_source_id"],
            ["id"],
            ondelete="SET NULL",
        )
    else:
        with op.batch_alter_table("quality_scenes") as batch:
            batch.create_foreign_key(
                "fk_quality_scenes_data_source",
                "external_data_sources",
                ["data_source_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    # 与 upgrade 的形态对称：SQLite 裸 drop_constraint 使降级在测试库全灭
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "fk_quality_scenes_data_source",
            "quality_scenes",
            type_="foreignkey",
        )
    else:
        with op.batch_alter_table("quality_scenes") as batch:
            batch.drop_constraint("fk_quality_scenes_data_source", type_="foreignkey")
    with op.batch_alter_table("quality_scenes") as batch:
        batch.drop_column("data_source_id")
    op.drop_index(
        "ix_external_data_sources_project_id", table_name="external_data_sources",
    )
    op.drop_table("external_data_sources")
