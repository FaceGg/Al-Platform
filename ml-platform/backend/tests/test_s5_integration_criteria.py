"""S5 集成判据①②（spec v0.9 §12.2/§12.3，2026-11-04）。

①换模跟随 e2e：真实 AutoML 搜索引擎（run_automl_search）训练 + 真实编排
发布/invoke 全链——serving 图绑定 load_deployment_model 后，轮换
``deployments.model_version_id``（闭环重训换模的生产字段）无需重新发布，
图调用输出跟随新模型。

②双域服务化对照：拧紧形（f1/f2）与点焊形（x1/x2/x3）两个域各自独立
部署/发布/调用，互不串扰。

训练引擎口径：run_automl_search 为平台真实搜索引擎（族评分/CV/指标）；
拟合采用搜索同族估计器 RandomForestClassifier(n_estimators=40)（引擎内
同参）在全量数据上拟合——非注入 trainer。
"""
import io
import tempfile
import unittest
import uuid
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sklearn.ensemble import RandomForestClassifier

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.artifact import Artifact  # noqa: F401
from app.models.model_registry import InferenceDeployment
from app.models.model_library import ModelLibrary
from app.models.model_registry import ModelVersion, RegisteredModel
from app.models.user import User
from app.services.automl_search import AutoMLContract, run_automl_search
from app.services.artifact_service import build_artifact_service
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login(username="admin", password="admin123"):
    r = client.post("/api/auth/login", data={"username": username, "password": password})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _domain_frame(kind: str) -> pd.DataFrame:
    if kind == "tightening":
        # 拧紧形：f1 高段=异常类。A 边界 f1>2.5，B 边界 f1>7（同一记录
        # f1=5.1 在 A 下预测 1、在 B 下预测 0——换模翻转的判别点）。
        return pd.DataFrame({
            "f1": [0.1, 0.4, 1.2, 2.0, 2.4, 2.8, 3.5, 4.2, 5.1, 6.0],
            "f2": [1.0, 0.8, 1.1, 0.9, 1.0, -1.0, -1.2, -0.9, -1.1, -1.0],
            "label": [0, 0, 0, 0, 0, 1, 1, 1, 1, 1],
        })
    # 点焊形：x2 高段=异常类，三特征。
    rng = np.random.default_rng(7)
    x1 = rng.normal(size=30)
    x2 = np.concatenate([rng.normal(-1.0, 0.2, size=15), rng.normal(1.0, 0.2, size=15)])
    x3 = rng.normal(size=30)
    return pd.DataFrame({"x1": x1, "x2": x2, "x3": x3,
                         "label": (x2 > 0).astype(int)})


