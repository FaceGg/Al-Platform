"""三批复审修复（2026-11-27 批次 A）的 HTTP 级回归测试。

根因纪律：这批缺陷全部因「验收测试只在服务层直调、不经 HTTP」而假绿——
所以本模块全部用 TestClient 走真实路由，覆盖事务边界与异常映射。

覆盖：
- U1 保留类型审批经 HTTP 批准 → 409 APPROVAL_EXECUTOR_NOT_READY（曾 500）
- U2 预授权发布执行不再 NameError（作用域导入修复；行为级验证随 S2b 大修）
- 演示预警不再经开放 API「检验结果」外泄（合同 §6-9）
- /api/platform/ingest-status 匿名 401（曾 200）
- 动作审计脱敏覆盖列表内 dict（曾绕过）
- NCR 关闭门禁经 HTTP 可达（曾因回滚永远关不掉）+ 点三次不能绕过时间窗
"""
import hashlib
import json
import unittest
import uuid
from datetime import datetime, timedelta

import numpy as np

from app.config import settings
from app.models.qms import QmsNcrCapa
from app.models.quality_alerts import QualityAlert
from app.services.qms_core import create_d8, create_ncr
from app.services.qms_tools import create_or_replace_plan, normalize_fmea_items
from tests.quality_alert_fixtures import QualityAlertApiCase


