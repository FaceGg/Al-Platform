"""S1 统一四眼审批中心（B2-07/B2-10）：四眼、过期回收+提醒、指纹失效、
水位线、执行器接线、存量投影、pending-count。

验收口径（技术方案 §5.3）：审批人=发起人路径被拒；72h 过期自动回收；
过期前 12h 提醒一次；拒绝必附意见；E05 水位线与 E06 指纹各有单测。
"""
import unittest
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.access import ProjectMember
from app.models.approvals import ApprovalRequest
from app.models.inference_result import InferenceResult
from app.models.project import Project
from app.models.quality_alerts import QualityAlert
from app.models.user import User
from app.services.approvals import (
    ApprovalError,
    create_approval,
    decide_approval,
    sweep_expiries,
)


class ApprovalCenterCase(unittest.TestCase):
    """owner=发起人 / editor_b=审批人（跨人）/ operator=运营（可发起 disposition）。"""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as db:
            self.owner = User(username=f"owner-{uuid.uuid4().hex[:6]}", password_hash="hash")
            self.editor_b = User(username=f"editor-b-{uuid.uuid4().hex[:6]}", password_hash="hash")
            self.operator = User(username=f"operator-{uuid.uuid4().hex[:6]}", password_hash="hash")
            db.add_all([self.owner, self.editor_b, self.operator])
            db.flush()
            self.project = Project(name="审批中心", owner_id=self.owner.id)
            db.add(self.project)
            db.flush()
            db.add_all([
                ProjectMember(project_id=self.project.id, user_id=self.editor_b.id, role="editor"),
                ProjectMember(project_id=self.project.id, user_id=self.operator.id, role="operator"),
            ])
            db.commit()

    def _create(self, approval_type="recipe_change", payload=None, initiator=None, db=None, ttl_hours=None):
        """默认用 recipe_change 加严形态（validate_create 只要求 plan 存在）
        测队列机械性——〔第三轮复审 2026-11-28〕recipe_change 已注册执行器
        （wave1 5dc6baea），空 payload 会被 QMS_SYNC_TARGET_NOT_FOUND 拒绝，
        故默认造一条 active 控制计划；disposition/retrain 专项测试显式传
        type+payload。"""
        own = db is None
        db = db or self.session_factory()
        kwargs = {}
        if ttl_hours is not None:
            kwargs["ttl_hours"] = ttl_hours
        if approval_type == "recipe_change" and not payload:
            from app.models.qms import QmsControlPlan

            db.add(QmsControlPlan(
                project_id=self.project.id,
                code=f"PL-{uuid.uuid4().hex[:8]}",
                version=1, status="active",
                quality_points=[], tightening_multiplier=1.0,
                decision_log=[], created_by_id=(initiator or self.owner).id,
            ))
            db.flush()
            plan = db.query(QmsControlPlan).filter(
                QmsControlPlan.project_id == self.project.id,
            ).order_by(QmsControlPlan.created_at.desc()).first()
            payload = {"plan_id": str(plan.id), "suggested_multiplier": 1.0}
        try:
            approval = create_approval(
                db,
                project_id=self.project.id,
                approval_type=approval_type,
                title=f"测试审批-{approval_type}",
                payload=payload or {},
                initiator_id=(initiator or self.owner).id,
                **kwargs,
            )
            if own:
                db.commit()
            return approval
        finally:
            if own:
                db.close()

    def _critical_alert(self, status="acknowledged", assignee=None):
        with self.session_factory() as db:
            alert = QualityAlert(
                project_id=self.project.id,
                source_type="model_risk",
                severity="critical",
                title="critical-close-me",
                evidence={},
                merge_key="model_risk",
                status=status,
                assigned_to_id=(assignee or self.operator).id,
            )
            db.add(alert)
            db.commit()
            return alert.id


