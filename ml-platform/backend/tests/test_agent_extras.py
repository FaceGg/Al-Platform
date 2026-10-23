"""agent_extras API tests (P1: profile endpoint + fixation + versions/rollback)."""

import io
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.services.artifact_service import build_artifact_service  # noqa: E402
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(__import__("app.main", fromlist=["app"]).app)


def _csv() -> bytes:
    frame = pd.DataFrame(
        {
            "F1": [5.0 + i * 0.01 for i in range(40)] + [0.2 + i * 0.01 for i in range(40)],
            "F2": [1.0] * 40 + [-1.0] * 40,
            "target": [1] * 40 + [0] * 40,
        }
    )
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue()


class TestAgentExtras(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        cls.h = {"Authorization": "Bearer " + client.post(
            "/api/auth/login", data={"username": "admin", "password": "admin123"}
        ).json()["access_token"]}
        with SessionLocal() as db:
            from app.models.project import Project
            from app.models.user import User

            admin = db.query(User).filter(User.username == "admin").one()
            project = Project(name="extras-%s" % uuid4().hex[:8], owner_id=admin.id)
            db.add(project)
            db.flush()
            cls.project_id = project.id
            service = build_artifact_service(db)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "extras.csv"
                path.write_bytes(_csv())
                artifact = service.create_from_file(
                    project.id, path, "extras-%s" % uuid4().hex[:6], "dataset"
                )
                db.commit()
                cls.artifact_id = artifact.id
            cls.admin_id = admin.id

    def test_profile_endpoint_returns_column_stats(self):
        response = client.get(
            "/api/agent/datasets/%s/profile" % self.artifact_id,
            params={"target": "target", "project_id": str(self.project_id)},
            headers=self.h,
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        names = {column["name"] for column in body["columns"]}
        self.assertIn("F1", names)
        self.assertNotIn("row_samples", body)
        top = [item["column"] for item in body["mutual_info_top"][:2]]
        self.assertIn("F1", top)

    def test_fixate_versions_and_rollback(self):
        with SessionLocal() as db:
            run = AgentRun(
                project_id=self.project_id,
                dataset_artifact_id=self.artifact_id,
                target_column="target",
                status="accepted",
                current_stage="done",
                memory_json={
                    "last_domain": "extras",
                    "rounds": [
                        {
                            "round": 1,
                            "verdict": "pass",
                            "s2_attempts": [
                                {"attempt": 1, "ok": True,
                                 "script": "def transform(df):\n    return df"}
                            ],
                        }
                    ],
                },
                result_json={"metrics": {"recall_minority": 0.95}},
                created_by=self.admin_id,
            )
            db.add(run)
            db.commit()
            run_id = str(run.id)
        fixed = client.post(
            "/api/agent/recipes/fixate",
            json={"run_id": run_id, "name": "extras-recipe-%s" % uuid4().hex[:5]},
            headers=self.h,
        )
        self.assertEqual(fixed.status_code, 201, fixed.text)
        recipe_id = fixed.json()["recipe_id"]
        self.assertTrue(fixed.json()["created"])

        # 幂等：重复固化返回既有配方。
        again = client.post("/api/agent/recipes/fixate", json={"run_id": run_id},
                            headers=self.h)
        self.assertFalse(again.json()["created"])
        self.assertEqual(again.json()["recipe_id"], recipe_id)

        # 发 v2 再回滚到 v1（回滚=新版本 v3 携带旧内容）。
        with SessionLocal() as db:
            from app.services.agent.recipe import update_recipe

            update_recipe(
                db, uuid.UUID(recipe_id),
                content={"domain": "extras", "acceptance_gates": {"recall_minority": 0.5}},
                change_note="v2 放宽",
            )
        versions = client.get("/api/agent/recipes/%s/versions" % recipe_id, headers=self.h)
        self.assertEqual(len(versions.json()), 2)
        rolled = client.post(
            "/api/agent/recipes/%s/rollback" % recipe_id,
            json={"to_version": 1},
            headers=self.h,
        )
        self.assertEqual(rolled.json()["new_version"], 3)

    def test_fixate_rejects_unaccepted_run(self):
        with SessionLocal() as db:
            run = AgentRun(
                project_id=self.project_id,
                dataset_artifact_id=self.artifact_id,
                target_column="target",
                status="waiting_escalate",
                created_by=self.admin_id,
            )
            db.add(run)
            db.commit()
            run_id = str(run.id)
        response = client.post(
            "/api/agent/recipes/fixate", json={"run_id": run_id}, headers=self.h
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "AGENT_RUN_NOT_ACCEPTED")

    def _servitize_stack(self):
        """搭建 servitize API 测试栈：模型工件→库→版本→注册模型→部署。"""
        import joblib
        from sklearn.linear_model import LogisticRegression

        from app.models.model_library import ModelLibrary
        from app.models.model_registry import (
            InferenceDeployment,
            ModelVersion,
            RegisteredModel,
        )
        with SessionLocal() as db:
            from app.models.user import User

            admin = db.query(User).filter(User.username == "admin").one()
            service = build_artifact_service(db)
            import tempfile as tempfile_module

            with tempfile_module.TemporaryDirectory() as tmp:
                model = LogisticRegression().fit([[0.0], [0.1], [5.0], [5.1]], [0, 0, 1, 1])
                path = Path(tmp) / "s5-api-model.joblib"
                joblib.dump(model, path)
                artifact = service.create_from_file(
                    self.project_id, path, "s5-api-%s" % uuid4().hex[:6], "model"
                )
            artifact_id = uuid.UUID(str(artifact.id))
            registered = RegisteredModel(
                project_id=self.project_id,
                name="s5-api-%s" % uuid4().hex[:6],
                created_by_id=admin.id,
            )
            db.add(registered)
            db.flush()
            library = ModelLibrary(
                name="s5-api-lib-%s" % uuid4().hex[:6],
                project_id=self.project_id,
                owner_id=admin.id,
                status="completed",
                framework="sklearn",
                model_artifact_id=artifact_id,
                file_size=1,
                format="joblib",
            )
            db.add(library)
            db.flush()
            version = ModelVersion(
                registered_model_id=registered.id,
                version_number=1,
                source_kind="platform_joblib",
                source_artifact_id=artifact_id,
                onnx_artifact_id=artifact_id,
                approval_status="approved",
                source_model_library_id=library.id,
                created_by_id=admin.id,
            )
            db.add(version)
            db.flush()
            deployment = InferenceDeployment(
                project_id=self.project_id,
                name="s5-api-deploy-%s" % uuid4().hex[:6],
                model_version_id=version.id,
                created_by_id=admin.id,
            )
            db.add(deployment)
            db.commit()
            return str(deployment.id)

    def test_servitize_draft_and_activate_flow(self):
        from app.services.agent.recipe import create_recipe

        deployment_id = self._servitize_stack()
        with SessionLocal() as db:
            recipe = create_recipe(
                db,
                project_id=self.project_id,
                name="s5-flow-%s" % uuid4().hex[:6],
                content={
                    "domain": "tightening",
                    "target_semantics": {"0": "不合格", "1": "合格"},
                    "inputs": {"target_column": "target"},
                    "feature_script": "def transform(df):\n    return df",
                    "smoke_row": {"F1": 5.0},
                },
            )
            recipe_id = str(recipe.id)
        draft = client.post(
            "/api/agent/servitize",
            json={
                "recipe_id": recipe_id,
                "deployment_id": deployment_id,
                "project_id": str(self.project_id),
            },
            headers=self.h,
        )
        self.assertEqual(draft.status_code, 201, draft.text)
        body = draft.json()
        self.assertEqual(body["error_classes"], ["0"])
        self.assertFalse(body["activated"])
        self.assertTrue(body["smoke"].get("dry_run"))
        self.assertEqual(body["smoke"].get("appended"), False)
        api_id = body["model_api_id"]

        activated = client.post(
            "/api/agent/servitize/activate",
            json={"model_api_id": api_id},
            headers=self.h,
        )
        self.assertEqual(activated.status_code, 200)
        self.assertEqual(activated.json()["status"], "published")

        duplicate_activation = client.post(
            "/api/agent/servitize/activate",
            json={"model_api_id": api_id},
            headers=self.h,
        )
        self.assertEqual(duplicate_activation.status_code, 409)

    def test_servitize_unknown_recipe_404(self):
        deployment_id = self._servitize_stack()
        response = client.post(
            "/api/agent/servitize",
            json={
                "recipe_id": str(uuid4()),
                "deployment_id": deployment_id,
                "project_id": str(self.project_id),
            },
            headers=self.h,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "RECIPE_NOT_FOUND")