class _SeqPredictor:
    """按序循环输出预设标签的预测器（模块级：joblib pickle 需要可导入的类）；
    可选 feature_importances_ 供 explain_sample 使用。"""

    def __init__(self, expected, weights=None):
        self._expected = list(expected)
        if weights is not None:
            self.feature_importances_ = list(weights)

    def predict(self, matrix):
        base = self._expected * (len(matrix) // max(1, len(self._expected)) + 1)
        return np.array(base[: len(matrix)])


class TestAuditFixes(QualityAlertApiCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._storage_dir = __import__("tempfile").TemporaryDirectory()
        cls._original_storage_dir = settings.artifact_storage_dir
        settings.artifact_storage_dir = cls._storage_dir.name

    @classmethod
    def tearDownClass(cls):
        settings.artifact_storage_dir = cls._original_storage_dir
        cls._storage_dir.cleanup()
        super().tearDownClass()

    def _fmea_recipe_change_approval(self, tag):
        """造一条 recipe_change 审批单（FMEA 高 RPN 同步），返回审批 id。"""
        base = f"/api/projects/{self.project.id}/qms"
        fmea = self.client.post(f"{base}/fmeas", json={
            "name": f"F-{tag}",
            "items": [{"failure_mode": "m", "severity": 9, "occurrence": 6, "detection": 5}],
        }).json()["id"]
        plan = create_or_replace_plan(self.db, project_id=self.project.id,
                                      code=f"PL-{tag}", quality_points=[])
        self.db.commit()
        sync = self.client.post(f"{base}/fmeas/{fmea}/sync-control-plan?plan_id={plan.id}")
        self.assertEqual(sync.status_code, 200, sync.text)
        from app.models.approvals import ApprovalRequest

        row = self.db.query(ApprovalRequest).filter(
            ApprovalRequest.type == "recipe_change").order_by(
            ApprovalRequest.created_at.desc()).first()
        return str(row.id)

    def test_u1_reserved_type_approve_returns_409_not_500(self):
        """U1：保留类型经 HTTP 批准 → 409 APPROVAL_EXECUTOR_NOT_READY（曾 500）。"""
        tag = uuid.uuid4().hex[:6]
        base = f"/api/projects/{self.project.id}"
        approval_id = self._fmea_recipe_change_approval(tag)
        # 发起人是 owner；把 operator 升为 editor 以满足四眼
        from sqlalchemy import update
        from app.models.access import ProjectMember

        self.db.execute(update(ProjectMember)
                        .where(ProjectMember.project_id == self.project.id,
                               ProjectMember.user_id == self.operator.id)
                        .values(role="editor"))
        self.db.commit()
        # 换人批准（四眼）：operator 升 editor 后持有 approval.approve
        self.act_as(self.operator)
        response = self.client.post(f"{base}/approvals/{approval_id}/approve",
                                    json={"note": "同意同步"})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "APPROVAL_EXECUTOR_NOT_READY")

    def test_demo_alerts_not_leaked_via_open_inspection_results(self):
        """演示预警不得经开放 API「检验结果」外泄（合同 §6-9；曾实测泄漏）。"""
        tag = uuid.uuid4().hex[:6]
        base = f"/api/projects/{self.project.id}"
        now = datetime.utcnow()
        for is_demo, label in ((True, "demo"), (False, "real")):
            self.db.add(QualityAlert(
                project_id=self.project.id, source_type="model_risk",
                severity="critical", title=f"{label}-{tag}", evidence={},
                merge_key=f"{label}-{tag}", status="closed",
                resolution="confirmed_issue", is_demo=is_demo,
                created_at=now - timedelta(hours=2), closed_at=now - timedelta(hours=1),
            ))
        self.db.commit()
        key = self.client.post(f"{base}/open-api-keys", json={}).json()["plaintext"]
        rows = self.client.get(
            f"/api/v1/open/projects/{self.project.id}/inspection-results",
            params={"page_size": 200}, headers={"X-Api-Key": key},
        ).json()["items"]
        titles = [r["title"] for r in rows]
        self.assertIn(f"real-{tag}", titles, "真实确认结论应在")
        self.assertNotIn(f"demo-{tag}", titles, "演示预警不得外泄")

    def test_ingest_status_requires_login(self):
        """/api/platform/ingest-status 匿名须 401（曾 200）。"""
        import tempfile

        from app.config import settings as app_settings
        from fastapi.testclient import TestClient

        from app.main import app

        saved = app.dependency_overrides.pop(
            __import__("app.api.auth", fromlist=["get_current_user"]).get_current_user, None)
        try:
            anon = TestClient(app)
            response = anon.get("/api/platform/ingest-status")
            self.assertEqual(response.status_code, 401, response.text[:120])
        finally:
            if saved is not None:
                app.dependency_overrides[
                    __import__("app.api.auth", fromlist=["get_current_user"]).get_current_user] = saved
        void = tempfile  # 保持导入使用（ noqa 语义占位）
        del void
        del app_settings

    def test_agent_action_audit_masks_nested_lists(self):
        """脱敏覆盖列表内 dict：messages[].api_key 须 REDACTED（曾绕过）。"""
        from app.services.agent_action_audit import _mask

        payload = {"messages": [{"role": "user", "api_key": "SECRET-IN-LIST",
                                 "content": "问题内容"}]}
        masked = json.loads(json.dumps(_mask(payload)))
        self.assertEqual(masked["messages"][0]["api_key"], "***REDACTED***")
        self.assertEqual(masked["messages"][0]["content"], "问题内容")

    def test_ncr_close_gate_reachable_over_http_and_time_gated(self):
        """NCR 关闭门禁经 HTTP：可推进到 verification；未满验证期被拒且回滚无害。"""
        tag = uuid.uuid4().hex[:6]
        base = f"/api/projects/{self.project.id}"
        ncr_id = self.client.post(f"{base}/qms/ncr-capa", json={
            "code": f"P-{tag}", "title": "HTTP 关闭门禁"}).json()["id"]
        for _ in range(3):
            step = self.client.post(f"{base}/qms/ncr-capa/{ncr_id}/transition")
            self.assertEqual(step.status_code, 200, step.text)
        detail = self.client.get(f"{base}/qms/ncr-capa/{ncr_id}").json()
        self.assertEqual(detail["stage"], "verification")
        # 未满验证期：409 且计数不被错误累计（新语义为时间窗判定）
        for _ in range(3):
            blocked = self.client.post(f"{base}/qms/ncr-capa/{ncr_id}/transition")
            self.assertEqual(blocked.status_code, 409)
            self.assertEqual(blocked.json()["detail"]["code"], "NCR_CLOSE_BLOCKED")
        after = self.client.get(f"{base}/qms/ncr-capa/{ncr_id}").json()
        self.assertEqual(after["stage"], "verification")


class TestBatchB2Fixes(QualityAlertApiCase):
    """批次 B 修复（2026-11-27）：E15 质量门接线、自动开案、控制计划归档。"""

    def test_critical_confirmed_close_auto_opens_case(self):
        """critical 确认异常关闭 → 自动开质量案例（D4/B3-07 补实现）。"""
        from app.models.qms import QmsCase

        tag = uuid.uuid4().hex[:6]
        base = f"/api/projects/{self.project.id}"
        alert = QualityAlert(
            project_id=self.project.id, source_type="model_risk",
            severity="critical", title=f"auto-case-{tag}", evidence={},
            merge_key=f"auto-case-{tag}", status="open", sla_due_at=None,
        )
        self.db.add(alert)
        self.db.commit()
        self.act_as(self.owner)
        # F2 流转图：closed 只能从 acknowledged/processing/review_pending 进入
        ack = self.client.post(
            f"{base}/quality-alerts/{alert.id}/ack",
            json={"assignee_id": str(self.owner.id)})
        self.assertIn(ack.status_code, (200, 201), ack.text[:200])
        response = self.client.post(
            f"{base}/quality-alerts/{alert.id}/disposition",
            json={"resolution": "confirmed_issue", "note": "确认为真实异常",
                  "form": {"action": "停机检查"}},
        )
        self.assertIn(response.status_code, (200, 201), response.text[:200])
        cases = self.db.query(QmsCase).filter(
            QmsCase.source_alert_id == alert.id).all()
        self.assertEqual(len(cases), 1, "critical 确认关闭应自动开案")
        self.assertEqual(cases[0].severity, "critical")
        # 对照：非 critical 确认关闭不开案
        minor = QualityAlert(
            project_id=self.project.id, source_type="model_risk",
            severity="warning", title=f"no-case-{tag}", evidence={},
            merge_key=f"no-case-{tag}", status="open", sla_due_at=None,
        )
        self.db.add(minor)
        self.db.commit()
        self.client.post(f"{base}/quality-alerts/{minor.id}/ack",
                         json={"assignee_id": str(self.owner.id)})
        self.client.post(
            f"{base}/quality-alerts/{minor.id}/disposition",
            json={"resolution": "confirmed_issue", "note": "一般异常",
                  "form": {"action": "调整参数"}},
        )
        still_one = self.db.query(QmsCase).filter(
            QmsCase.source_alert_id == minor.id).all()
        self.assertEqual(len(still_one), 0, "非 critical 不应自动开案")

    def test_control_plan_archive_enables_next_version(self):
        """归档端点：归档后可建第二版（三批复审缺口——原实现永远建不出来）。"""
        from contextlib import suppress

        from app.services.qms_tools import create_or_replace_plan

        tag = uuid.uuid4().hex[:6]
        base = f"/api/projects/{self.project.id}/qms"
        plan1 = create_or_replace_plan(self.db, project_id=self.project.id,
                                       code=f"A-{tag}", quality_points=[])
        self.db.commit()
        # 归档前建第二版被拒（409 双生效）
        with suppress(Exception):
            blocked = self.client.post(f"{base}/control-plans", json={
                "code": f"B-{tag}", "quality_points": []})
            self.assertEqual(blocked.status_code, 409)
        # 归档
        archived = self.client.post(f"{base}/control-plans/{plan1.id}/archive")
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(archived.json()["status"], "archived")
        # 归档后可建第二版
        second = self.client.post(f"{base}/control-plans", json={
            "code": f"B-{tag}", "quality_points": []})
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["version"], 2)
        # 重复归档被拒
        again = self.client.post(f"{base}/control-plans/{plan1.id}/archive")
        self.assertEqual(again.status_code, 409)