class TestFourEyes(ApprovalCenterCase):
    def test_self_approval_is_rejected(self):
        approval = self._create(initiator=self.owner)
        with self.session_factory() as db:
            with self.assertRaises(ApprovalError) as caught:
                decide_approval(
                    db, approval_id=approval.id, actor_id=self.owner.id,
                    decision="approve", note="self",
                )
            self.assertEqual(caught.exception.code, "APPROVAL_FOUR_EYES_DENIED")

    def test_cross_person_editor_can_approve(self):
        approval = self._create(initiator=self.owner)
        with self.session_factory() as db:
            decided = decide_approval(
                db, approval_id=approval.id, actor_id=self.editor_b.id,
                decision="approve",
            )
            db.commit()
        self.assertEqual(decided.status, "approved")
        self.assertEqual(decided.decided_by_id, self.editor_b.id)

    def test_rejection_requires_note(self):
        approval = self._create(initiator=self.owner)
        with self.session_factory() as db:
            with self.assertRaises(ApprovalError) as caught:
                decide_approval(
                    db, approval_id=approval.id, actor_id=self.editor_b.id,
                    decision="reject", note="   ",
                )
            self.assertEqual(caught.exception.code, "APPROVAL_REJECTION_NOTE_REQUIRED")
            decided = decide_approval(
                db, approval_id=approval.id, actor_id=self.editor_b.id,
                decision="reject", note="证据链不完整，补充后再提",
            )
            db.commit()
        self.assertEqual(decided.status, "rejected")

    def test_only_pending_can_be_decided(self):
        approval = self._create(initiator=self.owner)
        with self.session_factory() as db:
            decide_approval(
                db, approval_id=approval.id, actor_id=self.editor_b.id,
                decision="reject", note="first",
            )
            db.commit()
            with self.assertRaises(ApprovalError) as caught:
                decide_approval(
                    db, approval_id=approval.id, actor_id=self.owner.id,
                    decision="approve",
                )
            self.assertEqual(caught.exception.code, "APPROVAL_STATE_CONFLICT")


class TestExpiry(ApprovalCenterCase):
    def test_expired_after_ttl_and_reminder_once(self):
        approval = self._create(initiator=self.owner, ttl_hours=72)
        with self.session_factory() as db:
            row = db.get(ApprovalRequest, approval.id)
            # 快进到剩余 6h：提醒一次
            now = row.expires_at - timedelta(hours=6)
            result = sweep_expiries(db, now=now)
            db.commit()
            self.assertEqual(result["reminded"], 1)
            self.assertIsNotNone(db.get(ApprovalRequest, approval.id).reminded_at)
            # 第二次巡检不重复提醒
            result_again = sweep_expiries(db, now=now + timedelta(minutes=1))
            db.commit()
            self.assertEqual(result_again["reminded"], 0)
            # 快进过期：状态迁移 + expired 计数
            result_expired = sweep_expiries(db, now=row.expires_at + timedelta(minutes=1))
            db.commit()
            self.assertEqual(result_expired["expired"], 1)
            self.assertEqual(db.get(ApprovalRequest, approval.id).status, "expired")

    def test_expired_request_cannot_be_approved(self):
        approval = self._create(initiator=self.owner, ttl_hours=1)
        with self.session_factory() as db:
            row = db.get(ApprovalRequest, approval.id)
            sweep_expiries(db, now=row.expires_at + timedelta(minutes=1))
            db.commit()
            with self.assertRaises(ApprovalError) as caught:
                decide_approval(
                    db, approval_id=approval.id, actor_id=self.editor_b.id,
                    decision="approve",
                )
            self.assertEqual(caught.exception.code, "APPROVAL_STATE_CONFLICT")


class TestDispositionExecutor(ApprovalCenterCase):
    def _approval_for_alert(self, alert_id):
        return self._create(
            approval_type="disposition",
            payload={"alert_id": str(alert_id), "resolution": "confirmed_issue"},
            initiator=self.operator,
        )

    def test_create_rejects_open_alert_transition(self):
        alert_id = self._critical_alert(status="open")
        with self.session_factory() as db:
            with self.assertRaises(ApprovalError) as caught:
                create_approval(
                    db, project_id=self.project.id, approval_type="disposition",
                    title="关", payload={"alert_id": str(alert_id)},
                    initiator_id=self.operator.id,
                )
            self.assertEqual(caught.exception.code, "DISPOSITION_TRANSITION_INVALID")

    def test_fingerprint_invalidates_when_alert_moved(self):
        alert_id = self._critical_alert(status="acknowledged")
        approval = self._approval_for_alert(alert_id)
        # 预警在审批期间被他人流转到 processing（状态型指纹不复现）
        with self.session_factory() as db:
            row = db.get(QualityAlert, alert_id)
            row.status = "processing"
            db.commit()
        with self.session_factory() as db:
            decided = decide_approval(
                db, approval_id=approval.id, actor_id=self.editor_b.id,
                decision="approve",
            )
            db.commit()
        self.assertEqual(decided.status, "invalidated")
        self.assertEqual(decided.decision_note, "APPROVAL_FINGERPRINT_MISMATCH")

    def test_approve_closes_alert_via_executor(self):
        alert_id = self._critical_alert(status="acknowledged")
        approval = self._approval_for_alert(alert_id)
        with self.session_factory() as db:
            decided = decide_approval(
                db, approval_id=approval.id, actor_id=self.editor_b.id,
                decision="approve",
            )
            from app.services.approvals import perform_approved

            result = perform_approved(db, approval=decided, actor_id=self.editor_b.id)
            db.commit()
        self.assertEqual(decided.status, "approved")
        self.assertEqual(result["closed"], True)
        with self.session_factory() as db:
            alert = db.get(QualityAlert, alert_id)
            self.assertEqual(alert.status, "closed")
            self.assertEqual(alert.resolution, "confirmed_issue")


