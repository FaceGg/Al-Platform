import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentRollout,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.user import User
from app.services.inference_deployment import (
    InferenceDeploymentError,
    InferenceDeploymentService,
)


class FakeRuntimeClient:
    def __init__(self):
        self.loaded = {}
        self.fail_load = None

    def load(self, deployment_id, specification):
        if self.fail_load:
            raise InferenceDeploymentError(self.fail_load)
        self.loaded[str(deployment_id)] = specification
        return {"already_loaded": False}

    def unload(self, deployment_id):
        self.loaded.pop(str(deployment_id), None)
        return {"already_absent": False}

    def predict(self, deployment_id, records):
        if str(deployment_id) not in self.loaded:
            raise InferenceDeploymentError("DEPLOYMENT_NOT_READY")
        return {"predictions": [1], "records_seen": len(records), "served_key": str(deployment_id)}

    def list(self):
        return {"items": [
            {"deployment_id": key} for key in self.loaded
        ]}


class TestInferenceDeploymentService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.user = User(username="deployment-owner", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="Deployment", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.flush()
        self.artifact = Artifact(
            project_id=self.project.id, name="model.onnx", type="model",
            storage_path="", storage_uri="s3://models/model.onnx",
            file_size=12, format="onnx", metadata_={"sha256": "a" * 64},
        )
        self.db.add(self.artifact)
        self.db.flush()
        self.model = RegisteredModel(
            project_id=self.project.id, name="Fault", created_by_id=self.user.id,
        )
        self.db.add(self.model)
        self.db.flush()
        self.version = ModelVersion(
            registered_model_id=self.model.id, version_number=1,
            source_kind="onnx_artifact", source_artifact_id=self.artifact.id,
            onnx_artifact_id=self.artifact.id, framework="onnx", algorithm="",
            feature_schema=[{"name": "current", "dtype": "float64"}],
            output_schema={"name": "fault", "dtype": "int64", "task": "classification"},
            metrics={}, conversion_metadata={
                "sha256": "a" * 64, "size": 12,
                "input_names": ["features"], "output_names": ["label"],
            }, approval_status="approved", created_by_id=self.user.id,
        )
        self.db.add(self.version)
        self.db.commit()
        self.candidate_artifact = Artifact(
            project_id=self.project.id, name="candidate.onnx", type="model",
            storage_path="", storage_uri="s3://models/candidate.onnx",
            file_size=12, format="onnx", metadata_={"sha256": "b" * 64},
        )
        self.db.add(self.candidate_artifact)
        self.db.flush()
        self.candidate_version = ModelVersion(
            registered_model_id=self.model.id, version_number=2,
            source_kind="onnx_artifact", source_artifact_id=self.candidate_artifact.id,
            onnx_artifact_id=self.candidate_artifact.id, framework="onnx", algorithm="",
            feature_schema=[{"name": "current", "dtype": "float64"}],
            output_schema={"name": "fault", "dtype": "int64", "task": "classification"},
            conversion_metadata={
                "sha256": "b" * 64, "size": 12,
                "input_names": ["features"], "output_names": ["label"],
            }, approval_status="approved", created_by_id=self.user.id,
        )
        self.db.add(self.candidate_version)
        self.db.commit()
        self.runtime = FakeRuntimeClient()
        self.service = InferenceDeploymentService(self.runtime, self.Session)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_create_requires_approved_version(self):
        self.version.approval_status = "pending"
        self.db.commit()
        with self.assertRaises(InferenceDeploymentError) as raised:
            self.service.create(
                self.db, project_id=self.project.id, version_id=self.version.id,
                actor_id=self.user.id, name="primary",
            )
        self.assertEqual(raised.exception.code, "MODEL_NOT_APPROVED")

    def test_start_stop_and_predict_update_observed_state(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="primary",
        )
        started = self.service.start(self.db, deployment.id)
        self.assertEqual((started.desired_state, started.observed_state), ("running", "running"))
        self.assertEqual(self.service.predict(self.db, deployment.id, [{"current": 8.0}])["predictions"], [1])
        stopped = self.service.stop(self.db, deployment.id)
        self.assertEqual((stopped.desired_state, stopped.observed_state), ("stopped", "stopped"))
        with self.assertRaises(InferenceDeploymentError) as raised:
            self.service.predict(self.db, deployment.id, [{"current": 8.0}])
        self.assertEqual(raised.exception.code, "DEPLOYMENT_NOT_READY")

    def test_runtime_spec_includes_legacy_runtime_key_and_revision_identity(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="revision-aware",
        )
        self.service.start(self.db, deployment.id)
        specification = self.runtime.loaded[str(deployment.id)]
        self.assertEqual(specification["runtime_key"], str(deployment.id))
        self.assertEqual(specification["deployment_id"], str(deployment.id))
        self.assertIsNotNone(specification["revision_id"])

    def test_start_while_running_loads_new_stable_alias(self):
        # 回归：闭环换模会轮换 stable revision；已运行部署再次 start() 必须
        # 把新 revision 的别名加载进运行时，否则路由键命中 DEPLOYMENT_NOT_READY。
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="alias-refresh",
        )
        self.service.start(self.db, deployment.id)
        stable = self.db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        stable.status = "superseded"
        revision = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=stable.revision_number + 1,
            strategy="immediate",
            status="stable",
        )
        self.db.add(revision)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=revision.id,
            model_version_id=self.candidate_version.id,
            weight_bps=10000,
            role="stable",
        ))
        deployment.model_version_id = self.candidate_version.id
        self.db.commit()

        self.service.start(self.db, deployment.id)

        self.assertIn(
            f"{revision.id}:{self.candidate_version.id}", self.runtime.loaded,
        )

    def _swap_revision(self, deployment):
        """模拟闭环换模：旧 stable → superseded，新 stable 指向 candidate，部署行切换。"""
        stable = self.db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        stable.status = "superseded"
        revision = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=stable.revision_number + 1,
            strategy="immediate",
            status="stable",
        )
        self.db.add(revision)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=revision.id,
            model_version_id=self.candidate_version.id,
            weight_bps=10000,
            role="stable",
        ))
        deployment.model_version_id = self.candidate_version.id
        self.db.commit()
        return revision

    def test_plain_predict_follows_swapped_stable_revision(self):
        """回归（闭环实测 716e5803）：换模轮换 revision 后，不带 rollout 路由的
        默认 predict 此前永远打旧键（部署的仍是旧模型）。别名已由 reconcile
        预载时必须路由到新 revision 的集成/新模型。"""
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="swap-follow",
        )
        self.service.start(self.db, deployment.id)
        revision = self._swap_revision(deployment)
        self.service.reconcile(self.db)

        result = self.service.predict(self.db, deployment.id, [{"current": 8.0}])

        self.assertEqual(result["served_key"], f"{revision.id}:{self.candidate_version.id}")

    def test_plain_predict_falls_back_when_alias_not_preloaded(self):
        """换模后 reconcile 尚未运行（≤60s 窗口）：别名缺失 → 回落旧键继续服务，
        不允许默认路径报 DEPLOYMENT_NOT_READY。"""
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="swap-fallback",
        )
        self.service.start(self.db, deployment.id)
        self._swap_revision(deployment)  # 不跑 reconcile：别名未预载

        result = self.service.predict(self.db, deployment.id, [{"current": 8.0}])

        self.assertEqual(result["served_key"], str(deployment.id))

    def test_stable_weighted_route_uses_legacy_runtime_session(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="stable-routed",
        )
        self.service.start(self.db, deployment.id)
        prediction = self.service.predict(
            self.db,
            deployment.id,
            [{"current": 8.0}],
            routing_key="request-42",
        )
        self.assertEqual(prediction["predictions"], [1])

    def test_stop_unloads_legacy_stable_and_active_candidate_sessions(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="stop-aliases",
        )
        self.service.start(self.db, deployment.id)
        stable = self.db.query(DeploymentRevision).filter_by(
            deployment_id=deployment.id, status="stable",
        ).one()
        candidate = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=2,
            strategy="canary",
            status="candidate",
            created_by_id=self.user.id,
        )
        self.db.add(candidate)
        self.db.flush()
        candidate_target = DeploymentTarget(
            revision_id=candidate.id,
            model_version_id=self.candidate_version.id,
            weight_bps=10000,
            role="candidate",
        )
        self.db.add(candidate_target)
        self.db.add(DeploymentRollout(
            deployment_id=deployment.id,
            from_revision_id=stable.id,
            to_revision_id=candidate.id,
            state="progressing",
            current_step=1000,
            lock_version=1,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        ))
        self.db.commit()
        candidate_key = f"{candidate.id}:{self.candidate_version.id}"
        self.runtime.load(
            candidate_key,
            self.service._target_specification(
                self.db,
                deployment,
                candidate,
                candidate_target,
            ),
        )

        self.service.stop(self.db, deployment.id)

        self.assertNotIn(str(deployment.id), self.runtime.loaded)
        self.assertNotIn(f"{stable.id}:{self.version.id}", self.runtime.loaded)
        self.assertNotIn(candidate_key, self.runtime.loaded)
        with self.assertRaises(InferenceDeploymentError):
            self.runtime.predict(candidate_key, [{"current": 8.0}])

    def test_reconcile_leaves_active_candidate_alias_recovery_to_rollout_service(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="candidate-restart",
        )
        self.service.start(self.db, deployment.id)
        stable = self.db.query(DeploymentRevision).filter_by(
            deployment_id=deployment.id, status="stable",
        ).one()
        candidate = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=2,
            strategy="canary",
            status="candidate",
            created_by_id=self.user.id,
        )
        self.db.add(candidate)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=candidate.id,
            model_version_id=self.version.id,
            weight_bps=10000,
            role="candidate",
        ))
        rollout = DeploymentRollout(
            deployment_id=deployment.id,
            from_revision_id=stable.id,
            to_revision_id=candidate.id,
            state="progressing",
            current_step=1000,
            lock_version=1,
            step_schedule=[0, 1000, 5000, 10000],
            thresholds={"max_error_rate": 0.01, "max_p95_ms": 500},
        )
        self.db.add(rollout)
        self.db.commit()
        self.runtime.loaded.pop(str(deployment.id))
        self.runtime.load(str(deployment.id), self.service._specification(self.db, deployment))
        result = self.service.reconcile(self.db)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["loaded"], 0)
        self.assertNotIn(
            f"{candidate.id}:{self.version.id}",
            self.runtime.loaded,
        )

        self.runtime.load(
            f"{candidate.id}:{self.version.id}",
            self.service._target_specification(
                self.db, deployment, candidate, candidate.targets[0],
            ),
        )
        loaded_before_reconcile = list(self.runtime.loaded)
        second_result = self.service.reconcile(self.db)
        self.assertEqual(second_result["loaded"], 0)
        self.assertEqual(loaded_before_reconcile, list(self.runtime.loaded))
        self.assertIn(
            f"{candidate.id}:{self.version.id}",
            self.runtime.loaded,
        )

    def test_runtime_failure_persists_only_stable_code_and_can_retry(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="primary",
        )
        self.runtime.fail_load = "INFERENCE_RUNTIME_UNAVAILABLE"
        with self.assertRaises(InferenceDeploymentError):
            self.service.start(self.db, deployment.id)
        self.db.refresh(deployment)
        self.assertEqual(deployment.observed_state, "failed")
        self.assertEqual(deployment.last_error_code, "INFERENCE_RUNTIME_UNAVAILABLE")
        self.runtime.fail_load = None
        self.assertEqual(self.service.start(self.db, deployment.id).observed_state, "running")

    def test_reconcile_reloads_desired_running_after_runtime_restart(self):
        deployment = self.service.create(
            self.db, project_id=self.project.id, version_id=self.version.id,
            actor_id=self.user.id, name="primary",
        )
        self.service.start(self.db, deployment.id)
        self.runtime.loaded.clear()
        result = self.service.reconcile(self.db)
        self.assertEqual(result, {"loaded": 1, "unloaded": 0, "failed": 0})
        self.assertIn(str(deployment.id), self.runtime.loaded)


