"""补齐路线第一批迁移合同（_105–_108）：全新升级、定向降级、旧数据保留、单一头。

迁移内容：_105 质量领域三新表 + edge_devices 影子两列；_106 推理结果明细两表；
_107 外部数据源表 + 场景绑定列；_108 通知端点 kind CHECK 约束重建。
本地在 SQLite 上跑；PostgreSQL 的往返由 CI 生产集成作业（alembic upgrade /
current / check）背书。外键强制语义由 test_quality_domain 等用例覆盖，本模块
只验证结构往返与数据保留。
"""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.compute import EdgeDevice
from app.models.notifications import NotificationEndpoint
from app.models.project import Project
from app.models.user import User

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
PRE_BATCH_REVISION = "20261120_104"
BATCH_HEAD_REVISION = "20261125_108"
BATCH_CHAIN = (
    "20261125_108",
    "20261125_107",
    "20261125_106",
    "20261125_105",
    "20261120_104",
)

NEW_TABLES = (
    "quality_scenes",
    "quality_stations",
    "quality_spec_limits",
    "inference_results",
    "inference_result_buckets",
    "external_data_sources",
)


def device_name_of(session, row_id):
    """降级态读法：只选 name 列（ORM 实体读取会去选已随降级删除的影子列）。"""
    return session.scalar(sa.select(EdgeDevice.name).where(EdgeDevice.id == row_id))


def endpoint_name_of(session, row_id):
    return session.scalar(sa.select(NotificationEndpoint.name).where(NotificationEndpoint.id == row_id))


class TestGapBatch1Migrations(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.original_database_url = settings.database_url
        self.db_path = os.path.join(self.temporary.name, "gap_batch1.db").replace("\\", "/")
        settings.database_url = f"sqlite:///{self.db_path}"
        self.config = Config(str(ALEMBIC_INI))
        self.engine = sa.create_engine(f"sqlite:///{self.db_path}")

    def tearDown(self):
        self.engine.dispose()
        settings.database_url = self.original_database_url
        self.temporary.cleanup()

    def _engine_for(self, name):
        return sa.create_engine("sqlite:///" + os.path.join(self.temporary.name, name).replace("\\", "/"))

    def _column_names(self, engine, table):
        return {column["name"] for column in sa.inspect(engine).get_columns(table)}

    def _batch_schema(self, engine):
        """六张新表的 (表, 列) 集合——逐步升级与一步到 head 的等价性比较用。"""
        return {
            (table, column["name"])
            for table in NEW_TABLES
            for column in sa.inspect(engine).get_columns(table)
        }

    def test_migrations_form_a_single_linear_chain(self):
        script = ScriptDirectory.from_config(self.config)
        self.assertEqual(script.get_heads(), [BATCH_HEAD_REVISION])
        by_id = {revision.revision: revision for revision in script.walk_revisions()}
        for newer, older in zip(BATCH_CHAIN, BATCH_CHAIN[1:]):
            with self.subTest(newer=newer):
                self.assertEqual(by_id[newer].down_revision, older)

    def test_fresh_upgrade_creates_batch_objects_and_matches_models(self):
        command.upgrade(self.config, "head")
        inspector = sa.inspect(self.engine)
        self.assertTrue(set(NEW_TABLES).issubset(set(inspector.get_table_names())))
        self.assertTrue(
            {"shadow_desired", "shadow_reported"}.issubset(self._column_names(self.engine, "edge_devices"))
        )
        self.assertIn("data_source_id", self._column_names(self.engine, "quality_scenes"))
        # 保留期清理与查询路径依赖的索引
        result_indexes = {index["name"] for index in inspector.get_indexes("inference_results")}
        self.assertTrue(
            {"ix_inference_results_expires", "ix_inference_results_sample_key"}.issubset(result_indexes)
        )
        bucket_indexes = {index["name"] for index in inspector.get_indexes("inference_result_buckets")}
        self.assertIn("ix_inference_result_buckets_bucket", bucket_indexes)
        # 模型与迁移零漂移
        command.check(self.config)

    def test_notification_kind_constraint_covers_new_channels(self):
        command.upgrade(self.config, "head")
        checks = [
            constraint["sqltext"]
            for constraint in sa.inspect(self.engine).get_check_constraints("notification_endpoints")
            if constraint["name"] == "ck_notification_endpoint_kind"
        ]
        self.assertEqual(len(checks), 1)
        for kind in ("in_app", "wecom", "email", "webhook", "dingtalk", "sms_gateway"):
            with self.subTest(kind=kind):
                self.assertIn(f"'{kind}'", checks[0])

    def test_downgrade_then_upgrade_preserves_existing_rows(self):
        command.upgrade(self.config, "head")
        session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with session_factory() as db:
            user = User(username=f"gap-batch1-{uuid.uuid4().hex[:8]}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Gap batch 1 retention", owner_id=user.id)
            db.add(project)
            db.flush()
            device = EdgeDevice(
                name="retained-device", owner_id=user.id,
                shadow_desired={"state": "a"}, shadow_reported={"state": "b"},
            )
            db.add(device)
            db.flush()
            endpoint = NotificationEndpoint(
                project_id=project.id, kind="webhook", name="retained-endpoint",
                destination_hint="retained.example.invalid",
                encrypted_config="cipher-blob", created_by_id=user.id,
            )
            db.add(endpoint)
            db.commit()
            device_id, endpoint_id = device.id, endpoint.id

        # 定向降级到批前：新表与新增列移除，既有表的行原样保留
        command.downgrade(self.config, PRE_BATCH_REVISION)
        self.assertTrue(set(NEW_TABLES).isdisjoint(set(sa.inspect(self.engine).get_table_names())))
        self.assertNotIn("shadow_desired", self._column_names(self.engine, "edge_devices"))
        with session_factory() as db:
            self.assertEqual(device_name_of(db, device_id), "retained-device")
            self.assertEqual(endpoint_name_of(db, endpoint_id), "retained-endpoint")

        # 再次升级：行仍在、业务字段不变，新增列可读（影子列数据随降级丢弃，为空）
        command.upgrade(self.config, "head")
        command.check(self.config)
        with session_factory() as db:
            device = db.get(EdgeDevice, device_id)
            endpoint = db.get(NotificationEndpoint, endpoint_id)
            self.assertEqual(device.name, "retained-device")
            self.assertIsNone(device.shadow_desired)
            self.assertIsNone(device.shadow_reported)
            self.assertEqual(endpoint.kind, "webhook")
            self.assertEqual(endpoint.encrypted_config, "cipher-blob")

    def test_upgrade_one_step_at_a_time_is_equivalent_to_head(self):
        """逐个迁移升级与一步到 head 等价（批内相邻迁移可独立执行）。"""
        for revision in ("20261125_105", "20261125_106", "20261125_107", "20261125_108"):
            command.upgrade(self.config, revision)
        command.check(self.config)
        stepwise = self._batch_schema(self.engine)
        self.assertEqual(len({table for table, _ in stepwise}), len(NEW_TABLES))

        other_engine = self._engine_for("direct.db")
        try:
            settings.database_url = f"sqlite:///{self.temporary.name}/direct.db".replace("\\", "/")
            command.upgrade(self.config, "head")
            direct = self._batch_schema(other_engine)
        finally:
            settings.database_url = f"sqlite:///{self.db_path}"
            other_engine.dispose()
        self.assertEqual(stepwise, direct)


if __name__ == "__main__":
    unittest.main()
