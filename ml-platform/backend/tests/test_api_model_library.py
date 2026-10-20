"""Model Library API integration tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestModelLibraryAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        ensure_admin()
        cls.h = login()
        cls.model_ids = []

    def test_01_list_models_empty(self):
        r = client.get("/api/model-library", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("items", data)
        self.assertIn("total", data)

    def test_02_create_model(self):
        r = client.post("/api/model-library", json={
            "name": "TestXGBoostModel",
            "framework": "xgboost",
            "backbone": "gbtree",
            "description": "Test model for spot welding",
            "version": "v1.0",
            "params": {"max_depth": 6, "n_estimators": 100},
            "tags": ["welding", "classification"],
        }, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        data = r.json()
        self.assertIn("id", data)
        self.__class__.model_ids.append(data["id"])

    def test_03_list_models_has_items(self):
        r = client.get("/api/model-library", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreaterEqual(data["total"], 1)

    def test_04_get_model(self):
        mid = self.model_ids[0]
        r = client.get(f"/api/model-library/{mid}", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["name"], "TestXGBoostModel")
        self.assertEqual(data["framework"], "xgboost")

    def test_05_get_nonexistent_model(self):
        import uuid
        r = client.get(f"/api/model-library/{uuid.uuid4()}", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_06_update_model(self):
        mid = self.model_ids[0]
        r = client.put(f"/api/model-library/{mid}", json={
            "name": "UpdatedXGBoostModel",
            "status": "completed",
            "progress": 1.0,
            "metrics": {"accuracy": 0.95, "mAP": 0.92},
            "is_public": True,
        }, headers=self.h)
        self.assertEqual(r.status_code, 200)

        r = client.get(f"/api/model-library/{mid}", headers=self.h)
        self.assertEqual(r.json()["status"], "completed")

    def test_07_create_second_model(self):
        r = client.post("/api/model-library", json={
            "name": "RandomForestModel",
            "framework": "sklearn",
            "backbone": "random_forest",
            "version": "v1.0",
            "params": {"n_estimators": 200},
        }, headers=self.h)
        self.assertIn(r.status_code, [200, 201])
        self.__class__.model_ids.append(r.json()["id"])

    def test_08_delete_model(self):
        if len(self.model_ids) > 1:
            mid = self.model_ids.pop()
            r = client.delete(f"/api/model-library/{mid}", headers=self.h)
            self.assertEqual(r.status_code, 200)

    def test_09_model_stats(self):
        r = client.get("/api/model-library/stats/summary")
        self.assertIn(r.status_code, [200, 201])
        data = r.json()
        self.assertIn("total_models", data)
        self.assertIn("completed", data)

    def test_10_filter_by_status(self):
        r = client.get("/api/model-library?status=completed", headers=self.h)
        self.assertEqual(r.status_code, 200)

    def test_11_filter_by_framework(self):
        r = client.get("/api/model-library?framework=xgboost", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for item in data["items"]:
            self.assertEqual(item["framework"], "xgboost")

    def test_12_model_requires_auth(self):
        r = client.get("/api/model-library")
        self.assertEqual(r.status_code, 401)

    def test_13_stats_summary_top_models_sorted_by_best_score(self):
        # 回归：metrics 是 JSON 列，SQL 侧 order_by 在 PostgreSQL 直接报
        # "could not identify an ordering operator for type json"（sqlite
        # 按文本排掩盖了问题）。修复后 Python 侧按 best_score 降序。
        import uuid as _uuid

        from app.database import SessionLocal
        from app.models.model_library import ModelLibrary
        from app.models.project import Project
        from app.models.user import User

        marker = f"mlstats-{_uuid.uuid4().hex[:8]}"
        db = SessionLocal()
        try:
            owner_id = db.query(User.id).filter(User.username == "admin").scalar()
            project = Project(name=f"{marker}-project", owner_id=owner_id)
            db.add(project)
            db.flush()
            scores = {"low": 1.0001, "high": 1.0003, "mid": 1.0002}
            for name, score in scores.items():
                db.add(ModelLibrary(
                    project_id=project.id,
                    owner_id=owner_id,
                    name=f"{marker}-{name}",
                    framework="automl",
                    metrics={"best_score": score},
                    status="completed",
                ))
            db.add(ModelLibrary(
                project_id=project.id,
                owner_id=owner_id,
                name=f"{marker}-noscore",
                framework="automl",
                metrics={"f1": 0.9},
                status="completed",
            ))
            db.commit()
        finally:
            db.close()

        r = client.get("/api/model-library/stats/summary")
        self.assertEqual(r.status_code, 200, r.text)
        top = r.json()["top_models"]
        top_names = [item["name"] for item in top]
        self.assertIn(f"{marker}-high", top_names)
        # 共享库中可能存在更高分的真实条目，按标记内相对序断言（best_score 降序；
        # noscore 无 best_score 排在末位，但名称以同一 marker 开头，须一并断言）
        self.assertEqual(
            [name for name in top_names if name.startswith(marker)],
            [f"{marker}-high", f"{marker}-mid", f"{marker}-low", f"{marker}-noscore"],
        )

        r = client.get("/api/dashboard/top-models", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        dash_top = [item["name"] for item in r.json()["items"]]
        self.assertIn(f"{marker}-high", dash_top)
        self.assertEqual(
            [name for name in dash_top if name.startswith(marker)],
            [f"{marker}-high", f"{marker}-mid", f"{marker}-low", f"{marker}-noscore"],
        )

        # 清理
        db = SessionLocal()
        try:
            db.query(ModelLibrary).filter(ModelLibrary.name.like(f"{marker}-%")).delete(
                synchronize_session=False
            )
            db.query(Project).filter(Project.name == f"{marker}-project").delete(
                synchronize_session=False
            )
            db.commit()
        finally:
            db.close()


class TestModelLibraryCascadeDelete(unittest.TestCase):
    """回归：删除已注册的模型库条目。

    model_versions.source_model_library_id 外键无 ondelete，本地 sqlite
    不强制外键而删得掉（留孤儿行），PostgreSQL 提交时 IntegrityError 报
    500。修复后与注册表删除端点同语义：版本被推理部署引用时 409 拒绝，
    否则连带删除版本与变空的注册模型。
    """

    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()

    def _seed(self, db, suffix):
        import uuid as _uuid

        from app.models.artifact import Artifact
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import ModelVersion, RegisteredModel
        from app.models.project import Project
        from app.models.user import User

        admin_id = db.query(User.id).filter(User.username == "admin").scalar()
        project = Project(name=f"casc-{suffix}", owner_id=admin_id)
        db.add(project)
        db.flush()
        model = ModelLibrary(
            id=_uuid.uuid4(), name=f"casc-model-{suffix}", owner_id=admin_id,
            project_id=project.id, version="v1", framework="sklearn", status="completed",
        )
        db.add(model)
        db.flush()
        source_artifact = Artifact(
            project_id=project.id, name=f"casc-{suffix}-src",
            type="model", storage_path=f"casc/{suffix}/src",
        )
        onnx_artifact = Artifact(
            project_id=project.id, name=f"casc-{suffix}-onnx",
            type="model", storage_path=f"casc/{suffix}/onnx",
        )
        db.add_all([source_artifact, onnx_artifact])
        db.flush()
        registered = RegisteredModel(
            project_id=project.id, name=f"casc-rm-{suffix}", created_by_id=admin_id,
        )
        db.add(registered)
        db.flush()
        version = ModelVersion(
            registered_model_id=registered.id, version_number=1,
            source_kind="platform_joblib", source_model_library_id=model.id,
            source_artifact_id=source_artifact.id, onnx_artifact_id=onnx_artifact.id,
            created_by_id=admin_id,
        )
        db.add(version)
        db.commit()
        return project, model, registered, version

    def _cleanup(self, project_id):
        import uuid as _uuid

        from app.database import SessionLocal
        from app.models.artifact import Artifact
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import (
            InferenceDeployment,
            ModelVersion,
            RegisteredModel,
        )
        from app.models.project import Project

        db = SessionLocal()
        try:
            registered_ids = [
                row.id for row in db.query(RegisteredModel.id)
                .filter(RegisteredModel.project_id == project_id).all()
            ]
            db.query(InferenceDeployment).filter(
                InferenceDeployment.project_id == project_id
            ).delete(synchronize_session=False)
            db.query(ModelVersion).filter(
                ModelVersion.registered_model_id.in_(registered_ids)
            ).delete(synchronize_session=False)
            db.query(RegisteredModel).filter(
                RegisteredModel.project_id == project_id
            ).delete(synchronize_session=False)
            db.query(ModelLibrary).filter(
                ModelLibrary.project_id == project_id
            ).delete(synchronize_session=False)
            db.query(Artifact).filter(
                Artifact.project_id == project_id
            ).delete(synchronize_session=False)
            db.query(Project).filter(Project.id == project_id).delete(
                synchronize_session=False
            )
            db.commit()
        finally:
            db.close()

    def test_01_delete_registered_model_cascades(self):
        import uuid as _uuid

        from app.database import SessionLocal
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import ModelVersion, RegisteredModel

        db = SessionLocal()
        try:
            project, model, registered, version = self._seed(db, _uuid.uuid4().hex[:8])
            project_id = project.id
            model_id, registered_id, version_id = model.id, registered.id, version.id
        finally:
            db.close()

        r = client.delete(f"/api/model-library/{model_id}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

        db = SessionLocal()
        try:
            self.assertIsNone(db.query(ModelLibrary).filter(ModelLibrary.id == model_id).first())
            self.assertIsNone(db.query(ModelVersion).filter(ModelVersion.id == version_id).first())
            self.assertIsNone(db.query(RegisteredModel).filter(RegisteredModel.id == registered_id).first())
        finally:
            db.close()
        self._cleanup(project_id)

    def test_02_delete_with_active_deployment_rejected(self):
        import uuid as _uuid

        from app.database import SessionLocal
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import InferenceDeployment, ModelVersion

        db = SessionLocal()
        try:
            suffix = _uuid.uuid4().hex[:8]
            project, model, registered, version = self._seed(db, suffix)
            db.add(InferenceDeployment(
                project_id=project.id, name=f"casc-dep-{suffix}",
                model_version_id=version.id,
            ))
            db.commit()
            project_id = project.id
            model_id, version_id = model.id, version.id
        finally:
            db.close()

        r = client.delete(f"/api/model-library/{model_id}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["code"], "MODEL_DEPLOYMENT_EXISTS")

        db = SessionLocal()
        try:
            self.assertIsNotNone(db.query(ModelLibrary).filter(ModelLibrary.id == model_id).first())
            self.assertIsNotNone(db.query(ModelVersion).filter(ModelVersion.id == version_id).first())
        finally:
            db.close()
        self._cleanup(project_id)

    def test_03_batch_delete_skips_deployed(self):
        import uuid as _uuid

        from app.database import SessionLocal
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import InferenceDeployment

        db = SessionLocal()
        try:
            suffix = _uuid.uuid4().hex[:8]
            project, model, registered, version = self._seed(db, suffix)
            plain = ModelLibrary(
                id=_uuid.uuid4(), name=f"casc-plain-{suffix}", owner_id=model.owner_id,
                project_id=project.id, version="v1", framework="sklearn", status="completed",
            )
            db.add(plain)
            db.commit()
            db.add(InferenceDeployment(
                project_id=project.id, name=f"casc-dep-{suffix}",
                model_version_id=version.id,
            ))
            db.commit()
            project_id = project.id
            model_id, plain_id = model.id, plain.id
        finally:
            db.close()

        r = client.post(
            "/api/model-library/batch-delete",
            json={"ids": [str(model_id), str(plain_id)]},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["deleted"], 1)
        self.assertEqual(r.json()["skipped"], [str(model_id)])

        db = SessionLocal()
        try:
            self.assertIsNotNone(db.query(ModelLibrary).filter(ModelLibrary.id == model_id).first())
            self.assertIsNone(db.query(ModelLibrary).filter(ModelLibrary.id == plain_id).first())
        finally:
            db.close()
        self._cleanup(project_id)

    def _seed_rollout_target(self, db, suffix, model, version, owner_id, revision_status="stable"):
        """部署主版本属于另一模型，但其修订 target 引用 model 的版本。

        复现现场 500：旧护栏只查部署主版本，删除被 target 引用的模型时
        撞 deployment_targets 外键报 IntegrityError。revision_status 决定
        目标挂在 stable（在役）还是 superseded（自动换模残留）修订上。
        """
        from app.models.artifact import Artifact
        from app.models.model_registry import (
            DeploymentRevision,
            DeploymentTarget,
            InferenceDeployment,
            ModelVersion,
            RegisteredModel,
        )

        source_artifact = Artifact(
            project_id=model.project_id, name=f"casc-{suffix}-o-src",
            type="model", storage_path=f"casc/{suffix}/o-src",
        )
        onnx_artifact = Artifact(
            project_id=model.project_id, name=f"casc-{suffix}-o-onnx",
            type="model", storage_path=f"casc/{suffix}/o-onnx",
        )
        db.add_all([source_artifact, onnx_artifact])
        db.flush()
        other_registered = RegisteredModel(
            project_id=model.project_id, name=f"casc-rm-other-{suffix}",
            created_by_id=owner_id,
        )
        db.add(other_registered)
        db.flush()
        # onnx_artifact 来源版本不要求 source_model_library_id（合同约束）
        other_version = ModelVersion(
            registered_model_id=other_registered.id, version_number=1,
            source_kind="onnx_artifact", source_model_library_id=None,
            source_artifact_id=source_artifact.id, onnx_artifact_id=onnx_artifact.id,
            created_by_id=owner_id,
        )
        db.add(other_version)
        db.flush()
        deployment = InferenceDeployment(
            project_id=model.project_id, name=f"casc-dep-{suffix}",
            model_version_id=other_version.id,
            desired_state="running", observed_state="running",
        )
        db.add(deployment)
        db.flush()
        revision = DeploymentRevision(
            deployment_id=deployment.id, revision_number=1,
            strategy="immediate", status=revision_status, created_by_id=owner_id,
        )
        db.add(revision)
        db.flush()
        db.add(DeploymentTarget(
            revision_id=revision.id, model_version_id=version.id,
            weight_bps=10000, role="stable",
        ))
        db.commit()
        return deployment

    def test_04_library_delete_with_rollout_target_rejected(self):
        import uuid as _uuid

        from app.database import SessionLocal
        from app.models.model_library import ModelLibrary

        db = SessionLocal()
        try:
            suffix = _uuid.uuid4().hex[:8]
            project, model, registered, version = self._seed(db, suffix)
            self._seed_rollout_target(db, suffix, model, version, model.owner_id)
            project_id, model_id = project.id, model.id
        finally:
            db.close()

        r = client.delete(f"/api/model-library/{model_id}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["code"], "MODEL_DEPLOYMENT_EXISTS")

        db = SessionLocal()
        try:
            self.assertIsNotNone(db.query(ModelLibrary).filter(ModelLibrary.id == model_id).first())
        finally:
            db.close()
        self._cleanup(project_id)

    def test_05_registry_delete_with_rollout_target_rejected(self):
        """现场 500 的原始路径：模型库页删除注册模型（注册表删除端点）。"""
        import uuid as _uuid

        from app.database import SessionLocal
        from app.models.model_registry import RegisteredModel

        db = SessionLocal()
        try:
            suffix = _uuid.uuid4().hex[:8]
            project, model, registered, version = self._seed(db, suffix)
            self._seed_rollout_target(db, suffix, model, version, model.owner_id)
            project_id, registered_id = project.id, registered.id
        finally:
            db.close()

        r = client.delete(f"/api/registered-models/{registered_id}", headers=self.h)
        self.assertEqual(r.status_code, 409, r.text)
        detail = r.json()["detail"]
        self.assertEqual(detail["code"], "MODEL_DEPLOYMENT_EXISTS")
        self.assertIn("casc-dep-", detail["message"])

        db = SessionLocal()
        try:
            self.assertIsNotNone(db.query(RegisteredModel).filter(RegisteredModel.id == registered_id).first())
        finally:
            db.close()
        self._cleanup(project_id)

    def test_06_metrics_query_with_string_pagination(self):
        """回归：发布运维抽屉带 page/page_size 查询参数报 INFERENCE_QUERY_INVALID。

        查询参数恒为字符串，MetricQuery 原用 StrictInt 拒收 "1"；改普通 int
        后同一请求应 200。
        """
        import uuid as _uuid
        from datetime import datetime, timedelta, timezone

        from app.database import SessionLocal
        from app.models.model_registry import InferenceDeployment

        db = SessionLocal()
        try:
            suffix = _uuid.uuid4().hex[:8]
            project, model, registered, version = self._seed(db, suffix)
            db.add(InferenceDeployment(
                project_id=project.id, name=f"casc-dep-{suffix}",
                model_version_id=version.id,
            ))
            db.commit()
            deployment_id = None
            row = db.query(InferenceDeployment).filter(
                InferenceDeployment.name == f"casc-dep-{suffix}"
            ).first()
            deployment_id = str(row.id)
            project_id = project.id
        finally:
            db.close()

        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        until = datetime.now(timezone.utc).isoformat()
        r = client.get(
            f"/api/inference-deployments/{deployment_id}/metrics",
            params={"since": since, "until": until, "page": 1, "page_size": 100},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        r = client.get(
            f"/api/inference-deployments/{deployment_id}/request-logs",
            params={"since": since, "until": until, "page": 1, "page_size": 100},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200, r.text)
        self._cleanup(project_id)

    def test_07_delete_model_with_superseded_rollout_target_succeeds(self):
        """回归：自动换模残留的 superseded 修订目标不阻塞删除，随删除清理。

        闭环自动重训在被复用的部署上留下大量 superseded 修订目标，旧护栏
        把它们当占用导致每个换模过的模型都删不掉。
        """
        import uuid as _uuid

        from app.database import SessionLocal
        from app.models.model_library import ModelLibrary
        from app.models.model_registry import DeploymentTarget, ModelVersion

        db = SessionLocal()
        try:
            suffix = _uuid.uuid4().hex[:8]
            project, model, registered, version = self._seed(db, suffix)
            self._seed_rollout_target(
                db, suffix, model, version, model.owner_id, revision_status="superseded",
            )
            project_id, model_id, version_id = project.id, model.id, version.id
        finally:
            db.close()

        r = client.delete(f"/api/model-library/{model_id}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

        db = SessionLocal()
        try:
            self.assertIsNone(db.query(ModelLibrary).filter(ModelLibrary.id == model_id).first())
            self.assertIsNone(db.query(ModelVersion).filter(ModelVersion.id == version_id).first())
            # 历史目标行随删除清理，不再残留
            self.assertEqual(
                db.query(DeploymentTarget).filter(DeploymentTarget.model_version_id == version_id).count(),
                0,
            )
        finally:
            db.close()
        self._cleanup(project_id)


if __name__ == "__main__":
    unittest.main()
