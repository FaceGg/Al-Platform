"""补齐路线第二批迁移合同（_113）：S1 审批队列 + 动作审计 + 审计哈希链。

迁移内容（技术方案-补齐路线第二批 §1 R0，D4/D11/D14/D18）：
- 两张审计表各加哈希链三列（nullable；存量行 NULL=链前史）；
- audit_chain_state / agent_action_audits / approval_requests 三新表。
本地在 SQLite 上跑；PostgreSQL 的往返由 CI 生产集成作业背书。
"""
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.config import settings
from app.models.access import AuditEvent
from app.models.platform_audit import PlatformAuditEvent
from app.models.project import Project
from app.models.user import User

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
PRE_S1_REVISION = "20261126_112"
S1_REVISION = "20261126_113"
S1_NEW_TABLES = ("audit_chain_state", "agent_action_audits", "approval_requests")
CHAIN_COLUMNS = ("chain_seq", "prev_hash", "entry_hash")


class TestGapBatch2Migrations(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.original_database_url = settings.database_url
        self.db_path = os.path.join(self.temporary.name, "gap_batch2.db").replace("\\", "/")
        settings.database_url = f"sqlite:///{self.db_path}"
        self.config = Config(str(ALEMBIC_INI))
        self.engine = sa.create_engine(f"sqlite:///{self.db_path}")

    def tearDown(self):
        self.engine.dispose()
        settings.database_url = self.original_database_url
        self.temporary.cleanup()

    def _column_names(self, engine, table):
        return {column["name"] for column in sa.inspect(engine).get_columns(table)}

    def test_s1_migration_is_single_head_chained_on_batch1(self):
        script = ScriptDirectory.from_config(self.config)
        # 单头不变式 + 本批迁移链（后续批次追加不随批改常量）
        self.assertEqual(len(script.get_heads()), 1, script.get_heads())
        by_id = {revision.revision: revision for revision in script.walk_revisions()}
        self.assertEqual(by_id[S1_REVISION].down_revision, PRE_S1_REVISION)

    def test_fresh_upgrade_creates_s1_objects_and_matches_models(self):
        command.upgrade(self.config, "head")
        inspector = sa.inspect(self.engine)
        self.assertTrue(set(S1_NEW_TABLES).issubset(set(inspector.get_table_names())))
        for table in ("audit_events", "platform_audit_events"):
            with self.subTest(table=table):
                self.assertTrue(set(CHAIN_COLUMNS).issubset(self._column_names(self.engine, table)))
        checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("approval_requests")
        }
        self.assertTrue(
            {"ck_approval_requests_type", "ck_approval_requests_status", "ck_approval_requests_execution_status"}
            .issubset(checks)
        )
        unique_names = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("agent_action_audits")
        }
        self.assertIn("uq_agent_action_audits_idempotency_key", unique_names)
        # 模型与迁移零漂移
        command.check(self.config)

    def test_downgrade_then_upgrade_preserves_audit_rows(self):
        """两张既有审计表的行跨 _113 降级原样保留；新表数据随降级丢弃属预期。"""
        command.upgrade(self.config, "head")
        from sqlalchemy.orm import sessionmaker

        session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with session_factory() as db:
            user = User(username=f"gap-batch2-{uuid.uuid4().hex[:8]}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Gap batch 2 retention", owner_id=user.id)
            db.add(project)
            db.flush()
            project_audit = AuditEvent(
                project_id=project.id, actor_id=user.id, actor_username=user.username,
                action="approval.create", resource_type="approval_request",
                resource_id=str(uuid.uuid4()), result="success",
                request_id=uuid.uuid4(), changes={},
            )
            platform_audit = PlatformAuditEvent(
                actor_id=user.id, actor_username=user.username,
                action="auth.login", resource_type="session",
                resource_id=None, result="success",
                request_id=uuid.uuid4(), changes={},
            )
            db.add_all([project_audit, platform_audit])
            db.commit()
            project_audit_id, platform_audit_id = project_audit.id, platform_audit.id

        # 定向降级到批前：链列移除、三新表移除，两张审计表行保留
        command.downgrade(self.config, PRE_S1_REVISION)
        tables = set(sa.inspect(self.engine).get_table_names())
        self.assertTrue(set(S1_NEW_TABLES).isdisjoint(tables))
        for table in ("audit_events", "platform_audit_events"):
            with self.subTest(table=table):
                self.assertFalse(set(CHAIN_COLUMNS) & self._column_names(self.engine, table))
        with session_factory() as db:
            # 降级态读法：只选核心列（ORM 实体会选已删除的链列）
            kept_project = db.execute(
                sa.select(AuditEvent.action, AuditEvent.result).where(AuditEvent.id == project_audit_id)
            ).one()
            self.assertEqual(kept_project[0], "approval.create")
            kept_platform = db.execute(
                sa.select(PlatformAuditEvent.action).where(PlatformAuditEvent.id == platform_audit_id)
            ).one()
            self.assertEqual(kept_platform[0], "auth.login")

        # 再次升级：审计行仍在且链列为空（链前史口径）
        command.upgrade(self.config, "head")
        command.check(self.config)
        with session_factory() as db:
            audit_row = db.get(AuditEvent, project_audit_id)
            self.assertEqual(audit_row.action, "approval.create")
            self.assertIsNone(audit_row.chain_seq)
            self.assertIsNone(audit_row.entry_hash)
            platform_row = db.get(PlatformAuditEvent, platform_audit_id)
            self.assertIsNotNone(platform_row)

    def test_approval_and_action_audit_tables_accept_contract_rows(self):
        """新表能按 ORM 合同落行：CHECK/UNIQUE/默认值与模型一致。"""
        command.upgrade(self.config, "head")
        from sqlalchemy.orm import sessionmaker

        from app.models.agent_audit import AgentActionAudit, AuditChainState
        from app.models.approvals import ApprovalRequest

        session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        expires = datetime.utcnow() + timedelta(hours=72)
        with session_factory() as db:
            user = User(username=f"gap-s1-{uuid.uuid4().hex[:8]}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Gap S1 contract", owner_id=user.id)
            db.add(project)
            db.flush()
            approval = ApprovalRequest(
                project_id=project.id, type="retrain_proposal", title="S1 合同行",
                payload={"report_id": str(uuid.uuid4())},
                payload_fingerprint="a" * 64, created_by_id=user.id,
                expires_at=expires,
            )
            db.add(approval)
            db.flush()
            action = AgentActionAudit(
                agent_type="chat", status="success", duration_ms=120,
                request_payload={"prompt": "hi"}, response_payload={"text": "yo"},
                usage={"total_tokens": 12}, idempotency_key=f"idem-{uuid.uuid4().hex[:12]}",
            )
            db.add(action)
            db.add(AuditChainState(table_name="audit_events", last_seq=0, last_hash=None))
            db.commit()
            approval_id, action_id = approval.id, action.id

        with session_factory() as db:
            approval_row = db.get(ApprovalRequest, approval_id)
            self.assertEqual(approval_row.status, "pending")
            self.assertEqual(approval_row.execution_status, "none")
            self.assertTrue(approval_row.trace_id)
            action_row = db.get(AgentActionAudit, action_id)
            self.assertEqual(action_row.repeat_count, 0)

    def test_s2a_split_round_tables_upgrade_and_downgrade(self):
        """_114（S2a）：划分/成员/轮次/台账四新表；降级移除、既有表不动。"""
        command.upgrade(self.config, "head")
        tables = set(sa.inspect(self.engine).get_table_names())
        self.assertTrue(
            {"dataset_splits", "dataset_split_members", "modeling_rounds", "blind_test_usages"}
            .issubset(tables)
        )
        checks = {
            constraint["name"]
            for constraint in sa.inspect(self.engine).get_check_constraints("dataset_splits")
        }
        self.assertIn("ck_dataset_splits_strategy", checks)
        uniques = {
            constraint["name"]
            for constraint in sa.inspect(self.engine).get_unique_constraints("dataset_split_members")
        }
        self.assertIn("uq_split_members_row", uniques)
        command.downgrade(self.config, PRE_S1_REVISION)
        tables_after = set(sa.inspect(self.engine).get_table_names())
        self.assertTrue(
            {"dataset_splits", "dataset_split_members", "modeling_rounds", "blind_test_usages"}
            .isdisjoint(tables_after)
        )
        command.upgrade(self.config, "head")
        command.check(self.config)


if __name__ == "__main__":
    unittest.main()
