"""S1 审计哈希链（E10/D14）：两表 append 成链、校验定位断点、三写入分支挂接。

验收口径（路线 B2-08 增补 E10 + 技术方案 §5.3 口径 6）：篡改任一张审计表的
事件都能被校验端点定位断点；正常写入校验通过；存量 NULL 行计 unchained 不算断点。
"""
import unittest
import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.access import AuditEvent
from app.models.platform_audit import PlatformAuditEvent
from app.models.project import Project
from app.models.user import User
from app.services.audit import AuditIntent, AuditService
from app.services.audit_chain import append, verify, verify_all
from app.services.project_access import ProjectRole
from app.services.platform_audit import (
    PlatformAuditIntent,
    record_failed_platform_event,
    record_platform_event,
)


def _fake_request():
    return SimpleNamespace(state=SimpleNamespace(request_id=uuid.uuid4()), client=None)


class AuditChainCase(unittest.TestCase):
    """内存 SQLite + 全量建表；append/verify 与两写入服务共库。"""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as db:
            self.user = User(username=f"chain-{uuid.uuid4().hex[:8]}", password_hash="hash")
            db.add(self.user)
            db.flush()
            self.project = Project(name="Audit chain", owner_id=self.user.id)
            db.add(self.project)
            db.commit()

    def _chain_audit_event(self, action="quality.alert.close", result="success"):
        event = AuditEvent(
            project_id=self.project.id, actor_id=self.user.id,
            actor_username=self.user.username, action=action,
            resource_type="quality_alert", resource_id=str(uuid.uuid4()),
            result=result, request_id=uuid.uuid4(), changes={"status": "closed"},
        )
        with self.session_factory() as db:
            append(db, "audit_events", event)
            db.add(event)
            db.commit()
        return event

    def _chain_platform_event(self, action="auth.login"):
        event = PlatformAuditEvent(
            actor_id=self.user.id, actor_username=self.user.username,
            action=action, resource_type="session", resource_id=None,
            result="success", request_id=uuid.uuid4(), changes={},
        )
        with self.session_factory() as db:
            append(db, "platform_audit_events", event)
            db.add(event)
            db.commit()
        return event


class TestAppendAndVerify(AuditChainCase):
    def test_sequential_appends_form_a_complete_chain(self):
        first = self._chain_audit_event()
        second = self._chain_audit_event()
        third = self._chain_audit_event()
        self.assertEqual([first.chain_seq, second.chain_seq, third.chain_seq], [1, 2, 3])
        self.assertIsNone(first.prev_hash)
        self.assertEqual(second.prev_hash, first.entry_hash)
        self.assertEqual(third.prev_hash, second.entry_hash)
        with self.session_factory() as db:
            report = verify(db, "audit_events")
        self.assertTrue(report["complete"])
        self.assertIsNone(report["first_break"])
        self.assertEqual(report["chained"], 3)

    def test_platform_table_chains_independently(self):
        a = self._chain_platform_event()
        b = self._chain_platform_event(action="auth.logout")
        self.assertEqual([a.chain_seq, b.chain_seq], [1, 2])
        with self.session_factory() as db:
            report = verify(db, "platform_audit_events")
        self.assertTrue(report["complete"])
        self.assertEqual(report["chained"], 2)

    def test_append_is_idempotent_for_already_chained_event(self):
        event = self._chain_audit_event()
        with self.session_factory() as db:
            append(db, "audit_events", event)
        self.assertEqual(event.chain_seq, 1)

    def test_unknown_table_is_rejected(self):
        with self.session_factory() as db:
            with self.assertRaises(ValueError):
                append(db, "quality_alerts", SimpleNamespace(entry_hash=None))

    def test_pre_chain_rows_count_as_unchained_not_breaks(self):
        # 迁移前史：链列全 NULL 的行不算断点（历史记录不回填）
        with self.session_factory() as db:
            db.add(AuditEvent(
                project_id=self.project.id, actor_id=self.user.id,
                actor_username="legacy", action="legacy.action",
                resource_type="legacy", resource_id=None, result="success",
                request_id=uuid.uuid4(), changes={},
            ))
            db.commit()
        self._chain_audit_event()
        with self.session_factory() as db:
            report = verify(db, "audit_events")
        self.assertTrue(report["complete"])
        self.assertEqual(report["unchained"], 1)
        self.assertEqual(report["chained"], 1)

    def test_tampered_action_is_located_as_hash_mismatch(self):
        self._chain_audit_event()
        second = self._chain_audit_event()
        self._chain_audit_event()
        # 篡改中间行（绕过 ORM 直改，模拟审厂防篡改场景）
        with self.session_factory() as db:
            db.execute(
                AuditEvent.__table__.update()
                .where(AuditEvent.id == second.id)
                .values(action="forged.action")
            )
            db.commit()
        with self.session_factory() as db:
            report = verify(db, "audit_events")
        self.assertFalse(report["complete"])
        self.assertEqual(report["first_break"]["seq"], 2)
        self.assertEqual(report["first_break"]["reason"], "hash_mismatch")
        self.assertEqual(report["first_break"]["id"], str(second.id))

    def test_broken_link_is_located(self):
        self._chain_audit_event()
        second = self._chain_audit_event()
        with self.session_factory() as db:
            db.execute(
                AuditEvent.__table__.update()
                .where(AuditEvent.id == second.id)
                .values(prev_hash="0" * 64)
            )
            db.commit()
        with self.session_factory() as db:
            report = verify(db, "audit_events")
        self.assertFalse(report["complete"])
        self.assertEqual(report["first_break"]["seq"], 2)
        self.assertEqual(report["first_break"]["reason"], "link_mismatch")

    def test_verify_all_covers_both_tables(self):
        self._chain_audit_event()
        self._chain_platform_event()
        with self.session_factory() as db:
            report = verify_all(db)
        self.assertEqual(sorted(report), ["audit_events", "platform_audit_events"])
        self.assertTrue(all(item["complete"] for item in report.values()))