class TestRetrainWatermark(ApprovalCenterCase):
    def _deployment_payload(self, extra_results=0, anchor=None):
        deployment_id = uuid.uuid4()
        report_id = uuid.uuid4()
        anchor = anchor or datetime.utcnow() - timedelta(hours=1)
        with self.session_factory() as db:
            for index in range(extra_results):
                db.add(InferenceResult(
                    request_id=f"wm-{uuid.uuid4().hex[:8]}-{index}",
                    project_id=self.project.id,
                    deployment_id=deployment_id,
                ))
            db.commit()
        return {
            "deployment_id": str(deployment_id),
            "report_id": str(report_id),
            "report_created_at": anchor.isoformat(),
        }

    def test_reproposal_below_watermark_is_rejected(self):
        payload = self._deployment_payload(extra_results=5)
        approval = self._create(
            approval_type="retrain_proposal", payload=payload, initiator=self.owner,
        )
        with self.session_factory() as db:
            decide_approval(
                db, approval_id=approval.id, actor_id=self.editor_b.id,
                decision="reject", note="漂移证据不足",
            )
            db.commit()
        with self.session_factory() as db:
            with self.assertRaises(ApprovalError) as caught:
                create_approval(
                    db, project_id=self.project.id, approval_type="retrain_proposal",
                    title="再提案", payload=payload, initiator_id=self.owner.id,
                )
            self.assertEqual(caught.exception.code, "RETRAIN_PROPOSAL_BELOW_WATERMARK")

    def test_reproposal_above_watermark_passes(self):
        payload = self._deployment_payload(extra_results=5)
        approval = self._create(
            approval_type="retrain_proposal", payload=payload, initiator=self.owner,
        )
        with self.session_factory() as db:
            decide_approval(
                db, approval_id=approval.id, actor_id=self.editor_b.id,
                decision="reject", note="漂移证据不足",
            )
            db.commit()
        # 新增 6 行样本越过水位线（5）→ 允许再提案
        with self.session_factory() as db:
            deployment_id = payload["deployment_id"]
            for index in range(6):
                db.add(InferenceResult(
                    request_id=f"wm-more-{uuid.uuid4().hex[:8]}-{index}",
                    project_id=self.project.id,
                    deployment_id=uuid.UUID(deployment_id),
                ))
            db.commit()
        with self.session_factory() as db:
            second = create_approval(
                db, project_id=self.project.id, approval_type="retrain_proposal",
                title="越线再提案", payload=payload, initiator_id=self.owner.id,
            )
            self.assertEqual(second.status, "pending")


