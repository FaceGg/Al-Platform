import io
import time
import unittest
import uuid
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.run import NodeRun, WorkflowRun
from app.models.workflow import WorkflowNode
from app.templates.industrial import INDUSTRIAL_TEMPLATES


class TestIndustrialTemplateE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        username = f"industrial_e2e_{uuid.uuid4().hex[:8]}"
        cls.client.post("/api/auth/register", json={
            "username": username, "password": "admin123", "role": "admin",
        })
        login = cls.client.post("/api/auth/login", data={
            "username": username, "password": "admin123",
        })
        cls.headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        project = cls.client.post(
            "/api/projects", json={"name": "Industrial E2E"}, headers=cls.headers,
        )
        cls.project_id = project.json()["id"]

        source = Path(__file__).resolve().parents[2] / "data" / "demo" / "weld_fault_features.csv"
        frame = pd.read_csv(source)
        faults = frame[frame["Fault"] == 1]
        normal = frame[frame["Fault"] == 0].sample(n=237, random_state=42)
        bounded = pd.concat([faults, normal], ignore_index=True).sample(frac=1, random_state=42)
        payload = io.BytesIO(bounded.to_csv(index=False).encode("utf-8"))
        upload = cls.client.post(
            f"/api/projects/{cls.project_id}/datasets/upload",
            files={"file": ("weld_fault_features.csv", payload, "text/csv")},
            headers=cls.headers,
        )
        cls.artifact_id = upload.json()["artifact_id"]

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def _run_template(self, template_id):
        instantiated = self.client.post(
            f"/api/templates/{template_id}/instantiate",
            json={
                "project_id": self.project_id,
                "dataset_artifact_id": self.artifact_id,
                "parameters": {},
            },
            headers=self.headers,
        )
        self.assertEqual(instantiated.status_code, 200, instantiated.text)
        workflow_id = instantiated.json()["workflow_id"]
        started = self.client.post(f"/api/workflows/{workflow_id}/run", headers=self.headers)
        self.assertEqual(started.status_code, 201, started.text)
        run_id = started.json()["run_id"]
        deadline = time.time() + 90
        status = "pending"
        while time.time() < deadline:
            detail = self.client.get(f"/api/runs/{run_id}", headers=self.headers).json()
            status = detail["status"]
            if status in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.2)
        self.assertEqual(status, "completed", detail)
        return uuid.UUID(run_id), uuid.UUID(workflow_id)

    def test_all_four_templates_execute_required_outputs(self):
        for template_id, template in INDUSTRIAL_TEMPLATES.items():
            with self.subTest(template_id=template_id):
                run_id, workflow_id = self._run_template(template_id)
                with SessionLocal() as db:
                    nodes = {
                        node.label: node for node in db.query(WorkflowNode).filter(
                            WorkflowNode.workflow_id == workflow_id,
                        ).all()
                    }
                    for expected in template.expected_outputs:
                        node_spec = next(node for node in template.nodes if node.key == expected.node_key)
                        node = nodes[node_spec.label]
                        node_run = db.query(NodeRun).filter(
                            NodeRun.run_id == run_id,
                            NodeRun.node_id == node.id,
                            NodeRun.status == "completed",
                        ).order_by(NodeRun.attempt.desc()).first()
                        self.assertIsNotNone(node_run, f"Missing completed node {expected.node_key}")
                        self.assertIn(expected.port, node_run.result or {})


if __name__ == "__main__":
    unittest.main()