class _AnomalyRuntime:
    """解析式 fake：anomaly_score = f0（probabilities=-score，ONNX 方向）；f1 无关。"""

    def __init__(self):
        self.calls = 0

    def predict(self, deployment_id, records):
        self.calls += 1
        scores = [float(record["f0"]) for record in records]
        return {
            "predictions": [-1 if score > 0.5 else 1 for score in scores],
            "probabilities": [-score for score in scores],
            "duration_ms": 1,
        }


class TestAnomalyEnrichment(unittest.TestCase):
    """无监督三要素映射 + 扰动归因（技术方案 §3.5，共享函数合同）。"""

    def test_maps_triad_and_attributes_single_row(self):
        from app.services.inference_deployment import anomaly_predict_enrichment

        runtime = _AnomalyRuntime()
        version = type("Version", (), {
            "feature_schema": [
                {"name": "f0", "dtype": "float64"},
                {"name": "f1", "dtype": "float64"},
            ],
            "output_schema": {"name": "anomaly", "dtype": "float64", "task": "anomaly"},
        })()
        result = {"predictions": [1], "probabilities": [-2.0], "duration_ms": 1}
        enriched = anomaly_predict_enrichment(
            runtime, "key", [{"f0": 2.0, "f1": 5.0}], result,
            feature_schema=version.feature_schema, output_schema=version.output_schema,
        )
        # ONNX scores（正=正常）取负 → anomaly_score；label=1（score>0.5）→ False
        self.assertEqual(enriched["anomaly_score"], [2.0])
        self.assertEqual(enriched["is_anomaly"], [False])
        top = enriched["top_contributors"]
        self.assertEqual(top[0]["feature"], "f0")
        # f0 贡献解析值恰为 1.0：score(x+δ)-score(x-δ) = 2δ
        self.assertAlmostEqual(float(top[0]["contribution"]), 1.0, places=6)
        self.assertAlmostEqual(float(top[1]["contribution"]), 0.0, places=6)
        # 中心差分 = 每特征 2 次扰动调用（基线 result 由调用方传入，不计数）
        self.assertEqual(runtime.calls, 4)

    def test_batch_rows_skip_attribution_and_non_anomaly_passthrough(self):
        from app.services.inference_deployment import anomaly_predict_enrichment

        runtime = _AnomalyRuntime()
        version = type("Version", (), {
            "feature_schema": [{"name": "f0", "dtype": "float64"}],
            "output_schema": {"task": "anomaly"},
        })()
        batch = anomaly_predict_enrichment(
            runtime, "key", [{"f0": 1.0}, {"f0": 2.0}],
            {"predictions": [1, -1], "probabilities": [-1.0, -2.0]},
            feature_schema=version.feature_schema, output_schema=version.output_schema,
        )
        self.assertEqual(batch["anomaly_score"], [1.0, 2.0])
        self.assertEqual(batch["is_anomaly"], [False, True])
        self.assertNotIn("top_contributors", batch)

        supervised = anomaly_predict_enrichment(
            _AnomalyRuntime(), "key", [{"f0": 1.0}],
            {"predictions": [1]},
            feature_schema=version.feature_schema, output_schema={"task": "classification"},
        )
        self.assertNotIn("anomaly_score", supervised)


if __name__ == "__main__":
    unittest.main()
