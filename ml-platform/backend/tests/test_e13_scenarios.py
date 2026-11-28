"""E13 场景矩阵端到端（S2b 技术方案 §7.5 第 6 条；第三轮复审 2026-11-28
补齐——三批复审发现 E13 用例数为 0）。

三个治理场景全链（TestClient HTTP）：
- 场景 A 回退豁免：不回退门禁失败 → 被拒申请存档（checks 落档）→ 豁免审批
  （四眼）→ 重新发布放行 → rollout 创建。豁免链曾不可达（批准后无路可发、
  门禁失败的发布单建不出来=豁免无依据）。
- 场景 B 影子回放：shadow run 端点 → channel=shadow 明细落库。
- 场景 C 发布回滚：候选 rollout → rollback → 冠军恢复 stable。
"""
import hashlib
import tempfile
import unittest
import uuid

import joblib
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.access import ProjectMember
from app.models.dataset_splitting import DatasetSplit, DatasetSplitMember, ModelingRound
from app.models.data_version import DatasetVersion
from app.models.inference_result import InferenceResult
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.user import User
from app.services.model_artifact_sealing import model_seal_metadata


class _FixedPredictor:
    """按序输出预设标签的预测器（模块级：joblib pickle 需可导入类）。"""

    def __init__(self, labels):
        self._labels = list(labels)

    def predict(self, matrix):
        base = self._labels * (len(matrix) // max(1, len(self._labels)) + 1)
        return np.array(base[: len(matrix)])


class E13ScenarioCase(unittest.TestCase):
    """治理场景夹具：TestClient + 盲测链（300 行数据集：100 development +
    200 blind）。champion 完美预测、candidate 全预测多数类（盲测 f1≈0.769
    过 floor 0.5 但低于 champion 1.0 → 不回退 failed）。"""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.db = sessionmaker(bind=cls.engine, expire_on_commit=False)()
        tag = uuid.uuid4().hex[:6]
        cls.owner = User(username=f"e13-owner-{tag}", password_hash="hash")
        cls.operator = User(username=f"e13-operator-{tag}", password_hash="hash")
        cls.db.add_all([cls.owner, cls.operator])
        cls.db.flush()
        cls.project = Project(name=f"e13-{tag}", owner_id=cls.owner.id)
        cls.db.add(cls.project)
        cls.db.flush()
        cls.db.add(ProjectMember(project_id=cls.project.id, user_id=cls.operator.id,
                                 role="operator"))
        cls._build_blind_chain(tag)
        cls.db.commit()
        cls.actor = cls.owner
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.actor
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    @classmethod
    def _build_blind_chain(cls, tag):
        from app.services.artifact_service import build_artifact_service

        artifacts = build_artifact_service(cls.db)
        workdir = tempfile.TemporaryDirectory()
        total = 300
        frame = pd.DataFrame({
            "feature_a": [float(index) for index in range(total)],
            "target": ["a" if index < 225 else "b" for index in range(total)],
            "sample_key": [f"sk-{index}" for index in range(total)],
        })
        csv_path = workdir.name + "/e13.csv"
        frame.to_csv(csv_path, index=False)
        dataset_artifact = artifacts.create_from_file(
            cls.project.id, csv_path, f"e13-{tag}.csv", "dataset",
        )
        cls.dataset_version = DatasetVersion(
            project_id=cls.project.id, operator_id=cls.owner.id, version=1,
            status="ready", row_count=total, column_count=3,
            content_hash=uuid.uuid4().hex, schema_hash=uuid.uuid4().hex,
            normalized_artifact_id=dataset_artifact.id,
        )
        cls.db.add(cls.dataset_version)
        cls.db.flush()
        cls.split = DatasetSplit(
            project_id=cls.project.id, dataset_version_id=cls.dataset_version.id,
            name="E13 盲测", strategy="random_stratified",
            params={"target_column": "target", "test_size": 0.5, "seed": 42,
                    "sample_usage": {"development": "training",
                                     "blind": "release_validation"}},
            split_fingerprint=uuid.uuid4().hex, created_by_id=cls.owner.id,
        )
        cls.db.add(cls.split)
        cls.db.flush()
        for index in range(total):
            role = "development" if index < 100 else "blind"
            cls.db.add(DatasetSplitMember(
                split_id=cls.split.id, row_index=index,
                sample_key=f"sk-{index}", role=role,
            ))
        cls.round_row = ModelingRound(
            project_id=cls.project.id, dataset_version_id=cls.dataset_version.id,
            split_id=cls.split.id, status="locked", blind_eval_count=0,
            blind_eval_cap=6, blind_fingerprint=uuid.uuid4().hex,
            created_by_id=cls.owner.id,
        )
        cls.db.add(cls.round_row)

        registered = RegisteredModel(project_id=cls.project.id,
                                     name=f"e13-model-{tag}",
                                     created_by_id=cls.owner.id)
        cls.db.add(registered)
        cls.db.flush()

        def _sealed_library(name, labels):
            bundle = _FixedPredictor(labels)
            path = workdir.name + f"/{name}.joblib"
            joblib.dump(bundle, path)
            payload = open(path, "rb").read()
            digest = hashlib.sha256(payload).hexdigest()
            artifact = artifacts.create_from_file(
                cls.project.id, path, f"{name}.joblib", "model",
                metadata={**model_seal_metadata(digest), "served_sha256": digest},
            )
            from app.models.model_library import ModelLibrary

            library = ModelLibrary(name=name, owner_id=cls.owner.id,
                                   status="completed",
                                   model_artifact_id=artifact.id)
            cls.db.add(library)
            cls.db.flush()
            return library

        # champion：完美预测（盲测 200 行 = 行 100..299 → a×125 + b×75）
        champion_labels = ["a"] * 125 + ["b"] * 75
        champion_lib = _sealed_library(f"e13-champ-{tag}", champion_labels)
        # candidate：b 类漏报 25（盲测 macro F1≈0.855——过 floor 0.5、
        # 低于 champion 1.0 → 不回退 failed 但终验通过，豁免可发起）
        candidate_lib = _sealed_library(f"e13-cand-{tag}", ["a"] * 150 + ["b"] * 50)
        cls.champion_version = ModelVersion(
            registered_model_id=registered.id, version_number=1,
            source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
            onnx_artifact_id=uuid.uuid4(),
            source_model_library_id=champion_lib.id,
            approval_status="approved", metrics={"f1": 0.98},
            feature_schema=["feature_a"],
        )
        cls.candidate_version = ModelVersion(
            registered_model_id=registered.id, version_number=2,
            source_kind="platform_joblib", source_artifact_id=uuid.uuid4(),
            onnx_artifact_id=uuid.uuid4(),
            source_model_library_id=candidate_lib.id,
            approval_status="approved", metrics={"f1": 0.9},
            feature_schema=["feature_a"],
        )
        cls.db.add_all([cls.champion_version, cls.candidate_version])
        cls.db.flush()
        # 场景 A / 场景 C 各用独立部署（类级夹具共享内存库，避免活跃
        # rollout 状态互相泄漏）
        for suffix in ("a", "c"):
            deployment = InferenceDeployment(
                project_id=cls.project.id, name=f"E13 部署-{suffix}",
                model_version_id=cls.champion_version.id,
                created_by_id=cls.owner.id,
            )
            cls.db.add(deployment)
            cls.db.flush()
            revision = DeploymentRevision(
                deployment_id=deployment.id, revision_number=1,
                strategy="immediate", status="stable",
                created_by_id=cls.owner.id,
            )
            cls.db.add(revision)
            cls.db.flush()
            cls.db.add(DeploymentTarget(
                revision_id=revision.id,
                model_version_id=cls.champion_version.id,
                weight_bps=10000, role="stable",
            ))
            if suffix == "a":
                cls.deployment = deployment
            else:
                cls.deployment_c = deployment

    @classmethod
    def act_as(cls, user):
        cls.actor = user

    def _base(self):
        return f"/api/projects/{self.project.id}"

    def _promote_operator(self):
        cls = type(self)
        cls.db.execute(
            __import__("sqlalchemy").update(ProjectMember)
            .where(ProjectMember.project_id == cls.project.id,
                   ProjectMember.user_id == cls.operator.id)
            .values(role="editor"))
        cls.db.commit()

    def test_a_no_regression_exemption_full_chain(self):
        """场景 A：不回退失败 → 存档 → 豁免批准 → 重新发布放行。"""
        cls = type(self)
        cls.act_as(cls.owner)
        base = self._base()
        first = self.client.post(
            f"{base}/model-versions/{cls.candidate_version.id}/release-request",
            json={"deployment_id": str(cls.deployment.id),
                  "model_version_id": str(cls.candidate_version.id)})
        self.assertEqual(first.status_code, 409, first.text)
        self.assertEqual(first.json()["detail"]["code"], "RELEASE_GATE_FAILED")
        rejected_id = first.json()["detail"].get("rejected_request_id")
        self.assertIsNotNone(rejected_id, "被拒申请须存档并回执 id（豁免依据）")
        # 豁免审批（四眼）：owner 发起 → operator（升 editor）批准
        exemption = self.client.post(f"{base}/approvals", json={
            "type": "exemption",
            "title": "不回退豁免：候选接入新工况",
            "payload": {
                "release_approval_id": rejected_id,
                "deployment_id": str(cls.deployment.id),
                "model_version_id": str(cls.candidate_version.id),
                "reason": "新工况样本冠军模型覆盖率不足，业务批准带风险接入",
            },
        })
        self.assertEqual(exemption.status_code, 200, exemption.text)
        exemption_id = exemption.json()["id"]
        self._promote_operator()
        cls.act_as(cls.operator)
        granted = self.client.post(
            f"{base}/approvals/{exemption_id}/approve",
            json={"note": "同意豁免不回退"})
        self.assertEqual(granted.status_code, 200, granted.text)
        # 重新发布：探测查已批准豁免 → 仅 no_regression 放行
        cls.act_as(cls.owner)
        second = self.client.post(
            f"{base}/model-versions/{cls.candidate_version.id}/release-request",
            json={"deployment_id": str(cls.deployment.id),
                  "model_version_id": str(cls.candidate_version.id)})
        self.assertEqual(second.status_code, 200, second.text)
        release_approval_id = second.json()["approval_id"]
        # G3 影子观察窗前置（no_shadow_report 曾拦发布）：先回放一次影子
        shadow = self.client.post(
            f"{base}/inference-deployments/{cls.deployment.id}/shadow/runs",
            json={"model_version_id": str(cls.candidate_version.id),
                  "sample_source": "random_sample", "sample_size": 50})
        self.assertEqual(shadow.status_code, 200, shadow.text)
        # 四眼批准发布 → rollout 创建（豁免链闭环：批准后**有路可发**）
        cls.act_as(cls.operator)
        release = self.client.post(
            f"{base}/approvals/{release_approval_id}/approve",
            json={"note": "豁免生效发布"})
        self.assertEqual(release.status_code, 200, release.text)
        release_body = release.json()
        execution_ref = release_body.get("execution_ref") or {}
        self.assertEqual(release_body.get("execution_status"), "succeeded",
                         f"批准发布应执行成功：{release_body}")
        self.assertTrue(execution_ref.get("rollout_id"),
                        f"批准发布应产生 rollout：{release_body}")

    def test_b_shadow_replay_writes_shadow_channel(self):
        """场景 B：影子回放——HTTP 影子运行落 channel=shadow 明细。"""
        cls = type(self)
        cls.act_as(cls.owner)
        response = self.client.post(
            f"{self._base()}/inference-deployments/{cls.deployment.id}/shadow/runs",
            json={"model_version_id": str(cls.candidate_version.id),
                  "sample_source": "random_sample", "sample_size": 50})
        self.assertEqual(response.status_code, 200, response.text)
        cls.db.expire_all()
        rows = cls.db.query(InferenceResult).filter(
            InferenceResult.project_id == cls.project.id,
            InferenceResult.channel == "shadow").all()
        self.assertGreater(len(rows), 0, "影子回放应落 shadow 明细")

    def test_c_release_rollback_restores_champion(self):
        """场景 C：发布回滚——候选 rollout 回滚后冠军恢复 stable。"""
        from unittest.mock import patch

        from app.services.inference_rollout import InferenceRolloutService

        cls = type(self)
        cls.act_as(cls.owner)
        db = cls.db
        service = InferenceRolloutService(db)
        rollout = service.create_candidate(
            db, cls.deployment_c.id, cls.owner.id,
            targets=[{"model_version_id": str(cls.candidate_version.id),
                      "weight_bps": 10000}],
            strategy="immediate",
        )
        db.commit()
        rollout_id = rollout.id
        # 单元环境无推理运行时：503 在 rollout_service_for 的 services(db)
        # 探测即抛——桩 services 返回假 runtime；预加载/legacy 热替换一并
        # 桩掉（回滚的运行时侧由 test_inference_production_stack 真栈覆盖）
        from types import SimpleNamespace

        import app.api.model_registry as registry_module

        fake_deployment_service = SimpleNamespace(runtime=SimpleNamespace(
            load=lambda *args, **kwargs: None,
            unload=lambda *args, **kwargs: None,
        ))
        with patch.object(registry_module, "_default_services",
                          lambda db: (None, fake_deployment_service)), \
                patch.object(InferenceRolloutService, "_preload_revision",
                             lambda self, db, rollout, revision: None), \
                patch.object(InferenceRolloutService, "_replace_legacy_runtime",
                             lambda self, db, deployment, **kwargs: None):
            response = self.client.post(
                f"/api/inference-deployments/{cls.deployment_c.id}"
                f"/rollouts/{rollout_id}/rollback",
                json={},
            )
        self.assertEqual(response.status_code, 200, response.text)
        cls.db.expire_all()
        stable_targets = (
            cls.db.query(DeploymentTarget)
            .join(DeploymentRevision, DeploymentRevision.id == DeploymentTarget.revision_id)
            .filter(DeploymentRevision.deployment_id == cls.deployment_c.id,
                    DeploymentTarget.role == "stable")
            .all()
        )
        self.assertTrue(stable_targets, "回滚后应有 stable 目标")
        versions = {str(target.model_version_id) for target in stable_targets}
        self.assertIn(str(cls.champion_version.id), versions,
                      "回滚应恢复冠军为 stable")

    def test_d_traffic_mirror_scores_recent_production_traffic(self):
        """场景 D：traffic_mirror——影子样本镜像近期生产流量的 sample_key
        （2026-11-28 落地：曾按「全量 frame」静默兜底，来源语义名存实亡）。"""
        from datetime import datetime, timedelta

        cls = type(self)
        cls.act_as(cls.owner)
        base = self._base()
        deployment_id = str(cls.deployment_c.id)
        now = datetime.utcnow()
        # 生产流量：sk-5 较旧、sk-3 最新（最近优先）；sk-77 不在样本池
        cls.db.add_all([
            InferenceResult(request_id=f"tm-old-{uuid.uuid4().hex[:8]}",
                            project_id=cls.project.id, deployment_id=cls.deployment_c.id,
                            channel="online", sample_key="sk-5",
                            predicted_label="a", occurred_at=now - timedelta(minutes=10)),
            InferenceResult(request_id=f"tm-new-{uuid.uuid4().hex[:8]}",
                            project_id=cls.project.id, deployment_id=cls.deployment_c.id,
                            channel="online", sample_key="sk-3",
                            predicted_label="a", occurred_at=now),
            InferenceResult(request_id=f"tm-out-{uuid.uuid4().hex[:8]}",
                            project_id=cls.project.id, deployment_id=cls.deployment_c.id,
                            channel="online", sample_key="sk-not-in-pool",
                            predicted_label="b", occurred_at=now - timedelta(minutes=1)),
        ])
        cls.db.commit()
        response = self.client.post(
            f"{base}/inference-deployments/{deployment_id}/shadow/runs",
            json={"model_version_id": str(cls.candidate_version.id),
                  "sample_source": "traffic_mirror"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["sample_count"], 2, f"应只镜像命中样本池的 2 条流量：{body}")
        cls.db.expire_all()
        rows = cls.db.query(InferenceResult).filter(
            InferenceResult.deployment_id == cls.deployment_c.id,
            InferenceResult.channel == "shadow",
        ).all()
        keys = [row.sample_key for row in rows]
        self.assertEqual(sorted(keys), ["sk-3", "sk-5"], f"影子样本应为流量键：{keys}")
        # 最近优先：sk-3 的影子明细先落（流量顺序）
        ordered = [row for row in sorted(rows, key=lambda item: item.occurred_at)]
        self.assertEqual(ordered[0].sample_key, "sk-3")
        # 报告来源与 champion 对照
        report = self.client.get(
            f"{base}/inference-deployments/{deployment_id}/shadow/reports")
        self.assertEqual(report.status_code, 200, report.text)
        latest = report.json()["items"][0]
        self.assertEqual(latest["sample_source"], "traffic_mirror")
        self.assertEqual(latest["sample_count"], 2)
        self.assertIsNotNone(latest["agreement_rate"], "traffic_mirror 也应做 champion 对照")

    def test_d_traffic_mirror_without_traffic_fails_honestly(self):
        """场景 D 反例：无生产流量 → 409 SHADOW_NO_TRAFFIC（诚实失败，
        不静默退化为全量样本池）。"""
        from app.models.model_registry import InferenceDeployment

        cls = type(self)
        cls.act_as(cls.owner)
        bare = InferenceDeployment(
            project_id=cls.project.id, name="E13 无流量部署",
            model_version_id=cls.champion_version.id,
            created_by_id=cls.owner.id,
        )
        cls.db.add(bare)
        cls.db.commit()
        response = self.client.post(
            f"{self._base()}/inference-deployments/{bare.id}/shadow/runs",
            json={"model_version_id": str(cls.candidate_version.id),
                  "sample_source": "traffic_mirror"},
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["detail"]["code"], "SHADOW_NO_TRAFFIC")


if __name__ == "__main__":
    unittest.main()
