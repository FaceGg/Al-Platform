"""Closed-loop demo regression tests: config, per-row predict, error dataset,
threshold alert, review skip path, retrain trigger with a stubbed dispatcher."""

import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, ".")

import joblib
import pandas as pd
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

from app.database import Base, SessionLocal, engine
from app.main import app
from app.api.auth import pwd_context
from app.models.artifact import Artifact
from app.models.demo_loop import DemoLoopConfig, DemoLoopEvent
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
from app.models.notifications import InAppNotification
from app.models.training import TrainingJob
from app.models.user import User
from app.services import demo_loop as demo_loop_module
from app.services.artifact_service import build_artifact_service

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def ensure_admin():
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == "admin").first() is None:
            db.add(User(
                username="admin",
                password_hash=pwd_context.hash("admin123"),
                role="admin",
            ))
            db.commit()
    finally:
        db.close()


def login(username="admin", password="admin123"):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class _StubDispatcher:
    def __init__(self):
        self.enqueued = []
        self.started = []

    def enqueue(self, job_id):
        self.enqueued.append(str(job_id))
        return f"local:stub-{len(self.enqueued)}"

    def start(self, task_id):
        self.started.append(task_id)


class DemoLoopFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()
        db = SessionLocal()
        try:
            cls.user_id = db.query(User).filter(User.username == "admin").one().id
        finally:
            db.close()

        r = client.post("/api/projects", json={
            "name": f"demo-loop-{uuid.uuid4().hex[:8]}",
            "description": "closed-loop demo tests",
        }, headers=cls.h)
        assert r.status_code == 201, r.text
        cls.project_id = r.json()["id"]

        cls.features = ["f1", "f2"]
        frame = pd.DataFrame({
            "f1": [0.0, 0.2, 0.1, 0.3, 0.15, 5.0, 5.4, 4.8, 5.2, 5.1],
            "f2": [1.0, 1.2, 0.9, 1.1, 1.05, -1.0, -1.2, -0.9, -1.1, -1.0],
        })
        model = LogisticRegression().fit(frame, [0, 0, 0, 0, 0, 1, 1, 1, 1, 1])
        db = SessionLocal()
        try:
            service = build_artifact_service(db)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "toy_model.joblib"
                joblib.dump(model, path)
                artifact = service.create_from_file(
                    uuid.UUID(cls.project_id), path, f"toy-model-{uuid.uuid4().hex[:6]}",
                    "model", metadata={"source": "test"},
                )
            registered = RegisteredModel(
                project_id=uuid.UUID(cls.project_id),
                name=f"toy-model-{uuid.uuid4().hex[:6]}",
                created_by_id=cls.user_id,
            )
            db.add(registered)
            db.flush()
            version = ModelVersion(
                registered_model_id=registered.id,
                version_number=1,
                source_kind="onnx_artifact",
                source_artifact_id=artifact.id,
                onnx_artifact_id=artifact.id,
                framework="sklearn",
                feature_schema=cls.features,
                lifecycle_state="enabled",
                approval_status="approved",
            )
            db.add(version)
            db.flush()
            deployment = InferenceDeployment(
                project_id=uuid.UUID(cls.project_id),
                name=f"toy-deploy-{uuid.uuid4().hex[:6]}",
                model_version_id=version.id,
                desired_state="running",
                observed_state="running",
                created_by_id=cls.user_id,
            )
            db.add(deployment)
            db.commit()
            cls.deployment_id = str(deployment.id)
            cls.model_version_id = str(version.id)
        finally:
            db.close()

    # ---------------------------------------------------------------- helpers

    def _config_url(self):
        return f"/api/projects/{self.project_id}/demo-loop/config"

    def _save_config(self, **overrides):
        payload = {
            "name": "闭环演示",
            "deployment_id": self.deployment_id,
            "error_classes": ["1"],
            "alert_threshold_rows": 2,
            "preprocess_enabled": True,
        }
        payload.update(overrides)
        r = client.put(self._config_url(), json=payload, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _predict(self, record):
        r = client.post(
            f"/api/projects/{self.project_id}/demo-loop/predict",
            json={"record": record},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ------------------------------------------------------------------ tests

    def test_01_config_requires_deployment_in_project(self):
        r = client.put(self._config_url(), json={
            "deployment_id": str(uuid.uuid4()),
            "error_classes": ["1"],
        }, headers=self.h)
        self.assertEqual(r.status_code, 404, r.text)

    def test_02_status_404_without_config(self):
        project = f"demo-loop-empty-{uuid.uuid4().hex[:8]}"
        r = client.post("/api/projects", json={"name": project}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        empty_id = r.json()["id"]
        r = client.get(f"/api/projects/{empty_id}/demo-loop/status", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_03_predict_ok_row_not_appended(self):
        self._save_config()
        data = self._predict({"f1": 0.1, "f2": 1.0})
        self.assertFalse(data["error_matched"])
        self.assertFalse(data["appended"])
        self.assertEqual(data["error_count"], 0)

    def test_04_error_rows_append_alert_and_reset(self):
        self._save_config(alert_threshold_rows=2)
        first = self._predict({"f1": 5.0, "f2": -1.0})
        self.assertTrue(first["error_matched"])
        self.assertTrue(first["appended"])
        self.assertEqual(first["error_count"], 1)
        self.assertEqual(first["alert_count"], 0)

        second = self._predict({"f1": 5.2, "f2": -1.1})
        self.assertEqual(second["error_count"], 2)
        self.assertEqual(second["alert_count"], 1)

        status = client.get(
            f"/api/projects/{self.project_id}/demo-loop/status", headers=self.h,
        ).json()
        self.assertEqual(status["error_count"], 2)
        self.assertEqual(status["alert_count"], 1)
        types = [event["event_type"] for event in status["events"]]
        self.assertIn("error_appended", types)
        self.assertIn("alert_triggered", types)
        self.assertIsNotNone(status["error_artifact"])
        self.assertGreaterEqual(status["error_artifact"]["row_count"], 2)

        db = SessionLocal()
        try:
            notifications = db.query(InAppNotification).filter(
                InAppNotification.event_type == "demo_loop.alert",
                InAppNotification.project_id == uuid.UUID(self.project_id),
            ).count()
            self.assertGreaterEqual(notifications, 1)
            config = db.query(DemoLoopConfig).filter(
                DemoLoopConfig.project_id == uuid.UUID(self.project_id),
            ).order_by(DemoLoopConfig.created_at.asc()).first()
            artifact = db.query(Artifact).filter(Artifact.id == config.error_artifact_id).one()
            self.assertEqual(artifact.type, "dataset")
        finally:
            db.close()

        r = client.post(
            f"/api/projects/{self.project_id}/demo-loop/reset", headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["error_count"], 0)
        self.assertEqual(r.json()["alert_count"], 0)

    def test_05_review_skipped_without_annotators(self):
        self._save_config(alert_threshold_rows=1, require_review=True)
        self._predict({"f1": 5.0, "f2": -1.0})
        status = client.get(
            f"/api/projects/{self.project_id}/demo-loop/status", headers=self.h,
        ).json()
        types = [event["event_type"] for event in status["events"]]
        self.assertIn("review_skipped", types)

    def test_06_retrain_trigger_with_stub_dispatcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "retrain.csv"
            pd.DataFrame({
                "f1": [0.0, 0.2, 0.1, 0.3, 0.15, 5.0, 5.4, 4.8, 5.2, 5.1],
                "f2": [1.0, 1.2, 0.9, 1.1, 1.05, -1.0, -1.2, -0.9, -1.1, -1.0],
                "label": [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            }).to_csv(path, index=False)
            db = SessionLocal()
            try:
                service = build_artifact_service(db)
                artifact = service.create_dataset(
                    uuid.UUID(self.project_id), path, f"retrain-src-{uuid.uuid4().hex[:6]}",
                )
                retrain_dataset_id = str(artifact.id)
            finally:
                db.close()

        self._save_config(
            alert_threshold_rows=5,
            retrain_enabled=True,
            retrain_threshold_rows=3,
            retrain_target_column="label",
            retrain_dataset_artifact_id=retrain_dataset_id,
            retrain_max_trials=6,
        )
        # Prior tests leave error_count at 1; first row reaches 2 (below 3): idle.
        self._predict({"f1": 5.0, "f2": -1.0})
        status = client.get(
            f"/api/projects/{self.project_id}/demo-loop/status", headers=self.h,
        ).json()
        self.assertEqual(status["retrain_status"], "idle")

        stub = _StubDispatcher()
        # The trigger registers the experiment with the real tracking backend;
        # point that at an isolated sqlite store for the test process.
        with patch("app.services.experiment_tracking.resolve_tracking_configuration",
                   return_value=("sqlite:///./temp_test/ut_mlflow_tracking.db",
                                 "file:./temp_test/ut_mlflow_artifacts")), \
                patch("app.services.closed_loop_actions.automl_dispatcher", return_value=stub):
            self._predict({"f1": 5.4, "f2": -1.2})

        self.assertEqual(len(stub.enqueued), 1)
        # enqueue alone must not be the end: the local dispatcher needs an
        # explicit start(task_id), otherwise the job sits pending forever.
        self.assertEqual(len(stub.started), 1)
        db = SessionLocal()
        try:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(stub.enqueued[0]),
            ).one()
            self.assertEqual(job.operator_id, "automl")
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.params["search_contract"], "optuna_v1")
            self.assertEqual(job.automl_contract["target_columns"], ["label"])
        finally:
            db.close()
        status = client.get(
            f"/api/projects/{self.project_id}/demo-loop/status", headers=self.h,
        ).json()
        self.assertEqual(status["retrain_status"], "queued")
        types = [event["event_type"] for event in status["events"]]
        self.assertIn("retrain_triggered", types)

    def test_07_swap_uses_best_candidate_and_updates_deployment(self):
        db = SessionLocal()
        try:
            config = db.query(DemoLoopConfig).filter(
                DemoLoopConfig.project_id == uuid.UUID(self.project_id),
            ).order_by(DemoLoopConfig.created_at.asc()).first()
            job_id = config.retrain_job_id
            service = demo_loop_module.DemoLoopService(db)
            job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
            deployment = db.query(InferenceDeployment).filter(
                InferenceDeployment.id == config.deployment_id,
            ).one()
            existing_version_id = deployment.model_version_id
            candidates = [
                {"candidate_id": "c-low", "name": "weak", "metrics": {"accuracy": 0.4}},
                {"candidate_id": "c-best", "name": "strong", "metrics": {"accuracy": 0.93}},
            ]

            class _FakeVersion:
                # Reuse the existing model version id so the FK on
                # deployment.model_version_id stays satisfiable.
                id = existing_version_id
                version_number = 1
                approval_status = "pending"

            class _FakeRegistry:
                def __init__(self, *_args, **_kwargs):
                    pass

                def list_registerable_candidates(self, _db, _task_id):
                    return candidates

                def register_automl_candidate(self, _db, **kwargs):
                    self.kwargs = kwargs
                    return _FakeVersion(), True

                def transition_model_version(self, _db, version_id, _action, _actor_id, **_kwargs):
                    self.approved = version_id
                    return _FakeVersion()

            # The swap logic lives in closed_loop_actions now.
            with patch("app.services.closed_loop_actions.ModelRegistryService", _FakeRegistry):
                service._swap_to_best_model(config, job, self.user_id)
            db.commit()

            self.assertIsNotNone(config.swapped_model_version_id)
            self.assertEqual(service._candidate_score(candidates[1]), 0.93)
            status = client.get(
                f"/api/projects/{self.project_id}/demo-loop/status", headers=self.h,
            ).json()
            types = [event["event_type"] for event in status["events"]]
            self.assertIn("model_swapped", types)
        finally:
            db.close()

    def test_07b_second_completed_job_swaps_again(self):
        # 回归：swapped_model_version_id 是前端换模水印，不能当 once-ever
        # 守卫；真实多周期闭环要求每个完成任务都能再次触发换模。
        db = SessionLocal()
        try:
            config = db.query(DemoLoopConfig).filter(
                DemoLoopConfig.project_id == uuid.UUID(self.project_id),
            ).order_by(DemoLoopConfig.created_at.asc()).first()
            job = db.query(TrainingJob).filter(TrainingJob.id == config.retrain_job_id).one()
            service = demo_loop_module.DemoLoopService(db)

            class _FakeVersion:
                id = uuid.uuid4()
                version_number = 2

            with patch(
                "app.services.demo_loop.complete_retrain_swap",
                return_value=_FakeVersion(),
            ) as swap:
                service._swap_to_best_model(config, job, self.user_id)
            db.commit()

            self.assertEqual(swap.call_count, 1)
            self.assertEqual(config.swapped_model_version_id, _FakeVersion.id)
        finally:
            db.close()

    def test_07c_swap_rotates_stable_revision_target(self):
        # 回归：运行时规格与路由按最新 stable revision 的 target 取模，且
        # revision 不可变；换模必须轮换 revision，否则运行时永远加载旧模型。
        db = SessionLocal()
        try:
            from app.models.model_registry import DeploymentRevision, DeploymentTarget

            config = db.query(DemoLoopConfig).filter(
                DemoLoopConfig.project_id == uuid.UUID(self.project_id),
            ).order_by(DemoLoopConfig.created_at.asc()).first()
            job = db.query(TrainingJob).filter(TrainingJob.id == config.retrain_job_id).one()
            deployment = db.query(InferenceDeployment).filter(
                InferenceDeployment.id == config.deployment_id,
            ).one()
            new_version_id = deployment.model_version_id
            # stable 先指向一个陈旧版本，换入 new_version_id 时必须轮换。
            current = db.query(ModelVersion).filter(
                ModelVersion.id == new_version_id,
            ).one()
            stale_version = ModelVersion(
                registered_model_id=current.registered_model_id,
                version_number=90,
                source_kind="onnx_artifact",
                source_artifact_id=current.source_artifact_id,
                onnx_artifact_id=current.onnx_artifact_id,
                framework="onnx",
                feature_schema=[],
                approval_status="approved",
            )
            db.add(stale_version)
            db.flush()
            latest = db.query(DeploymentRevision.revision_number).filter(
                DeploymentRevision.deployment_id == deployment.id,
            ).order_by(DeploymentRevision.revision_number.desc()).first()
            old_revision = DeploymentRevision(
                deployment_id=deployment.id,
                revision_number=(int(latest[0]) if latest else 0) + 1,
                strategy="immediate",
                status="stable",
            )
            db.add(old_revision)
            db.flush()
            db.add(DeploymentTarget(
                revision_id=old_revision.id,
                model_version_id=stale_version.id,
                weight_bps=10000,
                role="stable",
            ))
            db.commit()

            class _FakeVersion:
                # 复用既有版本 id，满足 target.model_version_id 的外键约束。
                id = new_version_id
                version_number = 1
                approval_status = "pending"

            class _FakeRegistry:
                def __init__(self, *_args, **_kwargs):
                    pass

                def list_registerable_candidates(self, _db, _task_id):
                    return [{"candidate_id": "c-best", "name": "strong",
                             "metrics": {"accuracy": 0.9}}]

                def register_automl_candidate(self, _db, **_kwargs):
                    return _FakeVersion(), True

                def transition_model_version(self, _db, version_id, _action, _actor_id, **_kwargs):
                    return _FakeVersion()

            service = demo_loop_module.DemoLoopService(db)
            with patch(
                "app.services.closed_loop_actions.ModelRegistryService", _FakeRegistry,
            ):
                service._swap_to_best_model(config, job, self.user_id)
            db.commit()

            db.refresh(old_revision)
            self.assertEqual(old_revision.status, "superseded")
            stable = db.query(DeploymentRevision).filter(
                DeploymentRevision.deployment_id == deployment.id,
                DeploymentRevision.status == "stable",
            ).order_by(DeploymentRevision.revision_number.desc()).first()
            self.assertIsNotNone(stable)
            self.assertGreater(stable.revision_number, old_revision.revision_number)
            targets = list(stable.targets or ())
            self.assertEqual(len(targets), 1)
            self.assertEqual(targets[0].model_version_id, new_version_id)
            self.assertEqual(targets[0].weight_bps, 10000)
        finally:
            db.close()

    def test_08_predict_prefers_inference_runtime(self):
        calls = []

        class _StubRuntime:
            def predict(self, runtime_key, records):
                calls.append({"runtime_key": runtime_key, "records": records})
                return {"predictions": [[1]], "probabilities": [[0.3, 0.7]]}

        class _StubService:
            runtime = _StubRuntime()

        self._save_config(alert_threshold_rows=100, preprocess_enabled=False)
        from types import SimpleNamespace
        router = SimpleNamespace(revision_id="rev-1", model_version_id=uuid.UUID(self.model_version_id))
        with patch.object(demo_loop_module, "WeightedTargetRouter") as router_cls, \
                patch.object(demo_loop_module, "_deployment_service", return_value=_StubService()):
            router_cls.return_value.select_active.return_value = router
            data = self._predict({"f1": 5.1, "f2": -1.05, "extra": "ignored"})

        self.assertEqual(len(calls), 1)
        # Only the model's feature columns reach the runtime, as numbers.
        self.assertEqual(calls[0]["records"], [{"f1": 5.1, "f2": -1.05}])
        self.assertTrue(data["error_matched"])
        self.assertEqual(data["confidence"], 0.7)
        self.assertIn(":", calls[0]["runtime_key"])

    def test_09_non_numeric_feature_is_rejected_not_500(self):
        class _StubRuntime:
            def predict(self, runtime_key, records):
                return {"predictions": [[0]]}

        class _StubService:
            runtime = _StubRuntime()

        self._save_config(alert_threshold_rows=100, preprocess_enabled=False)
        from types import SimpleNamespace
        router = SimpleNamespace(revision_id="rev-1", model_version_id=uuid.UUID(self.model_version_id))
        with patch.object(demo_loop_module, "WeightedTargetRouter") as router_cls, \
                patch.object(demo_loop_module, "_deployment_service", return_value=_StubService()):
            router_cls.return_value.select_active.return_value = router
            r = client.post(
                f"/api/projects/{self.project_id}/demo-loop/predict",
                json={"record": {"f1": "abc", "f2": 1.0}},
                headers=self.h,
            )
        self.assertEqual(r.status_code, 422, r.text)
        self.assertEqual(r.json()["detail"]["code"], "DEMO_LOOP_RECORD_INVALID")

    def _runtime_patches(self, stub_service):
        from types import SimpleNamespace
        router = SimpleNamespace(revision_id="rev-1", model_version_id=uuid.UUID(self.model_version_id))
        router_patch = patch.object(demo_loop_module, "WeightedTargetRouter")
        service_patch = patch.object(demo_loop_module, "_deployment_service", return_value=stub_service)
        return router_patch, service_patch, router

    def test_10_feature_engineering_fills_missing_columns(self):
        captured = []

        class _StubRuntime:
            def predict(self, runtime_key, records):
                captured.append(records)
                return {"predictions": [[1]], "probabilities": [[0.1, 0.9]]}

        class _StubService:
            runtime = _StubRuntime()

        def fake_build_feature_frame(frame):
            assert list(frame.columns) == ["wld1c", "wld2c"]
            engineered = pd.DataFrame([{**{name: 1.5 for name in demo_loop_module.REPORT_TABLE_FIELDS},
                                        "f1": 4.9, "f2": -0.8, "current_ratio": 2.0}])
            return engineered, ["f1", "f2", "current_ratio"], {}

        self._save_config(alert_threshold_rows=100, preprocess_enabled=True)
        router_patch, service_patch, router = self._runtime_patches(_StubService())
        with router_patch as router_cls, service_patch, \
                patch.object(demo_loop_module, "build_fixed_feature_frame", fake_build_feature_frame):
            router_cls.return_value.select_active.return_value = router
            data = self._predict({"wld1c": 1.0, "wld2c": 1.0})

        self.assertEqual(len(captured), 1)
        # Engineered columns are merged and only model features reach the runtime.
        self.assertEqual(captured[0], [{"f1": 4.9, "f2": -0.8}])
        self.assertTrue(data["error_matched"])

    def test_11_missing_features_without_engineering_gives_guidance(self):
        class _StubRuntime:
            def predict(self, runtime_key, records):
                return {"predictions": [[0]]}

        class _StubService:
            runtime = _StubRuntime()

        self._save_config(alert_threshold_rows=100, preprocess_enabled=False)
        router_patch, service_patch, router = self._runtime_patches(_StubService())
        with router_patch as router_cls, service_patch:
            router_cls.return_value.select_active.return_value = router
            r = client.post(
                f"/api/projects/{self.project_id}/demo-loop/predict",
                json={"record": {"wld1c": 1.0, "wld2c": 1.0}},
                headers=self.h,
            )
        self.assertEqual(r.status_code, 422, r.text)
        detail = r.json()["detail"]
        self.assertEqual(detail["code"], "DEMO_LOOP_RECORD_INVALID")
        self.assertIn("自动特征工程", detail["message"])

    def test_12_engineering_failure_reports_required_columns(self):
        class _StubRuntime:
            def predict(self, runtime_key, records):
                return {"predictions": [[0]]}

        class _StubService:
            runtime = _StubRuntime()

        self._save_config(alert_threshold_rows=100, preprocess_enabled=True)
        router_patch, service_patch, router = self._runtime_patches(_StubService())
        with router_patch as router_cls, service_patch, \
                patch.object(demo_loop_module, "build_fixed_feature_frame", side_effect=ValueError("no waveforms")):
            router_cls.return_value.select_active.return_value = router
            r = client.post(
                f"/api/projects/{self.project_id}/demo-loop/predict",
                json={"record": {"wld1c": 1.0, "wld2c": 1.0}},
                headers=self.h,
            )
        self.assertEqual(r.status_code, 422, r.text)
        detail = r.json()["detail"]
        self.assertEqual(detail["code"], "DEMO_LOOP_RECORD_INVALID")
        self.assertIn("cvei", detail["message"])

    def test_13_partial_config_update_keeps_existing_flags(self):
        # The page form always sends every field, but API callers may send a
        # subset: omitted flags must keep their stored value instead of being
        # silently reset to False.
        self._save_config(alert_threshold_rows=3, preprocess_enabled=True)
        r = client.put(self._config_url(), json={"name": "闭环演示"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["preprocess_enabled"])

    def test_14_review_chain_creates_task_and_assignment(self):
        # Full review chain with a REAL annotator: alert → task (assignable
        # status) → label schema → scope samples → assignment rows. This
        # caught the draft-status and string-vs-UUID regressions before.
        from app.models.annotator import AnnotatorAccount, ProjectAnnotatorGrant
        from app.models.labeling import AnnotationAssignment
        from app.models.platform_models import GenericAnnotationTask

        db = SessionLocal()
        try:
            annotator = AnnotatorAccount(
                username=f"annotator-{uuid.uuid4().hex[:8]}",
                password_hash=pwd_context.hash("x"),
                status="active",
            )
            db.add(annotator)
            db.flush()
            subject_id = str(annotator.subject_id)
            db.add(ProjectAnnotatorGrant(
                project_id=uuid.UUID(self.project_id),
                subject_id=annotator.subject_id,
                status="active",
            ))
            db.commit()
        finally:
            db.close()

        self._save_config(alert_threshold_rows=1, require_review=True,
                          review_annotator_ids=[subject_id])
        self._predict({"f1": 5.0, "f2": -1.0})

        db = SessionLocal()
        try:
            task = db.query(GenericAnnotationTask).filter(
                GenericAnnotationTask.project_id == uuid.UUID(self.project_id),
                GenericAnnotationTask.name.contains("人工审核"),
            ).one()
            self.assertEqual(task.status, "awaiting_annotation")
            assignment = db.query(AnnotationAssignment).filter(
                AnnotationAssignment.task_id == task.id,
            ).one()
            self.assertEqual(str(assignment.annotator_subject_id), subject_id)
        finally:
            db.close()

    def test_15_loop_task_crud(self):
        # 闭环支持多任务：创建/列表/修改/删除。
        r = client.post(
            f"/api/projects/{self.project_id}/demo-loop/loops",
            json={
                "name": "夜间闭环", "deployment_id": self.deployment_id,
                "error_classes": ["3"], "alert_threshold_rows": 5,
            },
            headers=self.h,
        )
        self.assertEqual(r.status_code, 201, r.text)
        loop = r.json()
        self.assertEqual(loop["name"], "夜间闭环")
        self.assertEqual(loop["error_classes"], ["3"])

        r = client.get(f"/api/projects/{self.project_id}/demo-loop/loops", headers=self.h)
        items = r.json()["items"]
        self.assertIn(loop["id"], [item["id"] for item in items])
        self.assertTrue(all("error_count" in item and "retrain_status" in item for item in items))

        r = client.put(
            f"/api/projects/{self.project_id}/demo-loop/loops/{loop['id']}",
            json={"name": "白天闭环", "alert_threshold_rows": 7},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["name"], "白天闭环")
        self.assertEqual(r.json()["alert_threshold_rows"], 7)
        # 部分修改不清洗未提及的类别
        self.assertEqual(r.json()["error_classes"], ["3"])

        r = client.delete(
            f"/api/projects/{self.project_id}/demo-loop/loops/{loop['id']}",
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "deleted")
        r = client.get(f"/api/projects/{self.project_id}/demo-loop/loops", headers=self.h)
        self.assertNotIn(loop["id"], [item["id"] for item in r.json()["items"]])
        r = client.delete(
            f"/api/projects/{self.project_id}/demo-loop/loops/{loop['id']}",
            headers=self.h,
        )
        self.assertEqual(r.status_code, 404)

    def test_16_loop_scoped_predict_status_reset_and_event_cleanup(self):
        from types import SimpleNamespace

        loop = client.post(
            f"/api/projects/{self.project_id}/demo-loop/loops",
            json={
                "name": " Scoped 闭环", "deployment_id": self.deployment_id,
                "error_classes": ["1"], "alert_threshold_rows": 100,
            },
            headers=self.h,
        ).json()
        loop_id = loop["id"]
        try:
            class _StubRuntime:
                def predict(self, runtime_key, records):
                    return {"predictions": [[1]], "probabilities": [[0.2, 0.8]]}

            class _StubService:
                runtime = _StubRuntime()

            router = SimpleNamespace(revision_id="rev-1", model_version_id=uuid.UUID(self.model_version_id))
            with patch.object(demo_loop_module, "WeightedTargetRouter") as router_cls, \
                    patch.object(demo_loop_module, "_deployment_service", return_value=_StubService()):
                router_cls.return_value.select_active.return_value = router
                r = client.post(
                    f"/api/projects/{self.project_id}/demo-loop/loops/{loop_id}/predict",
                    json={"record": {"f1": 5.1, "f2": -1.05}},
                    headers=self.h,
                )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(r.json()["error_matched"])

            r = client.get(
                f"/api/projects/{self.project_id}/demo-loop/loops/{loop_id}/status",
                headers=self.h,
            )
            self.assertEqual(r.status_code, 200, r.text)
            status = r.json()
            self.assertEqual(status["config_id"], loop_id)
            self.assertEqual(status["error_count"], 1)

            db = SessionLocal()
            try:
                events = db.query(DemoLoopEvent).filter(DemoLoopEvent.config_id == uuid.UUID(loop_id)).all()
                self.assertGreaterEqual(len(events), 1)
            finally:
                db.close()

            r = client.post(
                f"/api/projects/{self.project_id}/demo-loop/loops/{loop_id}/reset",
                json={}, headers=self.h,
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["error_count"], 0)
        finally:
            # 删除任务并校验事件级联清除
            r = client.delete(
                f"/api/projects/{self.project_id}/demo-loop/loops/{loop_id}",
                headers=self.h,
            )
            self.assertEqual(r.status_code, 200, r.text)
            db = SessionLocal()
            try:
                remaining = db.query(DemoLoopEvent).filter(DemoLoopEvent.config_id == uuid.UUID(loop_id)).count()
                self.assertEqual(remaining, 0)
            finally:
                db.close()

    def test_17_multi_dataset_retrain_with_auto_labeled_reflow(self):
        # 回归：重训数据集支持多选合并；回流行无人工标签时用推理结果自动
        # 补齐（回流数据集可以单独/混合选入重训），同时 total_count 计数。
        client.post(f"/api/projects/{self.project_id}/demo-loop/reset", json={}, headers=self.h)
        with tempfile.TemporaryDirectory() as tmp:
            base_path = Path(tmp) / "base.csv"
            pd.DataFrame({
                "f1": [0.0, 0.2, 0.1, 0.3, 0.15, 5.0, 5.4, 4.8, 5.2, 5.1],
                "f2": [1.0, 1.2, 0.9, 1.1, 1.05, -1.0, -1.2, -0.9, -1.1, -1.0],
                "label": [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
            }).to_csv(base_path, index=False)
            # 模拟回流数据集：只有特征 + prediction 列，没有人工标签列。
            reflow_path = Path(tmp) / "reflow.csv"
            pd.DataFrame({
                "f1": [5.6, 4.9],
                "f2": [-1.05, -0.95],
                "prediction": [1, 1],
                "confidence": [0.9, 0.85],
            }).to_csv(reflow_path, index=False)
            db = SessionLocal()
            try:
                service = build_artifact_service(db)
                base_art = service.create_dataset(
                    uuid.UUID(self.project_id), base_path, f"multi-base-{uuid.uuid4().hex[:6]}")
                reflow_art = service.create_dataset(
                    uuid.UUID(self.project_id), reflow_path, f"multi-reflow-{uuid.uuid4().hex[:6]}")
                base_id, reflow_id = str(base_art.id), str(reflow_art.id)
            finally:
                db.close()

        r = client.put(self._config_url(), json={
            "deployment_id": self.deployment_id,
            "error_classes": ["1"],
            "require_review": False,
            "review_annotator_ids": [],
            "alert_threshold_rows": 50,
            "retrain_enabled": True,
            "retrain_threshold_rows": 3,
            "retrain_target_column": "label",
            "retrain_dataset_artifact_ids": [base_id, reflow_id],
        }, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["retrain_dataset_artifact_ids"], [base_id, reflow_id])

        class _StubRuntime:
            def predict(self, runtime_key, records):
                return {"predictions": [[1]], "probabilities": [[0.2, 0.8]]}

        class _StubService:
            runtime = _StubRuntime()

        stub = _StubDispatcher()
        from types import SimpleNamespace
        router = SimpleNamespace(revision_id="rev-1", model_version_id=uuid.UUID(self.model_version_id))
        with patch("app.services.experiment_tracking.resolve_tracking_configuration",
                   return_value=("sqlite:///./temp_test/ut_mlflow_tracking.db",
                                 "file:./temp_test/ut_mlflow_artifacts")), \
                patch("app.services.closed_loop_actions.automl_dispatcher", return_value=stub), \
                patch.object(demo_loop_module, "WeightedTargetRouter") as router_cls, \
                patch.object(demo_loop_module, "_deployment_service", return_value=_StubService()):
            router_cls.return_value.select_active.return_value = router
            first = client.post(
                f"/api/projects/{self.project_id}/demo-loop/predict",
                json={"record": {"f1": 5.2, "f2": -1.1}}, headers=self.h,
            )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["total_count"], 1)

        # 回流行自动带标签列：回流工件出现 label=1。
        db = SessionLocal()
        try:
            config = db.query(DemoLoopConfig).filter(
                DemoLoopConfig.project_id == uuid.UUID(self.project_id),
            ).order_by(DemoLoopConfig.created_at.asc()).first()
            art = db.query(Artifact).filter(Artifact.id == config.error_artifact_id).one()
            svc = build_artifact_service(db)
            with svc.storage.materialize(art.storage_uri) as path:
                reflow = pd.read_csv(path)
            self.assertIn("label", reflow.columns)
            self.assertEqual(reflow.iloc[-1]["label"], 1)
            self.assertIn("prediction", reflow.columns)
        finally:
            db.close()

        # 报错数据积累到阈值触发重训：合并两个数据集，标签自动补齐，
        # prediction/confidence 不进特征列。
        stub2 = _StubDispatcher()
        with patch("app.services.experiment_tracking.resolve_tracking_configuration",
                   return_value=("sqlite:///./temp_test/ut_mlflow_tracking.db",
                                 "file:./temp_test/ut_mlflow_artifacts")), \
                patch("app.services.closed_loop_actions.automl_dispatcher", return_value=stub2), \
                patch.object(demo_loop_module, "WeightedTargetRouter") as router_cls, \
                patch.object(demo_loop_module, "_deployment_service", return_value=_StubService()):
            router_cls.return_value.select_active.return_value = router
            for _ in range(2):
                client.post(
                    f"/api/projects/{self.project_id}/demo-loop/predict",
                    json={"record": {"f1": 5.0, "f2": -1.0}}, headers=self.h,
                )
        self.assertEqual(len(stub2.enqueued), 1)
        db = SessionLocal()
        try:
            job = db.query(TrainingJob).filter(
                TrainingJob.id == uuid.UUID(stub2.enqueued[0]),
            ).one()
            # 多选时训练输入是物化后的合并数据集（含自动补齐标签），
            # 不是第一个原始数据集。
            self.assertNotEqual(str(job.dataset_artifact_id), base_id)
            merged = db.query(Artifact).filter(Artifact.id == job.dataset_artifact_id).one()
            self.assertIn("合并数据集", merged.name)
            svc = build_artifact_service(db)
            with svc.materialize(merged.id, merged.project_id, expected_type="dataset") as p:
                merged_frame = pd.read_csv(p)
            self.assertEqual(len(merged_frame), 12)  # 10 基础 + 2 回流
            self.assertIn("label", merged_frame.columns)
            self.assertNotIn("prediction", merged_frame.columns)
            self.assertNotIn("confidence", merged_frame.columns)
            self.assertEqual(set(job.params["input_columns"]), {"f1", "f2"})
            self.assertEqual(job.automl_contract["target_columns"], ["label"])
        finally:
            db.close()
        status = client.get(
            f"/api/projects/{self.project_id}/demo-loop/status", headers=self.h,
        ).json()
        self.assertEqual(status["total_count"], 3)
        self.assertEqual(status["error_count"], 3)

    def test_18_duplicate_names_auto_renamed(self):
        # 同项目任务名唯一：重名自动追加 -2/-3，不报错。
        first = client.post(
            f"/api/projects/{self.project_id}/demo-loop/loops",
            json={"name": "巡检闭环", "deployment_id": self.deployment_id,
                  "error_classes": ["1"]},
            headers=self.h,
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()["name"], "巡检闭环")

        second = client.post(
            f"/api/projects/{self.project_id}/demo-loop/loops",
            json={"name": "巡检闭环", "deployment_id": self.deployment_id,
                  "error_classes": ["1"]},
            headers=self.h,
        )
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["name"], "巡检闭环-2")

        third = client.post(
            f"/api/projects/{self.project_id}/demo-loop/loops",
            json={"name": "巡检闭环", "deployment_id": self.deployment_id,
                  "error_classes": ["1"]},
            headers=self.h,
        )
        self.assertEqual(third.json()["name"], "巡检闭环-3")

        # 改名撞已有任务同样自动让名；把自己原名让给自己不受影响。
        renamed = client.put(
            f"/api/projects/{self.project_id}/demo-loop/loops/{first.json()['id']}",
            json={"name": "巡检闭环-2"},
            headers=self.h,
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["name"], "巡检闭环-2-2")

        # 清理本用例创建的任务
        for item in (second, third, renamed):
            client.delete(
                f"/api/projects/{self.project_id}/demo-loop/loops/{item.json()['id']}",
                headers=self.h,
            )


if __name__ == "__main__":
    unittest.main()