class TestReservedTypeAndRetrainTrigger(ApprovalCenterCase):
    def test_recipe_change_multiplier_perform_applies_plan(self):
        """〔第三轮复审 2026-11-28 改造〕recipe_change 已注册执行器（wave1），
        旧断言 409 EXECUTOR_NOT_READY 的「保留类型」语义随之退役——保留类型
        清零（approval_executors._RESERVED_TYPES = ()）后该分支对合法类型不可达。
        本用例改为锁定加严形态的真实执行：批准 → 乘数写回控制计划。"""
        from app.models.qms import QmsControlPlan
        from app.services.approvals import perform_approved

        with self.session_factory() as db:
            plan = QmsControlPlan(
                project_id=self.project.id,
                code=f"PL-{uuid.uuid4().hex[:8]}",
                version=1, status="active",
                quality_points=[], tightening_multiplier=1.0,
                decision_log=[], created_by_id=self.owner.id,
            )
            db.add(plan)
            db.commit()
            plan_id = plan.id
        approval = self._create(
            approval_type="recipe_change",
            payload={"plan_id": str(plan_id), "suggested_multiplier": 1.25},
        )
        with self.session_factory() as db:
            decided = decide_approval(
                db, approval_id=approval.id, actor_id=self.editor_b.id,
                decision="approve",
            )
            result = perform_approved(db, approval=decided, actor_id=self.editor_b.id)
            db.commit()
            plan = db.get(QmsControlPlan, uuid.UUID(result["plan_id"]))
            self.assertEqual(plan.tightening_multiplier, 1.25)
            sources = [row.get("source") for row in (plan.decision_log or [])]
            self.assertIn("tightening_approval", sources)

    def test_retrain_perform_invokes_loop_config_trigger(self):
        from unittest.mock import patch

        from app.models.demo_loop import DemoLoopConfig

        deployment_id = uuid.uuid4()
        with self.session_factory() as db:
            db.add(DemoLoopConfig(
                project_id=self.project.id, deployment_id=deployment_id,
            ))
            db.commit()
        approval = self._create(
            approval_type="retrain_proposal",
            payload={
                "deployment_id": str(deployment_id),
                "report_id": str(uuid.uuid4()),
            },
            initiator=self.owner,
        )
        with self.session_factory() as db:
            decided = decide_approval(
                db, approval_id=approval.id, actor_id=self.editor_b.id,
                decision="approve",
            )
            from app.services.approvals import perform_approved
            from app.services.demo_loop import DemoLoopService

            with patch.object(
                DemoLoopService, "_trigger_retrain_inner",
                lambda self_inner, config, actor: setattr(
                    self_inner, "_called_with", str(config.deployment_id),
                ),
            ):
                result = perform_approved(db, approval=decided, actor_id=self.editor_b.id)
            db.commit()
        self.assertEqual(result["triggered"], True)
        self.assertEqual(decided.execution_status, "succeeded")
        self.assertEqual(decided.execution_ref.get("retrain_mode"), "engine")

    def test_retrain_perform_without_loop_config_fails_honestly(self):
        approval = self._create(
            approval_type="retrain_proposal",
            payload={
                "deployment_id": str(uuid.uuid4()),
                "report_id": str(uuid.uuid4()),
            },
            initiator=self.owner,
        )
        with self.session_factory() as db:
            decided = decide_approval(
                db, approval_id=approval.id, actor_id=self.editor_b.id,
                decision="approve",
            )
            from app.services.approvals import perform_approved

            result = perform_approved(db, approval=decided, actor_id=self.editor_b.id)
            db.commit()
        self.assertEqual(decided.execution_status, "failed")
        self.assertIn("closed-loop retrain config", decided.execution_error)
        self.assertEqual(result["status"], "failed")


class TestLegacyProjection(ApprovalCenterCase):
    def test_projection_maps_four_sources(self):
        from app.models.agent import AgentTask
        from app.models.model_registry import (
            InferenceDeployment,
            ModelCard,
            ModelVersion,
        )
        from app.models.skill_revision import SkillRevision
        from app.services.approvals import legacy_approvals

        with self.session_factory() as db:
            task = AgentTask(
                project_id=self.project.id, name="审查任务",
                created_by_id=self.owner.id, review_status="pending",
            )
            db.add(task)
            db.flush()
            version = ModelVersion(
                registered_model_id=uuid.uuid4(), version_number=7,
                source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
                onnx_artifact_id=uuid.uuid4(),
                source_model_library_id=uuid.uuid4(),
                approval_status="pending", created_by_id=self.owner.id,
            )
            db.add(version)
            db.flush()
            db.add(InferenceDeployment(
                project_id=self.project.id, name="投影部署",
                model_version_id=version.id, created_by_id=self.owner.id,
            ))
            db.flush()
            card = ModelCard(model_version_id=version.id, approval_status="approved")
            db.add(card)
            db.add(SkillRevision(
                skill_name="automl-agent", base_version=1, new_version=2,
                status="pending_approval", risk_level="medium",
                approved_by=self.editor_b.id,
            ))
            db.commit()
        with self.session_factory() as db:
            projection = legacy_approvals(db, project_id=self.project.id)
        by_source = {}
        for item in projection["items"]:
            by_source.setdefault(item["source"], []).append(item)
        self.assertEqual(by_source["agent_task_review"][0]["status"], "pending")
        self.assertEqual(by_source["model_version"][0]["raw_status"], "pending")
        self.assertEqual(by_source["model_card"][0]["raw_status"], "approved")
        self.assertEqual(by_source["skill_revision"][0]["status"], "pending")
        self.assertIn("平台级", by_source["skill_revision"][0]["note"])


