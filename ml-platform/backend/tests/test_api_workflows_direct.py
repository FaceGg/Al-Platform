"""Tests for app.api.workflows_direct endpoints.

The direct workflow GET/PUT/DELETE routes (with audit + project access)
had only indirect coverage. We verify retrieval, save (node/edge
replacement), delete, and 404/403 behaviors.
"""
import sys
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, ".")

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.access import ProjectMember
from app.models.project import Project
from app.models.user import User
from app.models.workflow import Workflow, WorkflowEdge, WorkflowNode


class TestWorkflowsDirectAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)

        with cls.Session() as db:
            cls.owner = User(username="wfd-owner", password_hash="hash")
            cls.viewer = User(username="wfd-viewer", password_hash="hash")
            db.add_all([cls.owner, cls.viewer])
            db.flush()
            cls.project = Project(name="WFD project", owner_id=cls.owner.id)
            db.add(cls.project)
            db.flush()
            # Add viewer as a project member with "viewer" role so the access
            # check resolves (non-members get 404 "hidden", not 403 "denied").
            cls.membership = ProjectMember(
                project_id=cls.project.id,
                user_id=cls.viewer.id,
                role="viewer",
                created_by=cls.owner.id,
            )
            db.add(cls.membership)
            db.flush()
            cls.workflow = Workflow(
                project_id=cls.project.id,
                name="WFD workflow",
                created_by=cls.owner.id,
            )
            db.add(cls.workflow)
            db.flush()
            cls.workflow_id = str(cls.workflow.id)
            cls.project_id = str(cls.project.id)
            # Seed an initial node so GET returns something.
            cls.node = WorkflowNode(
                workflow_id=cls.workflow.id,
                operator_id="csv_import",
                label="Read",
                position_x=0.0,
                position_y=0.0,
                params={},
            )
            db.add(cls.node)
            db.commit()

        cls.db = cls.Session()
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.owner
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def test_get_workflow_returns_nodes_and_edges(self):
        response = self.client.get(f"/api/workflows/{self.workflow_id}")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["id"], self.workflow_id)
        self.assertEqual(data["project_id"], self.project_id)
        self.assertEqual(data["name"], "WFD workflow")
        self.assertEqual(len(data["nodes"]), 1)
        self.assertEqual(data["nodes"][0]["operator_id"], "csv_import")
        self.assertEqual(data["edges"], [])

    def test_get_missing_workflow_returns_404(self):
        response = self.client.get(f"/api/workflows/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)

    def test_save_workflow_replaces_nodes_and_edges(self):
        save_payload = {
            "name": "Saved Workflow",
            "description": "updated desc",
            "nodes": [
                {
                    "id": "n1",
                    "operator_id": "csv_import",
                    "label": "Source",
                    "position": {"x": 10.0, "y": 20.0},
                    "params": {"file": "a.csv"},
                },
                {
                    "id": "n2",
                    "operator_id": "row_filter",
                    "label": "Filter",
                    "position": {"x": 100.0, "y": 20.0},
                    "params": {},
                },
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "n1",
                    "source_port": "default",
                    "target": "n2",
                    "target_port": "input",
                },
            ],
        }
        response = self.client.put(f"/api/workflows/{self.workflow_id}", json=save_payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"message": "Workflow saved"})

        # Verify persisted state via GET.
        fetched = self.client.get(f"/api/workflows/{self.workflow_id}").json()
        self.assertEqual(fetched["name"], "Saved Workflow")
        self.assertEqual(fetched["description"], "updated desc")
        self.assertEqual(len(fetched["nodes"]), 2)
        self.assertEqual(len(fetched["edges"]), 1)
        self.assertEqual(fetched["edges"][0]["source_port"], "default")

    def test_save_workflow_with_invalid_node_reference_returns_400(self):
        save_payload = {
            "name": "Bad",
            "nodes": [],
            "edges": [
                {
                    "id": "e1",
                    "source": "not-a-uuid-or-known-id",
                    "source_port": "default",
                    "target": "also-bad",
                    "target_port": "input",
                },
            ],
        }
        response = self.client.put(f"/api/workflows/{self.workflow_id}", json=save_payload)
        self.assertEqual(response.status_code, 400)

    def test_save_missing_workflow_returns_404(self):
        response = self.client.put(
            f"/api/workflows/{uuid.uuid4()}",
            json={"name": "x", "nodes": [], "edges": []},
        )
        self.assertEqual(response.status_code, 404)

    def test_viewer_cannot_save_workflow(self):
        # Viewer lacks resource.update permission.
        app.dependency_overrides[get_current_user] = lambda: self.viewer
        try:
            response = self.client.put(
                f"/api/workflows/{self.workflow_id}",
                json={"name": "Viewer Edit", "nodes": [], "edges": []},
            )
            self.assertEqual(response.status_code, 403)
        finally:
            app.dependency_overrides[get_current_user] = lambda: self.owner

    def test_delete_workflow_returns_204(self):
        # Create a throwaway workflow to delete via the shared session.
        wf = Workflow(
            project_id=self.project.id,
            name="To Delete",
            created_by=self.owner.id,
        )
        self.db.add(wf)
        self.db.commit()
        wf_id = str(wf.id)

        response = self.client.delete(f"/api/workflows/{wf_id}")
        self.assertEqual(response.status_code, 204, response.text)
        # Subsequent GET returns 404.
        self.assertEqual(self.client.get(f"/api/workflows/{wf_id}").status_code, 404)

    def test_delete_missing_workflow_returns_404(self):
        response = self.client.delete(f"/api/workflows/{uuid.uuid4()}")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
