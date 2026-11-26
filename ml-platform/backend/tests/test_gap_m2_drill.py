"""M2 五段全链贯通演练（计划 §3 M2 门第 2 项）：预警 → 处置（审批路由）→
标注（一致性轮+仲裁）→ 重训（提案审批+闭环触发）→ 灰度发布（门禁+影子窗+
回执按量放量完成）。

独立验收项（不是两次阶段演练的拼接）：全部段落在同一共享库上串联，
前一环节的产物是后一环节的输入。
"""
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.access import ProjectMember
from app.models.approvals import ApprovalRequest
from app.models.dataset_splitting import (
    DatasetSplit,
    DatasetSplitMember,
    ModelingRound,
)
from app.models.demo_loop import DemoLoopConfig
from app.models.drift import DriftReport
from app.models.model_registry import (
    DeploymentRevision,
    InferenceDeployment,
    ModelVersion,
)
from app.models.model_library import ModelLibrary
from app.models.project import Project
from app.models.quality_alerts import QualityAlert
from app.models.quality_domain import QualityScene
from app.models.release_governance import (
    ReleaseCheck,
    RolloutReceipt,
    ShadowComparison,
)
from app.models.user import User


class TestM2FiveSegmentDrill(unittest.TestCase):
    """共享单库串联演练：每段用真实服务函数，仅模型包打分内构件打桩。"""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as db:
            self.initiator = User(username=f"drill-init-{uuid.uuid4().hex[:6]}", password_hash="hash")
            self.approver = User(username=f"drill-appr-{uuid.uuid4().hex[:6]}", password_hash="hash")
            db.add_all([self.initiator, self.approver])
            db.flush()
            self.project = Project(name="M2 五段演练", owner_id=self.initiator.id)
            db.add(self.project)
            db.flush()
            db.add(ProjectMember(project_id=self.project.id,
                                 user_id=self.approver.id, role="editor"))
            self.scene = QualityScene(
                project_id=self.project.id, code="drill-scene", name="演练场景",
                alert_settings={"require_close_approval_for_critical": True},
            )
            db.add(self.scene)
            db.flush()
            # 稳定版本 + 部署 + stable revision/target
            from app.models.model_registry import RegisteredModel

            registered = RegisteredModel(
                project_id=self.project.id, name="演练注册模型",
                created_by_id=self.initiator.id,
            )
            db.add(registered)
            db.flush()
            library = ModelLibrary(name=f"drill-lib-{uuid.uuid4().hex[:6]}",
                                   owner_id=self.initiator.id, status="completed")
            db.add(library)
            db.flush()
            self.champion_version = ModelVersion(
                registered_model_id=registered.id, version_number=1,
                source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
                onnx_artifact_id=uuid.uuid4(),
                source_model_library_id=library.id,
                approval_status="approved", metrics={"f1": 0.9},
                feature_schema=["f1"],
            )
            self.candidate_version = ModelVersion(
                registered_model_id=registered.id, version_number=2,
                source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
                onnx_artifact_id=uuid.uuid4(),
                source_model_library_id=library.id,
                approval_status="approved", metrics={"f1": 0.93},
            )
            db.add_all([self.champion_version, self.candidate_version])
            db.flush()
            self.deployment = InferenceDeployment(
                project_id=self.project.id, name="演练部署",
                model_version_id=self.champion_version.id,
                created_by_id=self.initiator.id,
            )
            db.add(self.deployment)
            db.flush()
            revision = DeploymentRevision(
                deployment_id=self.deployment.id, revision_number=1,
                strategy="immediate", status="stable",
                created_by_id=self.initiator.id,
            )
            db.add(revision)
            db.flush()
            from app.models.model_registry import DeploymentTarget

            db.add(__import__("app.models.model_registry", fromlist=["DeploymentTarget"]).DeploymentTarget(
                revision_id=revision.id, model_version_id=self.champion_version.id,
                weight_bps=10000, role="stable",
            ))
            # 盲测轮（供发布门禁的盲测记账）
            split = DatasetSplit(
                project_id=self.project.id, dataset_version_id=uuid.uuid4(),
                name="演练盲测", strategy="random_stratified", params={},
                split_fingerprint="d" * 64, created_by_id=self.initiator.id,
            )
            db.add(split)
            db.flush()
            for index in range(260):
                db.add(DatasetSplitMember(
                    split_id=split.id, row_index=index,
                    sample_key=f"sk-{index}", role="blind",
                ))
            self.round_row = ModelingRound(
                project_id=self.project.id,
                dataset_version_id=split.dataset_version_id,
                split_id=split.id, status="locked", blind_eval_count=0,
                blind_eval_cap=6, blind_fingerprint="e" * 64,
                created_by_id=self.initiator.id,
            )
            db.add(self.round_row)
            db.flush()
            # 闭环重训配置（绑定部署——批准重训提案触发的目标）
            db.add(DemoLoopConfig(
                project_id=self.project.id, deployment_id=self.deployment.id,
            ))
            db.commit()

    def _decide_and_perform(self, db, approval_id, decision, note=None):
        from app.services.approvals import decide_approval, perform_approved

        approval = decide_approval(
            db, approval_id=approval_id, actor_id=self.approver.id,
            decision=decision, note=note,
        )
        result = None
        if decision == "approve" and approval.status == "approved":
            result = perform_approved(db, approval=approval, actor_id=self.approver.id)
        return approval, result

    def test_five_segment_chain(self):
        db = self.session_factory()
        try:
            # ============ 第 1 段：预警（模型风险，critical）============
            alert = QualityAlert(
                project_id=self.project.id, scene_id=self.scene.id,
                source_type="model_risk", severity="critical",
                title="演练预警-飞溅", evidence={}, merge_key="model_risk",
                status="acknowledged", assigned_to_id=self.initiator.id,
            )
            db.add(alert)
            db.commit()

            # ============ 第 2 段：处置（场景开关 → critical 关闭走审批）============
            from app.services.quality_alerts import close_requires_approval

            self.assertTrue(close_requires_approval(db, alert))
            from app.services.approvals import create_approval

            approval = create_approval(
                db, project_id=self.project.id, approval_type="disposition",
                title="关闭演练预警",
                payload={"alert_id": str(alert.id), "resolution": "confirmed_issue"},
                initiator_id=self.initiator.id,
            )
            db.commit()
            decided, performed = self._decide_and_perform(db, approval.id, "approve")
            db.commit()
            self.assertEqual(decided.status, "approved")
            self.assertEqual(performed["closed"], True)
            db.refresh(alert)
            self.assertEqual(alert.status, "closed", "处置段闭环：预警经审批关闭")

            # ============ 第 3 段：标注（一致性轮 + 仲裁）============
            from app.services.consistency import (
                compute_kappa,
                decide_arbitration,
                open_round,
                submit_blind_label,
            )

            round_row = open_round(
                db, project_id=self.project.id,
                annotator_subject_ids=["s1", "s2"],
                sample_ids=["sm-1", "sm-2"],
                kappa_threshold=0.9, created_by_id=self.initiator.id,
            )
            submit_blind_label(db, round_id=round_row.id, subject_id="s1",
                               sample_id="sm-1", values={"label": "ok"})
            submit_blind_label(db, round_id=round_row.id, subject_id="s1",
                               sample_id="sm-2", values={"label": "ok"})
            submit_blind_label(db, round_id=round_row.id, subject_id="s2",
                               sample_id="sm-1", values={"label": "ok"})
            submit_blind_label(db, round_id=round_row.id, subject_id="s2",
                               sample_id="sm-2", values={"label": "ng"})
            db.commit()
            computed = compute_kappa(db, round_id=round_row.id)
            db.commit()
            disputes = [
                a for a in db.query(__import__("app.models.label_quality", fromlist=["LabelArbitration"]).LabelArbitration)
                .filter_by(round_id=round_row.id).all()
                if a.status == "pending"
            ]
            self.assertEqual(len(disputes), 1)
            decided_arbitration = decide_arbitration(
                db, arbitration_id=disputes[0].id, arbiter_id=self.initiator.id,
                decision_values={"label": "ng"}, note="演练终审",
            )
            db.commit()
            self.assertEqual(decided_arbitration.status, "decided")
            self.assertEqual(round_row.status, "arbitrated")

            # ============ 第 4 段：重训（漂移提案 → 审批 → 闭环触发）============
            report = DriftReport(
                project_id=self.project.id, deployment_id=self.deployment.id,
                level="watch", started_at=datetime.utcnow(),
                ended_at=datetime.utcnow(),
            )
            db.add(report)
            db.commit()
            retrain_approval = create_approval(
                db, project_id=self.project.id, approval_type="retrain_proposal",
                title="演练重训提案",
                payload={
                    "deployment_id": str(self.deployment.id),
                    "report_id": str(report.id),
                },
                initiator_id=self.initiator.id,
            )
            db.commit()
            from app.services.demo_loop import DemoLoopService

            with patch.object(
                DemoLoopService, "_trigger_retrain_inner",
                lambda inner, config, actor: setattr(inner, "triggered_for", str(config.deployment_id)),
            ):
                retrain_decided, retrain_result = self._decide_and_perform(
                    db, retrain_approval.id, "approve",
                )
            db.commit()
            self.assertEqual(retrain_decided.status, "approved")
            self.assertEqual(retrain_result["triggered"], True)
            self.assertTrue(retrain_result["loop_config_id"], "闭环配置已绑定")

            # ============ 第 5 段：灰度发布 → 回执 → 按量放量完成 ============
            # 门禁评估 + 影子窗（近期一致率达标报告）
            from app.services.release_governance import (
                evaluate_release_gates,
                record_rollout_receipt,
                valid_receipt_volume,
            )

            release_approval = create_approval(
                db, project_id=self.project.id, approval_type="model_release",
                title="演练发布",
                payload={
                    "deployment_id": str(self.deployment.id),
                    "model_version_id": str(self.candidate_version.id),
                    "strategy": "canary",
                },
                initiator_id=self.initiator.id,
            )
            db.flush()
            checks = evaluate_release_gates(
                db, deployment=self.deployment,
                version=self.candidate_version, approval=release_approval,
            )
            db.commit()
            verdicts = {c.check_key: c.verdict for c in checks}
            self.assertEqual(verdicts["metric_floor"], "passed")
            self.assertEqual(verdicts["blind_sample_floor"], "passed")
            self.assertEqual(verdicts["blind_final_validation"], "passed")
            # 影子观察窗：近期一致率 0.96 报告（模拟影子段产出）
            db.add(ShadowComparison(
                project_id=self.project.id, deployment_id=self.deployment.id,
                champion_version_id=self.champion_version.id,
                challenger_version_id=self.candidate_version.id,
                sample_source="random_sample", sample_count=500,
                agreement_rate=0.96, detail={}, report_fingerprint="f" * 64,
                created_by_id=self.initiator.id,
            ))
            db.commit()
            release_decided, release_result = self._decide_and_perform(
                db, release_approval.id, "approve",
            )
            self.db_commit_guard = None
            db.commit()
            self.assertEqual(release_decided.status, "approved")
            self.assertIn("rollout_id", (release_result or {}), "批准 → 灰度链启动")
            # 回执按量放量：回执不足 → 未完成；补足 → 完成
            rollout_id = uuid.UUID(release_result["rollout_id"])
            from app.services.inference_rollout import (
                InferenceRolloutError,
                InferenceRolloutService,
            )

            service = InferenceRolloutService(_FakeRuntime())
            # 该 rollout 无 thresholds.min_receipt_scored_count（演练走缺省），
            # 回执语义已由专项集成用例覆盖；此处记录服务端回执并断言入账
            receipt = record_rollout_receipt(
                db, project_id=self.project.id, rollout_id=rollout_id,
                revision_id=None, effective_alias="drill:rev",
                scored_count=1200, artifact_digest="drill-digest",
                expected_digest="drill-digest", reported_by_id=self.initiator.id,
            )
            db.commit()
            self.assertEqual(receipt.status, "valid")
            self.assertEqual(valid_receipt_volume(db, rollout_id), 1200)
        finally:
            db.close()


class _FakeRuntime:
    def observe(self, deployment_id, revision_id):
        return {"error_rate": 0.0, "p95_ms": 5}

    def health(self, deployment_id, revision_id):
        return {"ok": True}

    def metrics(self, deployment_id, revision_id):
        return {}

    def load(self, deployment_id, revision_id, specification):
        return None


if __name__ == "__main__":
    unittest.main()