class TestWriterHooks(AuditChainCase):
    def test_project_action_success_appends_chain(self):
        service = AuditService(self.session_factory)
        access = SimpleNamespace(role=ProjectRole.OWNER)
        with self.session_factory() as db:
            with service.project_action(
                db, request=_fake_request(), actor=self.user, access=access,
                permission="project.read",
                intent=AuditIntent(
                    project_id=self.project.id, action="approval.create",
                    resource_type="approval_request", resource_id="x",
                    changes={"title": "t"},
                ),
                allowed_changes={"title"},
            ):
                pass
            report = verify(db, "audit_events")
            row = db.execute(
                AuditEvent.__table__.select().where(AuditEvent.action == "approval.create")
            ).one()
        self.assertTrue(report["complete"])
        self.assertEqual(report["chained"], 1)
        self.assertEqual(row.changes, {"title": "t"})

    def test_project_action_denied_appends_chain(self):
        service = AuditService(self.session_factory)
        access = SimpleNamespace(role=ProjectRole.VIEWER)
        with self.session_factory() as db:
            with self.assertRaises(Exception):
                with service.project_action(
                    db, request=_fake_request(), actor=self.user, access=access,
                    permission="model.approve",
                    intent=AuditIntent(
                        project_id=self.project.id, action="model.approve",
                        resource_type="model_version", changes={},
                    ),
                    allowed_changes=set(),
                ):
                    pass
            report = verify(db, "audit_events")
            row = db.execute(
                AuditEvent.__table__.select().where(AuditEvent.result == "denied")
            ).one()
        self.assertTrue(report["complete"])
        self.assertEqual(row.error_code, "PROJECT_PERMISSION_DENIED")

    def test_project_action_failed_records_chained_failed_event(self):
        service = AuditService(self.session_factory)
        access = SimpleNamespace(role=ProjectRole.OWNER)

        class Boom(RuntimeError):
            code = "TEST_EXPLODED"

        with self.session_factory() as db:
            with self.assertRaises(Boom):
                with service.project_action(
                    db, request=_fake_request(), actor=self.user, access=access,
                    permission="project.read",
                    intent=AuditIntent(
                        project_id=self.project.id, action="quality.alert.close",
                        resource_type="quality_alert", changes={},
                    ),
                    allowed_changes=set(),
                ):
                    raise Boom("x")
        with self.session_factory() as db:
            report = verify(db, "audit_events")
            row = db.execute(
                AuditEvent.__table__.select().where(AuditEvent.result == "failed")
            ).one()
        self.assertTrue(report["complete"])
        self.assertEqual(row.error_code, "TEST_EXPLODED")

    def test_platform_event_helpers_append_chain(self):
        with self.session_factory() as db:
            record_platform_event(
                db, actor=self.user, request=_fake_request(),
                intent=PlatformAuditIntent(
                    action="auth.login", resource_type="session", changes={"mfa": False},
                ),
                result="success",
            )
            db.commit()
        with self.session_factory() as db:
            record_failed_platform_event(
                db, actor=self.user, request=_fake_request(),
                intent=PlatformAuditIntent(action="auth.login", resource_type="session"),
                error_code="AUTH_INVALID_CREDENTIALS",
            )
        with self.session_factory() as db:
            report = verify(db, "platform_audit_events")
            results = db.execute(
                PlatformAuditEvent.__table__.select().order_by(PlatformAuditEvent.chain_seq)
            ).all()
        self.assertTrue(report["complete"])
        self.assertEqual(report["chained"], 2)
        self.assertEqual([row.result for row in results], ["success", "failed"])


class TestVerifyEndpoint(AuditChainCase):
    def test_admin_verify_endpoint_returns_both_tables(self):
        from app.api.agent_audit import router as agent_audit_router
        from app.api.users import get_current_admin
        from app.database import get_db

        self._chain_audit_event()
        self._chain_platform_event()
        app = FastAPI()
        app.include_router(agent_audit_router)

        def _override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_admin] = lambda: self.user
        client = TestClient(app)
        response = client.get("/api/admin/audit-chain/verify")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(sorted(payload), ["audit_events", "platform_audit_events"])
        self.assertTrue(payload["audit_events"]["complete"])
        self.assertTrue(payload["platform_audit_events"]["complete"])


if __name__ == "__main__":
    unittest.main()