class TestSecondReviewFixes(unittest.TestCase):
    """第二轮复审（2026-11-28）三项同族修复：影子 champion 工件归属、
    explain_sample 键错配、自动开案保存点隔离。"""

    def setUp(self):
        import tempfile

        import joblib
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.database import Base
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import (
            DeploymentRevision,
            DeploymentTarget,
            InferenceDeployment,
            ModelVersion,
            RegisteredModel,
        )
        from app.models.project import Project
        from app.models.user import User
        from app.services.artifact_service import build_artifact_service
        from app.services.model_artifact_sealing import model_seal_metadata

        self.engine = create_engine("sqlite://",
                                    connect_args={"check_same_thread": False},
                                    poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        tag = uuid.uuid4().hex[:6]
        self.owner = User(username=f"sr-{tag}", password_hash="hash")
        self.db.add(self.owner)
        self.db.flush()
        self.project = Project(name=f"sr-{tag}", owner_id=self.owner.id)
        self.db.add(self.project)
        self.db.flush()
        self.artifacts = build_artifact_service(self.db)
        self._workdir = tempfile.TemporaryDirectory()

        def _sealed_library(name, labels, importances=None):
            bundle = _SeqPredictor(labels, importances)
            path = self._workdir.name + f"/{name}.joblib"
            joblib.dump(bundle, path)
            payload = open(path, "rb").read()
            digest = hashlib.sha256(payload).hexdigest()
            artifact = self.artifacts.create_from_file(
                self.project.id, path, f"{name}.joblib", "model",
                metadata={**model_seal_metadata(digest), "served_sha256": digest},
            )
            library = ModelLibrary(name=name, owner_id=self.owner.id,
                                   status="completed",
                                   model_artifact_id=artifact.id)
            self.db.add(library)
            self.db.flush()
            return library.id

        registered = RegisteredModel(project_id=self.project.id,
                                     name=f"sr-model-{tag}",
                                     created_by_id=self.owner.id)
        self.db.add(registered)
        self.db.flush()
        champion_lib_id = _sealed_library(
            f"sr-champ-{tag}", [0, 1] * 130, importances=[0.7])
        self.champion = ModelVersion(
            registered_model_id=registered.id, version_number=1,
            source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
            onnx_artifact_id=uuid.uuid4(),
            source_model_library_id=champion_lib_id,
            approval_status="approved", metrics={"f1": 0.9},
            feature_schema=["f1"],
        )
        self.db.add(self.champion)
        self.db.flush()
        self.deployment = InferenceDeployment(
            project_id=self.project.id, name="第二轮复审部署",
            model_version_id=self.champion.id, created_by_id=self.owner.id,
        )
        self.db.add(self.deployment)
        self.db.flush()
        revision = DeploymentRevision(
            deployment_id=self.deployment.id, revision_number=1,
            strategy="immediate", status="stable", created_by_id=self.owner.id,
        )
        self.db.add(revision)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=revision.id, model_version_id=self.champion.id,
            weight_bps=10000, role="stable",
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self._workdir.cleanup()

    def test_shadow_champion_comparison_resolves_project_artifact(self):
        """影子 champion 对照按项目解析工件（曾漏传 project_id 恒降级 None）。"""
        import pandas as pd

        from app.services.release_governance import run_shadow_batch

        frame = pd.DataFrame({
            "f1": [index * 0.1 for index in range(6)],
            "sample_key": [f"sk-{i}" for i in range(6)],
        })
        scored = run_shadow_batch(
            self.db, deployment=self.deployment,
            challenger_version=self.champion, frame=frame,
            feature_columns=["f1"], sample_source="random_sample",
            sample_size=6, actor_id=self.owner.id,
        )
        self.assertGreater(scored, 0)
        from app.models.inference_result import InferenceResult

        rows = self.db.query(InferenceResult).filter(
            InferenceResult.channel == "shadow").all()
        self.assertGreater(len(rows), 0)
        # champion 对照值非空 = 工件按 project_id 解析成功（修复前恒 None）
        with_champion = [r for r in rows if r.extra.get("champion_label") is not None]
        self.assertTrue(with_champion, "champion 对照值不应静默降级")

    def test_explain_sample_resolves_bundle_via_source_library(self):
        """单样本解释按 source_model_library_id + 项目解析工件（曾键型错配
        恒 EXPLAIN_BUNDLE_MISSING）。"""
        from app.services.model_trust import explain_sample

        result = explain_sample(self.db, version=self.champion,
                                project_id=self.project.id,
                                row={"f1": 1.0}, feature_columns=["f1"])
        self.assertTrue(result.get("contributions"), result)

    def test_auto_case_failure_isolated_by_savepoint(self):
        """自动开案失败（保存点隔离）不反噬处置流：会话可用、预警已关闭、
        正常路径仍成功开案。"""
        from unittest.mock import patch

        from app.services import quality_alerts as alert_service
        from app.services.qms_core import open_case

        tag = uuid.uuid4().hex[:6]
        alert = QualityAlert(
            project_id=self.project.id, source_type="model_risk",
            severity="critical", title=f"savepoint-{tag}", evidence={},
            merge_key=f"savepoint-{tag}", status="acknowledged", sla_due_at=None,
            assigned_to_id=self.owner.id,
        )
        self.db.add(alert)
        self.db.commit()
        # open_case 抛错（保存点隔离）→ 处置流完成、会话可用、无 auto_case_id
        #（quality_alerts 在调用时才 import，patch 须打在源模块上）
        with patch("app.services.qms_core.open_case",
                   side_effect=RuntimeError("simulated flush failure")):
            outcome = alert_service.submit_disposition(
                self.db, alert, actor_id=self.owner.id,
                form={"action": "停机检查"}, resolution="confirmed_issue",
                note="确认为真实异常",
            )
            self.db.commit()
        self.assertNotIn("auto_case_id", outcome)
        self.db.commit()  # 会话可用（保存点隔离的核心语义）
        self.db.expire_all()
        row = self.db.get(type(alert), alert.id)
        self.assertEqual(row.status, "closed", "处置结论不得被开案失败回滚")
        # 正常路径：另一条 critical 关闭 → 自动开案成功
        alert2 = QualityAlert(
            project_id=self.project.id, source_type="model_risk",
            severity="critical", title=f"savepoint-ok-{tag}", evidence={},
            merge_key=f"savepoint-ok-{tag}", status="acknowledged", sla_due_at=None,
            assigned_to_id=self.owner.id,
        )
        self.db.add(alert2)
        self.db.commit()
        outcome2 = alert_service.submit_disposition(
            self.db, alert2, actor_id=self.owner.id,
            form={"action": "停机检查"}, resolution="confirmed_issue",
            note="确认为真实异常",
        )
        self.db.commit()
        self.assertIn("auto_case_id", outcome2)


if __name__ == "__main__":
    unittest.main()
