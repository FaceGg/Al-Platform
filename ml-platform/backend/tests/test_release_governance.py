"""S2b 发布治理链（B2-09/02/03/G2/G3）：门禁五项、不回退、Wilson、预授权
四失效、豁免三约束、回执与按量放量、Challenger 留痕。

验收口径（技术方案 §7.5）。
"""
import hashlib
import unittest
import uuid
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.access import AuditEvent
from app.models.approvals import ApprovalRequest
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
)
from app.models.project import Project
from app.models.release_governance import (
    ReleaseCheck,
    ReleasePreauthorization,
    RolloutReceipt,
)
from app.models.user import User
from app.services.release_governance import (
    GovernanceError,
    business_alert_ratio,
    check_preauthorization,
    evaluate_no_regression,
    evaluate_release_gates,
    grant_preauthorization,
    record_rollout_receipt,
    register_challenger,
    retire_challenger,
    shadow_window_gate,
    valid_receipt_volume,
    wilson_lower_bound,
)


def _sealed_predictor_artifact(db, project_id, owner_id, name, labels):
    """构造密封模型包工件（预测器按序循环输出 labels），返回 (artifact_id, library_id)。"""
    import tempfile
    from pathlib import Path

    import joblib

    from app.models.model_library import ModelLibrary
    from app.services.artifact_service import build_artifact_service
    from app.services.model_artifact_sealing import model_seal_metadata


    workdir = tempfile.TemporaryDirectory()
    path = Path(workdir.name) / (name + ".joblib")
    joblib.dump(_SeqPredictor(labels), path)
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    artifact = build_artifact_service(db).create_from_file(
        project_id, path, name + ".joblib", "model",
        metadata={**model_seal_metadata(digest), "served_sha256": digest},
    )
    library = ModelLibrary(name=name, owner_id=owner_id, status="completed",
                           model_artifact_id=artifact.id)
    db.add(library)
    db.flush()
    return artifact.id, library.id


def _version(db, project, library_owner_id, metrics=None, task=None,
             feature_schema=None, sealed_labels=None, registered_model_id=None):
    """造版本；sealed_labels + feature_schema 提供时挂真实密封模型包（盲测打分用）。"""
    from app.models.model_library import ModelLibrary

    conversion = {"task": task} if task else {}
    source_artifact_id = uuid.uuid4()
    model_library_id = None
    if sealed_labels is not None and feature_schema:
        source_artifact_id, model_library_id = _sealed_predictor_artifact(
            db, project.id, library_owner_id,
            f"lib-{uuid.uuid4().hex[:8]}",
            sealed_labels,
        )
    else:
        library = ModelLibrary(
            name=f"lib-{uuid.uuid4().hex[:8]}", owner_id=library_owner_id,
            status="completed",
        )
        db.add(library)
        db.flush()
        model_library_id = library.id
    version = ModelVersion(
        registered_model_id=registered_model_id or uuid.uuid4(), version_number=100 + np_random(),
        source_kind="platform_joblib", source_artifact_id=source_artifact_id,
        onnx_artifact_id=uuid.uuid4(),
        source_model_library_id=model_library_id,
        approval_status="approved",
        metrics=metrics or {},
        conversion_metadata=conversion,
        feature_schema=feature_schema,
    )
    db.add(version)
    db.flush()
    return version


