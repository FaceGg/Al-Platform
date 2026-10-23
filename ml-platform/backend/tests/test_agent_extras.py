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