class S5IntegrationCriteria(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = login()
        db = SessionLocal()
        try:
            cls.admin_id = db.query(User).filter(User.username == "admin").one().id
            cls.project = Project_ = None
            from app.models.project import Project

            cls.project = Project(name=f"s5-{uuid.uuid4().hex[:8]}", owner_id=cls.admin_id)
            db.add(cls.project)
            db.flush()
            service = build_artifact_service(db)
            cls.domain = {}
            for kind, feature_cols, boundary in (
                ("tightening", ["f1", "f2"], 2.5),
                ("spotweld", ["x1", "x2", "x3"], None),
            ):
                frame = _domain_frame(kind)
                contract = AutoMLContract(
                    task_type="classification",
                    target_columns=["label"],
                    input_columns=feature_cols,
                    cross_validation_folds=2,
                )
                # ① 真实搜索引擎：族评分/CV/指标（引擎内同参估计器族）
                result = run_automl_search(frame, contract)
                metrics = result.per_target["label"]
                accuracy = float(getattr(metrics, "accuracy", 0.0) or 0.0)
                assert accuracy >= 0.85, (kind, accuracy)

                # ② 搜索同族估计器全量拟合（非注入 trainer）
                features = frame[feature_cols]
                model = RandomForestClassifier(
                    n_estimators=40, random_state=42, n_jobs=1,
                ).fit(features, frame["label"])
                buffer = io.BytesIO()
                joblib.dump(model, buffer)

                with tempfile.TemporaryDirectory() as tmp:
                    model_path = Path(tmp) / f"{kind}-model.joblib"
                    model_path.write_bytes(buffer.getvalue())
                    artifact = service.create_from_file(
                        cls.project.id, model_path,
                        f"s5-{kind}-{uuid.uuid4().hex[:6]}", "model",
                    )
                db.flush()
                library = ModelLibrary(
                    name=f"s5-{kind}-lib-{uuid.uuid4().hex[:6]}",
                    project_id=cls.project.id, owner_id=cls.admin_id,
                    status="completed", framework="sklearn",
                    backbone="random_forest", format="joblib",
                    metrics={"accuracy": accuracy},
                    model_artifact_id=artifact.id,
                )
                db.add(library)
                db.flush()
                registered = RegisteredModel(
                    project_id=cls.project.id,
                    name=f"s5-{kind}-model-{uuid.uuid4().hex[:6]}",
                    created_by_id=cls.admin_id,
                )
                db.add(registered)
                db.flush()
                version = ModelVersion(
                    registered_model_id=registered.id,
                    version_number=1,
                    source_kind="platform_joblib",
                    source_model_library_id=library.id,
                    source_artifact_id=artifact.id,
                    onnx_artifact_id=artifact.id,
                    framework="sklearn", algorithm="random_forest",
                    feature_schema=[{"name": c, "type": "number"} for c in feature_cols],
                    output_schema={"type": "number"},
                    metrics={"accuracy": accuracy},
                    conversion_metadata={},
                    approval_status="approved",
                    created_by_id=cls.admin_id,
                )
                db.add(version)
                db.flush()
                cls.domain[kind] = {
                    "artifact_id": str(artifact.id),
                    "version_id": version.id,
                    "boundary": boundary,
                    "features": feature_cols,
                    "accuracy": accuracy,
                }
            db.commit()
            cls.project_id = str(cls.project.id)
        finally:
            db.close()

    @staticmethod
    def _swap_boundary_frame() -> pd.DataFrame:
        # 换模后的 B 模型：边界右移（f1>7 才为 1），同记录 f1=5.1 → 0
        return pd.DataFrame({
            "f1": [0.1, 0.4, 1.2, 2.0, 2.4, 2.8, 3.5, 4.2, 5.1, 6.0,
                   7.5, 8.2, 9.0, 9.5],
            "f2": [1.0, 0.8, 1.1, 0.9, 1.0, -1.0, -1.2, -0.9, -1.1, -1.0,
                   -1.0, -1.1, -0.9, -1.2],
            "label": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
        })

    def _deploy_and_publish(self, kind: str, version_id) -> tuple[str, str]:
        db = SessionLocal()
        try:
            deployment = InferenceDeployment(
                project_id=self.project.id,
                name=f"s5-deploy-{kind}-{uuid.uuid4().hex[:6]}",
                model_version_id=version_id,
                desired_state="running", observed_state="running",
                created_by_id=self.admin_id,
            )
            db.add(deployment)
            db.flush()
            from app.models.workflow import Workflow
            from app.models.workflow_version import WorkflowVersion

            workflow = Workflow(
                project_id=self.project.id,
                name=f"s5-wf-{kind}-{uuid.uuid4().hex[:6]}",
                created_by=self.admin_id,
            )
            db.add(workflow)
            db.flush()
            nodes = [
                {"id": "n-input", "operator_id": "api_input", "label": "输入", "params": {}},
                {"id": "n-model", "operator_id": "load_deployment_model", "label": "部署模型",
                 "params": {"deployment_id": str(deployment.id)}},
                {"id": "n-apply", "operator_id": "apply_model", "label": "推理", "params": {}},
                {"id": "n-cond", "operator_id": "condition", "label": "判断",
                 "params": {"column": "prediction", "operator": "==", "value": "1"}},
            ]
            edges = [
                {"source": "n-input", "target": "n-apply", "source_port": "data", "target_port": "data"},
                {"source": "n-model", "target": "n-apply", "source_port": "model", "target_port": "model"},
                {"source": "n-apply", "target": "n-cond", "source_port": "data", "target_port": "data"},
            ]
            workflow_version = WorkflowVersion(
                workflow_id=workflow.id, version=1, name="v1",
                nodes_snapshot=nodes, edges_snapshot=edges,
                published_by=self.admin_id,
            )
            db.add(workflow_version)
            db.commit()
            return str(deployment.id), f"{workflow.id}/{workflow_version.version}"
        finally:
            db.close()

    def _publish(self, workflow_ref: str) -> str:
        r = client.post(
            f"/api/platform/apis/publish/workflow/{workflow_ref}", headers=self.h,
        )
        self.assertEqual(r.status_code, 201, r.text)
        return f"/api/platform/apis/orchestration/{r.json()['source_id']}/invoke"

    def _invoke(self, invoke_url: str, record: dict) -> dict:
        r = client.post(invoke_url, json={"record": record}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_1_swap_follow_e2e_without_republish(self):
        from app.models.model_registry import InferenceDeployment as Deploy

        main_version_id = self.domain["tightening"]["version_id"]
        deployment_id, workflow_ref = self._deploy_and_publish(
            "tightening", main_version_id,
        )
        invoke_url = self._publish(workflow_ref)
        boundary_record = {"f1": 5.1, "f2": -1.0}

        # A 模型（边界 f1>2.5）：记录预测 1 → true 分支
        body = self._invoke(invoke_url, boundary_record)
        self.assertEqual(body["branch"], "true", body)
        self.assertEqual(float(body["records"][0]["prediction"]), 1.0)

        # 换模：轮换 deployment.model_version_id → B 模型（边界 f1>7），
        # 不重新发布工作流
        db = SessionLocal()
        try:
            swap_frame = self._swap_boundary_frame()
            swap_model = RandomForestClassifier(
                n_estimators=40, random_state=42, n_jobs=1,
            ).fit(swap_frame[["f1", "f2"]], swap_frame["label"])
            buffer = io.BytesIO()
            joblib.dump(swap_model, buffer)
            db2 = SessionLocal()
            try:
                service = build_artifact_service(db2)
                with tempfile.TemporaryDirectory() as tmp:
                    model_path = Path(tmp) / "swap-model.joblib"
                    model_path.write_bytes(buffer.getvalue())
                    artifact_b = service.create_from_file(
                        self.project.id, model_path,
                        f"s5-swap-{uuid.uuid4().hex[:6]}", "model",
                    )
                db2.commit()
                artifact_b_id = artifact_b.id
            finally:
                db2.close()
            library_b = ModelLibrary(
                name=f"s5-swap-lib-{uuid.uuid4().hex[:6]}",
                project_id=self.project.id, owner_id=self.admin_id,
                status="completed", framework="sklearn",
                backbone="random_forest", format="joblib",
                model_artifact_id=artifact_b_id,
            )
            db.add(library_b)
            db.flush()
            registered_b = RegisteredModel(
                project_id=self.project.id,
                name=f"s5-swap-model-{uuid.uuid4().hex[:6]}",
                created_by_id=self.admin_id,
            )
            db.add(registered_b)
            db.flush()
            version_b = ModelVersion(
                registered_model_id=registered_b.id,
                version_number=1,
                source_kind="platform_joblib",
                source_model_library_id=library_b.id,
                source_artifact_id=artifact_b_id,
                onnx_artifact_id=artifact_b_id,
                framework="sklearn", algorithm="random_forest",
                feature_schema=[{"name": "f1", "type": "number"},
                                {"name": "f2", "type": "number"}],
                output_schema={"type": "number"},
                metrics={}, conversion_metadata={},
                approval_status="approved",
                created_by_id=self.admin_id,
            )
            db.add(version_b)
            db.flush()
            deployment = db.query(Deploy).filter(
                Deploy.id == uuid.UUID(deployment_id),
            ).first()
            deployment.model_version_id = version_b.id
            db.commit()
            version_b_id = version_b.id
        finally:
            db.close()

        # 同一记录、同一发布 API：输出跟随新模型（1 → 0，false 分支）
        body = self._invoke(invoke_url, boundary_record)
        self.assertEqual(body["branch"], "false", body)
        self.assertEqual(float(body["records"][0]["prediction"]), 0.0)

        # 可逆性：轮换回 A 模型 → 恢复 1
        db = SessionLocal()
        try:
            deployment = db.query(Deploy).filter(Deploy.id == uuid.UUID(deployment_id)).first()
            deployment.model_version_id = main_version_id
            db.commit()
        finally:
            db.close()
        body = self._invoke(invoke_url, boundary_record)
        self.assertEqual(float(body["records"][0]["prediction"]), 1.0, body)

    def test_2_dual_domain_serving_isolation(self):
        # 点焊域独立部署/发布/调用（与拧紧域互不串扰的对照）
        version_id = self.domain["spotweld"]["version_id"]
        _deployment_id, workflow_ref = self._deploy_and_publish(
            "spotweld", version_id,
        )
        invoke_url = self._publish(workflow_ref)
        rng = np.random.default_rng(11)
        ok_record = {"x1": float(rng.normal()), "x2": -1.2, "x3": 0.3}
        bad_record = {"x1": float(rng.normal()), "x2": 1.3, "x3": -0.2}
        body = self._invoke(invoke_url, ok_record)
        self.assertEqual(float(body["records"][0]["prediction"]), 0.0, body)
        body = self._invoke(invoke_url, bad_record)
        self.assertEqual(float(body["records"][0]["prediction"]), 1.0, body)
        self.assertEqual(body["branch"], "true", body)


if __name__ == "__main__":
    unittest.main()