class _SeqPredictor:
    """按序循环输出预设标签的预测器（模块级：joblib pickle 需要可导入的类）。"""

    def __init__(self, labels):
        self._labels = list(labels)

    def predict(self, matrix):
        base = self._labels * (len(matrix) // max(1, len(self._labels)) + 1)
        return np.array(base[: len(matrix)])


def np_random():
    import random

    return random.randint(1, 99)


class GovernanceCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as db:
            self.owner = User(username=f"gov-{uuid.uuid4().hex[:6]}", password_hash="hash")
            self.approver_b = User(username=f"approver-{uuid.uuid4().hex[:6]}", password_hash="hash")
            db.add_all([self.owner, self.approver_b])
            db.flush()
            self.project = Project(name="发布治理", owner_id=self.owner.id)
            db.add(self.project)
            db.flush()
            # 盲测数据集（真实 CSV 工件，260 行，target=行号%2）——终验/不回退
            # 的盲测打分要物化它并对 blind 段真实打分（三批复审重构）
            import tempfile

            import pandas as pd

            from app.models.data_version import DatasetVersion
            from app.services.artifact_service import build_artifact_service

            blind_rows = [
                {"feature_a": index * 0.1, "target": index % 2,
                 "sample_key": f"sk-{index}"}
                for index in range(260)
            ]
            blind_dir = tempfile.TemporaryDirectory()
            self.addCleanup(blind_dir.cleanup)
            blind_csv = blind_dir.name + "/blind-dataset.csv"
            pd.DataFrame(blind_rows).to_csv(blind_csv, index=False)
            blind_artifact = build_artifact_service(db).create_from_file(
                self.project.id, blind_csv, "blind-dataset.csv", "dataset",
            )
            self.blind_dataset_version = DatasetVersion(
                project_id=self.project.id, operator_id=self.owner.id, version=1,
                status="ready", row_count=260, column_count=3,
                content_hash=uuid.uuid4().hex, schema_hash=uuid.uuid4().hex,
                normalized_artifact_id=blind_artifact.id,
            )
            db.add(self.blind_dataset_version)
            db.flush()
            # champion/challenger 挂真实密封模型包（按序输出每行真值 → 盲测 F1=1.0）
            truth = [str(index % 2) for index in range(260)]
            self.champion = _version(db, self.project, self.owner.id,
                                     metrics={"f1": 0.9},
                                     feature_schema=["feature_a"],
                                     sealed_labels=truth)
            self.challenger = _version(db, self.project, self.owner.id,
                                       metrics={"f1": 0.92},
                                       feature_schema=["feature_a"],
                                       sealed_labels=truth)
            self.deployment = InferenceDeployment(
                project_id=self.project.id, name="治理部署",
                model_version_id=self.champion.id,
                created_by_id=self.owner.id,
            )
            db.add(self.deployment)
            db.flush()
            stable_revision = DeploymentRevision(
                deployment_id=self.deployment.id, revision_number=1,
                strategy="immediate", status="stable",
                created_by_id=self.owner.id,
            )
            db.add(stable_revision)
            db.flush()
            db.add(DeploymentTarget(
                revision_id=stable_revision.id,
                model_version_id=self.champion.id,
                weight_bps=10000, role="stable",
            ))
            db.commit()

    def _approval(self, db, payload=None):
        approval = ApprovalRequest(
            project_id=self.project.id, type="model_release",
            title="发布单", payload=payload or {},
            payload_fingerprint="a" * 64,
            created_by_id=self.owner.id,
            expires_at=datetime.utcnow() + timedelta(hours=72),
        )
        db.add(approval)
        db.flush()
        return approval

    def _blind_round(self, db, sample_count=250):
        from app.models.dataset_splitting import (
            DatasetSplit,
            DatasetSplitMember,
            ModelingRound,
        )

        split = DatasetSplit(
            project_id=self.project.id,
            dataset_version_id=self.blind_dataset_version.id,
            name="盲测划分", strategy="random_stratified",
            # target_column 供盲测终验/不回退的真实打分（三批复审重构）
            params={"target_column": "target", "test_size": 0.5, "seed": 42},
            split_fingerprint="b" * 64,
            created_by_id=self.owner.id,
        )
        db.add(split)
        db.flush()
        for index in range(sample_count):
            db.add(DatasetSplitMember(
                split_id=split.id, row_index=index,
                sample_key=f"sk-{index}", role="blind",
            ))
        round_row = ModelingRound(
            project_id=self.project.id, dataset_version_id=split.dataset_version_id,
            split_id=split.id, status="locked", blind_eval_count=0,
            blind_eval_cap=5, blind_fingerprint="c" * 64, created_by_id=self.owner.id,
        )
        db.add(round_row)
        db.flush()
        return round_row


class TestWilson(unittest.TestCase):
    def test_roadmap_example_29_of_30_is_below_90(self):
        # 路线 B2-03 验收原文：30 检出 29 → 点估计 96.7%，下界 83.3% < 90% 不通过
        self.assertAlmostEqual(wilson_lower_bound(29, 30), 0.8333, places=3)
        self.assertLess(wilson_lower_bound(29, 30), 0.90)

    def test_zero_total_returns_zero(self):
        self.assertEqual(wilson_lower_bound(0, 0), 0.0)


class TestReleaseGates(GovernanceCase):
    def test_four_intercepts(self):
        """低 F1 / 无盲测 / 样本不足 / 漂移超阈四种情形均拦截。"""
        with self.session_factory() as db:
            # 低 F1 候选（0.2）
            weak = _version(db, self.project, self.owner.id, metrics={"f1": 0.2})
            approval = self._approval(db)
            checks = evaluate_release_gates(
                db, deployment=self.deployment, version=weak, approval=approval,
            )
            verdicts = {c.check_key: c.verdict for c in checks}
            self.assertEqual(verdicts["metric_floor"], "failed")
            self.assertEqual(verdicts["blind_final_validation"], "failed")
            self.assertEqual(verdicts["blind_sample_floor"], "failed")
            db.rollback()

    def test_drift_severe_intercepts(self):
        from app.models.drift import DriftReport

        with self.session_factory() as db:
            self._blind_round(db)
            report = DriftReport(
                project_id=self.project.id, deployment_id=self.deployment.id,
                level="severe", started_at=datetime.utcnow(),
                ended_at=datetime.utcnow(),
            )
            db.add(report)
            db.commit()
            approval = self._approval(db)
            checks = evaluate_release_gates(
                db, deployment=self.deployment, version=self.challenger, approval=approval,
            )
            verdicts = {c.check_key: c.verdict for c in checks}
            self.assertEqual(verdicts["drift_severity"], "failed")
            db.rollback()

    def test_passing_candidate_clears_all_gates(self):
        with self.session_factory() as db:
            self._blind_round(db)
            approval = self._approval(db)
            checks = evaluate_release_gates(
                db, deployment=self.deployment, version=self.challenger, approval=approval,
            )
            verdicts = {c.check_key: c.verdict for c in checks}
            self.assertEqual(verdicts["metric_floor"], "passed")
            self.assertEqual(verdicts["drift_severity"], "passed")
            self.assertEqual(verdicts["blind_sample_floor"], "passed")
            self.assertEqual(verdicts["blind_final_validation"], "passed")
            db.commit()

    def test_unsupervised_candidate_not_blocked_by_f1(self):
        """无监督口径：不因无 F1 误拦（读 synthetic_auc 冠军资格键）。"""
        with self.session_factory() as db:
            self._blind_round(db)
            anomaly = _version(db, self.project, self.owner.id,
                               metrics={"synthetic_auc": 0.95}, task="anomaly_detection")
            approval = self._approval(db)
            checks = evaluate_release_gates(
                db, deployment=self.deployment, version=anomaly, approval=approval,
            )
            verdicts = {c.check_key: c.verdict for c in checks}
            self.assertEqual(verdicts["metric_floor"], "passed")
            self.assertNotIn("wilson_lower_bound", verdicts, "无监督不启用 Wilson")
            db.rollback()

    def test_no_regression_tolerates_and_compares_same_blind_round(self):
        with self.session_factory() as db:
            self._blind_round(db)
            result = evaluate_no_regression(
                db, deployment=self.deployment, version=self.challenger,
            )
            self.assertTrue(result["passed"])
            # 同批由「同一 blind frame」构造性保证；样本集指纹随 detail 落档
            self.assertTrue(result["same_blind_samples"])
            self.assertTrue(result["samples_fingerprint"])
            db.commit()

    def test_no_regression_blocks_when_candidate_weaker(self):
        with self.session_factory() as db:
            self._blind_round(db)
            # 恒预测 1：macro F1 = 0.333 < champion 的 1.0（盲测配对揭穿
            # 「浅验证集 metrics 更好」的候选——旧实现会放行）
            weaker = _version(db, self.project, self.owner.id, metrics={"f1": 0.7},
                              feature_schema=["feature_a"], sealed_labels=[1] * 260)
            result = evaluate_no_regression(
                db, deployment=self.deployment, version=weaker,
            )
            self.assertFalse(result["passed"])
            db.commit()

    def test_no_regression_without_champion_is_not_applicable(self):
        with self.session_factory() as db:
            orphan = _version(db, self.project, self.owner.id, metrics={"f1": 0.9})
            deployment_bare = InferenceDeployment(
                project_id=self.project.id, name="无冠军部署",
                model_version_id=orphan.id, created_by_id=self.owner.id,
            )
            db.add(deployment_bare)
            db.commit()
            result = evaluate_no_regression(
                db, deployment=deployment_bare, version=orphan,
            )
            self.assertIsNone(result)


class TestPreauthorization(GovernanceCase):
    def test_grant_and_use_passes(self):
        with self.session_factory() as db:
            auth = grant_preauthorization(
                db, project_id=self.project.id, deployment_id=self.deployment.id,
                gates_fingerprint="g" * 64,
                expires_at=datetime.utcnow() + timedelta(hours=24),
                max_releases=2, granted_by_id=self.approver_b.id,
            )
            used = check_preauthorization(
                db, auth_id=auth.id, deployment_id=self.deployment.id,
                gates_fingerprint="g" * 64, applicant_id=self.owner.id,
            )
            db.commit()
            self.assertEqual(used.releases_used, 1)

    def test_self_granted_use_is_denied(self):
        with self.session_factory() as db:
            auth = grant_preauthorization(
                db, project_id=self.project.id, deployment_id=self.deployment.id,
                gates_fingerprint="g" * 64,
                expires_at=datetime.utcnow() + timedelta(hours=24),
                max_releases=2, granted_by_id=self.owner.id,
            )
            with self.assertRaises(GovernanceError) as caught:
                check_preauthorization(
                    db, auth_id=auth.id, deployment_id=self.deployment.id,
                    gates_fingerprint="g" * 64, applicant_id=self.owner.id,
                )
            self.assertEqual(caught.exception.code, "PREAUTH_SELF_GRANTED_DENIED")

    def test_four_invalidation_scenarios(self):
        with self.session_factory() as db:
            auth = grant_preauthorization(
                db, project_id=self.project.id, deployment_id=self.deployment.id,
                gates_fingerprint="g" * 64,
                expires_at=datetime.utcnow() + timedelta(hours=24),
                max_releases=1, granted_by_id=self.approver_b.id,
            )
            db.commit()
            # 撤销
            auth.status = "revoked"
            db.commit()
            with self.assertRaises(GovernanceError) as caught:
                check_preauthorization(
                    db, auth_id=auth.id, deployment_id=self.deployment.id,
                    gates_fingerprint="g" * 64, applicant_id=self.owner.id,
                )
            self.assertEqual(caught.exception.code, "PREAUTH_REVOKED")
            db.rollback()

        with self.session_factory() as db:
            # 过期
            auth = grant_preauthorization(
                db, project_id=self.project.id, deployment_id=self.deployment.id,
                gates_fingerprint="g" * 64,
                expires_at=datetime.utcnow() - timedelta(hours=1),
                max_releases=1, granted_by_id=self.approver_b.id,
            )
            db.commit()
            with self.assertRaises(GovernanceError) as caught:
                check_preauthorization(
                    db, auth_id=auth.id, deployment_id=self.deployment.id,
                    gates_fingerprint="g" * 64, applicant_id=self.owner.id,
                )
            self.assertEqual(caught.exception.code, "PREAUTH_EXPIRED")

        with self.session_factory() as db:
            # 超次
            auth = grant_preauthorization(
                db, project_id=self.project.id, deployment_id=self.deployment.id,
                gates_fingerprint="g" * 64,
                expires_at=datetime.utcnow() + timedelta(hours=24),
                max_releases=1, granted_by_id=self.approver_b.id,
            )
            db.commit()
            check_preauthorization(
                db, auth_id=auth.id, deployment_id=self.deployment.id,
                gates_fingerprint="g" * 64, applicant_id=self.owner.id,
            )
            with self.assertRaises(GovernanceError) as caught:
                check_preauthorization(
                    db, auth_id=auth.id, deployment_id=self.deployment.id,
                    gates_fingerprint="g" * 64, applicant_id=self.owner.id,
                )
            self.assertEqual(caught.exception.code, "PREAUTH_EXHAUSTED")

        with self.session_factory() as db:
            # 质量门变更（指纹不符）
            auth = grant_preauthorization(
                db, project_id=self.project.id, deployment_id=self.deployment.id,
                gates_fingerprint="g" * 64,
                expires_at=datetime.utcnow() + timedelta(hours=24),
                max_releases=5, granted_by_id=self.approver_b.id,
            )
            db.commit()
            with self.assertRaises(GovernanceError) as caught:
                check_preauthorization(
                    db, auth_id=auth.id, deployment_id=self.deployment.id,
                    gates_fingerprint="h" * 64, applicant_id=self.owner.id,
                )
            self.assertEqual(caught.exception.code, "PREAUTH_GATES_CHANGED")


class TestReceiptsAndShadowGate(GovernanceCase):
    def test_receipt_digest_mismatch_is_marked(self):
        with self.session_factory() as db:
            receipt = record_rollout_receipt(
                db, project_id=self.project.id, rollout_id=uuid.uuid4(),
                effective_alias="rev:ver", scored_count=500,
                artifact_digest="bad" * 16,
                expected_digest="good" * 16,
                reported_by_id=self.owner.id,
            )
            db.commit()
            self.assertEqual(receipt.status, "digest_mismatch")
            self.assertEqual(valid_receipt_volume(db, receipt.rollout_id), 0,
                             "mismatch 回执不计入放量")

    def test_valid_receipts_accumulate_volume(self):
        with self.session_factory() as db:
            rollout_id = uuid.uuid4()
            record_rollout_receipt(
                db, project_id=self.project.id, rollout_id=rollout_id,
                effective_alias="rev:ver", scored_count=300,
                artifact_digest="g" * 16, expected_digest="g" * 16,
            )
            record_rollout_receipt(
                db, project_id=self.project.id, rollout_id=rollout_id,
                effective_alias="rev:ver", scored_count=200,
                artifact_digest="g" * 16, expected_digest="g" * 16,
            )
            db.commit()
            self.assertEqual(valid_receipt_volume(db, rollout_id), 500)

    def test_shadow_window_gate_requires_recent_report(self):
        with self.session_factory() as db:
            gate = shadow_window_gate(db, deployment=self.deployment)
            self.assertFalse(gate["passed"])
            self.assertEqual(gate["reason"], "no_shadow_report")

    def test_challenger_register_retire_with_audit(self):
        with self.session_factory() as db:
            target = register_challenger(
                db, deployment=self.deployment, version=self.challenger,
                actor_id=self.owner.id,
            )
            db.commit()
            self.assertEqual(target.weight_bps, 0)
            audits = db.query(AuditEvent).filter(
                AuditEvent.action == "challenger.register"
            ).all()
            self.assertEqual(len(audits), 1)
            result = retire_challenger(
                db, deployment_id=self.deployment.id, actor_id=self.owner.id
            )
            db.commit()
            self.assertTrue(result["retired"])
            retired_audits = db.query(AuditEvent).filter(
                AuditEvent.action == "challenger.retire"
            ).all()
            self.assertEqual(len(retired_audits), 1)

    def test_challenger_rejects_same_as_stable_and_unapproved(self):
        with self.session_factory() as db:
            with self.assertRaises(GovernanceError) as caught:
                register_challenger(
                    db, deployment=self.deployment, version=self.champion,
                    actor_id=self.owner.id,
                )
            self.assertEqual(caught.exception.code, "CHALLENGER_SAME_AS_STABLE")
            pending = _version(db, self.project, self.owner.id)
            pending.approval_status = "pending"
            db.commit()
            with self.assertRaises(GovernanceError) as caught:
                register_challenger(
                    db, deployment=self.deployment, version=pending,
                    actor_id=self.owner.id,
                )
            self.assertEqual(caught.exception.code, "CHALLENGER_VERSION_NOT_APPROVED")


class TestBusinessFallback(GovernanceCase):
    def test_business_ratio_without_traffic_is_none(self):
        with self.session_factory() as db:
            self.assertIsNone(
                business_alert_ratio(db, deployment=self.deployment)
            )