class TestProducersWiring(ApprovalCenterCase):
    """R4b 生产者接线：critical 关闭路由审批（D8 场景开关）+ 漂移提案进队列。"""

    def test_critical_close_routes_to_approval_when_scene_flag_on(self):
        from app.models.quality_domain import QualityScene

        with self.session_factory() as db:
            scene = QualityScene(
                project_id=self.project.id, code="scene-approval", name="审批场景",
                alert_settings={"require_close_approval_for_critical": True},
            )
            db.add(scene)
            db.flush()
            alert = QualityAlert(
                project_id=self.project.id, scene_id=scene.id,
                source_type="model_risk", severity="critical",
                title="routed-close", evidence={}, merge_key="model_risk",
                status="acknowledged", assigned_to_id=self.operator.id,
            )
            db.add(alert)
            db.commit()
            alert_id = alert.id

        from app.api.approvals import router as approvals_router
        from app.api.auth import get_current_user
        from app.api.quality_alerts import router as alerts_router
        from app.database import get_db

        app = FastAPI()
        app.include_router(approvals_router)
        app.include_router(alerts_router)

        def _override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: self.operator
        client = TestClient(app)
        response = client.post(
            f"/api/projects/{self.project.id}/quality-alerts/{alert_id}/transition",
            json={"to_status": "closed", "resolution": "confirmed_issue"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["routed_to_approval"])
        with self.session_factory() as db:
            routed = db.get(QualityAlert, alert_id)
            self.assertEqual(routed.status, "acknowledged")
            approval = db.get(ApprovalRequest, uuid.UUID(payload["approval_id"]))
            self.assertEqual(approval.type, "disposition")

    def test_critical_close_unchanged_when_scene_flag_off(self):
        with self.session_factory() as db:
            alert = QualityAlert(
                project_id=self.project.id,
                source_type="model_risk", severity="critical",
                title="direct-close", evidence={}, merge_key="model_risk",
                status="acknowledged", assigned_to_id=self.operator.id,
            )
            db.add(alert)
            db.commit()
            alert_id = alert.id

        from app.api.auth import get_current_user
        from app.api.quality_alerts import router as alerts_router
        from app.database import get_db

        app = FastAPI()
        app.include_router(alerts_router)

        def _override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: self.operator
        client = TestClient(app)
        response = client.post(
            f"/api/projects/{self.project.id}/quality-alerts/{alert_id}/transition",
            json={"to_status": "closed", "resolution": "confirmed_issue"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("routed_to_approval", response.json())
        with self.session_factory() as db:
            self.assertEqual(db.get(QualityAlert, alert_id).status, "closed")

    def test_drift_propose_creates_approval(self):
        from app.models.drift import DriftReport

        deployment_id = uuid.uuid4()
        with self.session_factory() as db:
            report = DriftReport(
                project_id=self.project.id, deployment_id=deployment_id,
                level="severe",
                started_at=datetime.utcnow() - timedelta(hours=2),
                ended_at=datetime.utcnow() - timedelta(minutes=5),
            )
            db.add(report)
            db.commit()
            report_id = report.id

        from app.api.approvals import router as approvals_router
        from app.api.auth import get_current_user
        from app.api.drift import router as drift_router
        from app.database import get_db

        app = FastAPI()
        app.include_router(approvals_router)
        app.include_router(drift_router)

        def _override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: self.owner
        client = TestClient(app)
        response = client.post(
            f"/api/projects/{self.project.id}/drift/reports/{report_id}/propose-retrain",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("approval_id"))
        with self.session_factory() as db:
            approval = db.get(ApprovalRequest, uuid.UUID(payload["approval_id"]))
            self.assertEqual(approval.type, "retrain_proposal")
            self.assertEqual(approval.payload.get("deployment_id"), str(deployment_id))
            from app.models.drift import DriftReport as _DR

            self.assertIsNotNone(db.get(_DR, report_id).proposal_at)


class TestPendingCountEndpoint(ApprovalCenterCase):
    def test_pending_count_endpoint_counts_pending(self):
        from app.api.approvals import router as approvals_router
        from app.api.auth import get_current_user
        from app.database import get_db

        self._create(initiator=self.owner)
        self._create(initiator=self.owner)
        app = FastAPI()
        app.include_router(approvals_router)

        def _override_db():
            db = self.session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: self.operator
        client = TestClient(app)
        response = client.get("/api/approvals/pending-count")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
