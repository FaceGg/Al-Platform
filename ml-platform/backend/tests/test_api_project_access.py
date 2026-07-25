import unittest
import uuid
import io
import importlib

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.api.runs import get_task_dispatcher
from app.database import Base, get_db
from app.main import app
from app.models.access import AuditEvent, ProjectMember
from app.models.project import Project
from app.models.run import WorkflowRun
from app.models.user import User
from app.models.workflow import Workflow, WorkflowNode
from app.models.artifact import Artifact
from app.models.model_library import ModelLibrary


class TestProjectAccessAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)
        cls.db = cls.Session()
        cls.users = {
            role: User(username=f"api-access-{role}", password_hash="hash")
            for role in ("owner", "editor", "viewer", "outsider")
        }
        cls.db.add_all(cls.users.values())
        cls.db.flush()
        cls.project = Project(name="Access API project", owner_id=cls.users["owner"].id)
        cls.db.add(cls.project)
        cls.db.commit()
        cls.current_user = cls.users["owner"]
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.current_user
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def setUp(self):
        self.__class__.current_user = self.users["owner"]

    def test_member_add_list_change_and_remove(self):
        project_id = self.project.id
        added = self.client.post(
            f"/api/projects/{project_id}/members",
            json={"username": self.users["editor"].username, "role": "editor"},
        )
        self.assertEqual(added.status_code, 201, added.text)
        self.assertEqual(added.json()["role"], "editor")

        listed = self.client.get(f"/api/projects/{project_id}/members")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertTrue(
            {"owner", "editor"}.issubset(
                {item["role"] for item in listed.json()["items"]}
            )
        )

        changed = self.client.patch(
            f"/api/projects/{project_id}/members/{self.users['editor'].id}",
            json={"role": "operator"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["role"], "operator")

        removed = self.client.delete(
            f"/api/projects/{project_id}/members/{self.users['editor'].id}"
        )
        self.assertEqual(removed.status_code, 204, removed.text)

    def test_joined_project_list_contains_project_role(self):
        self.db.add(ProjectMember(
            project_id=self.project.id,
            user_id=self.users["viewer"].id,
            role="viewer",
            created_by=self.users["owner"].id,
        ))
        self.db.commit()
        self.__class__.current_user = self.users["viewer"]

        response = self.client.get("/api/projects")

        self.assertEqual(response.status_code, 200, response.text)
        item = next(item for item in response.json()["items"] if item["id"] == str(self.project.id))
        self.assertEqual(item["project_role"], "viewer")

    def test_visible_member_is_forbidden_and_outsider_is_hidden(self):
        self.__class__.current_user = self.users["viewer"]
        forbidden = self.client.get(f"/api/projects/{self.project.id}/members")
        self.assertEqual(forbidden.status_code, 403, forbidden.text)
        self.assertEqual(forbidden.json()["detail"]["code"], "PROJECT_PERMISSION_DENIED")

        self.__class__.current_user = self.users["outsider"]
        hidden = self.client.get(f"/api/projects/{self.project.id}/members")
        self.assertEqual(hidden.status_code, 404, hidden.text)

    def test_owner_can_filter_append_only_audit_events(self):
        response = self.client.get(
            f"/api/projects/{self.project.id}/audit-events",
            params={"action": "project.member.add", "result": "success", "limit": 10},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertGreaterEqual(payload["total"], 1)
        self.assertTrue(all(item["action"] == "project.member.add" for item in payload["items"]))
        self.assertTrue(all(item["result"] == "success" for item in payload["items"]))


class TestProjectRoleResourceAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)
        cls.db = cls.Session()
        cls.users = {
            role: User(username=f"api-role-{role}", password_hash="hash")
            for role in ("owner", "editor", "operator", "viewer", "outsider")
        }
        cls.db.add_all(cls.users.values())
        cls.db.flush()
        cls.project = Project(name="Role resource project", owner_id=cls.users["owner"].id)
        cls.db.add(cls.project)
        cls.db.flush()
        cls.db.add_all([
            ProjectMember(
                project_id=cls.project.id,
                user_id=cls.users[role].id,
                role=role,
                created_by=cls.users["owner"].id,
            )
            for role in ("editor", "operator", "viewer")
        ])
        cls.workflow = Workflow(
            project_id=cls.project.id,
            name="Role workflow",
            created_by=cls.users["owner"].id,
        )
        cls.db.add(cls.workflow)
        cls.db.flush()
        cls.db.add(WorkflowNode(
            workflow_id=cls.workflow.id,
            operator_id="mechanism_thermal",
            label="Thermal",
            position_x=10,
            position_y=20,
            params={},
        ))
        cls.db.commit()
        cls.current_user = cls.users["owner"]
        cls.dispatch_calls = []
        dispatcher = type("Dispatcher", (), {
            "enqueue_workflow": lambda self, run_id: cls.dispatch_calls.append(("enqueue", run_id)),
            "cancel": lambda self, task_id, terminate=False: cls.dispatch_calls.append(
                ("cancel", task_id, terminate)
            ),
        })()
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.current_user
        app.dependency_overrides[get_task_dispatcher] = lambda: dispatcher
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def _as(self, role):
        self.__class__.current_user = self.users[role]

    def test_all_members_can_read_project_and_workflow_but_outsider_is_hidden(self):
        for role in ("owner", "editor", "operator", "viewer"):
            with self.subTest(role=role):
                self._as(role)
                project = self.client.get(f"/api/projects/{self.project.id}")
                workflow = self.client.get(f"/api/workflows/{self.workflow.id}")
                self.assertEqual(project.status_code, 200, project.text)
                self.assertEqual(workflow.status_code, 200, workflow.text)

        self._as("outsider")
        self.assertEqual(self.client.get(f"/api/projects/{self.project.id}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/workflows/{self.workflow.id}").status_code, 404)

    def test_only_owner_can_update_project_metadata(self):
        self._as("editor")
        denied = self.client.put(
            f"/api/projects/{self.project.id}", json={"description": "editor denied"},
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertEqual(denied.json()["detail"]["code"], "PROJECT_PERMISSION_DENIED")

        self._as("owner")
        updated = self.client.put(
            f"/api/projects/{self.project.id}", json={"description": "owner updated"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["description"], "owner updated")

    def test_editor_can_create_save_publish_restore_and_delete_workflow(self):
        self._as("editor")
        created = self.client.post(
            f"/api/projects/{self.project.id}/workflows",
            json={"name": "Editor workflow", "nodes": [], "edges": []},
        )
        self.assertEqual(created.status_code, 201, created.text)
        workflow_id = created.json()["id"]

        saved = self.client.put(
            f"/api/workflows/{workflow_id}",
            json={
                "name": "Editor saved workflow",
                "nodes": [{
                    "id": "thermal", "operator_id": "mechanism_thermal", "label": "Thermal",
                    "position": {"x": 10, "y": 20}, "params": {},
                }],
                "edges": [],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        published = self.client.post(f"/api/workflows/{workflow_id}/publish")
        self.assertEqual(published.status_code, 201, published.text)
        restored = self.client.post(f"/api/workflows/{workflow_id}/versions/1/restore")
        self.assertEqual(restored.status_code, 200, restored.text)
        deleted = self.client.delete(f"/api/workflows/{workflow_id}")
        self.assertEqual(deleted.status_code, 204, deleted.text)

        self._as("operator")
        denied = self.client.put(
            f"/api/workflows/{self.workflow.id}",
            json={"name": "Operator denied", "nodes": [], "edges": []},
        )
        self.assertEqual(denied.status_code, 403, denied.text)

    def test_operator_can_start_cancel_and_read_run_while_viewer_cannot_execute(self):
        self._as("operator")
        started = self.client.post(f"/api/workflows/{self.workflow.id}/run")
        self.assertEqual(started.status_code, 201, started.text)
        run_id = started.json()["run_id"]
        run = self.db.query(WorkflowRun).filter(WorkflowRun.id == uuid.UUID(run_id)).one()
        run.task_id = "role-task"
        self.db.commit()
        cancelled = self.client.post(f"/api/runs/{run_id}/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "cancel_requested")
        self.assertEqual(self.client.get(f"/api/runs/{run_id}").status_code, 200)

        self._as("viewer")
        denied = self.client.post(f"/api/workflows/{self.workflow.id}/run")
        self.assertEqual(denied.status_code, 403, denied.text)

        self._as("outsider")
        self.assertEqual(self.client.get(f"/api/runs/{run_id}").status_code, 404)

    def test_template_instantiation_uses_definition_permissions(self):
        self._as("editor")
        created = self.client.post(
            "/api/templates/condition_branch/instantiate",
            params={"project_id": str(self.project.id)},
        )
        self.assertEqual(created.status_code, 200, created.text)

        self._as("operator")
        denied = self.client.post(
            "/api/templates/condition_branch/instantiate",
            params={"project_id": str(self.project.id)},
        )
        self.assertEqual(denied.status_code, 403, denied.text)

    def test_dataset_roles_cover_upload_read_and_hidden_access(self):
        self._as("editor")
        uploaded = self.client.post(
            f"/api/projects/{self.project.id}/datasets/upload",
            files={"file": ("roles.csv", io.BytesIO(b"x,y\n1,2\n"), "text/csv")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        artifact_id = uploaded.json()["artifact_id"]

        self._as("viewer")
        listed = self.client.get(f"/api/projects/{self.project.id}/datasets")
        preview = self.client.get(f"/api/datasets/{artifact_id}/preview")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(preview.status_code, 200, preview.text)

        self._as("operator")
        denied = self.client.post(
            f"/api/projects/{self.project.id}/datasets/upload",
            files={"file": ("denied.csv", io.BytesIO(b"x\n1\n"), "text/csv")},
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        self._as("outsider")
        self.assertEqual(
            self.client.get(f"/api/projects/{self.project.id}/datasets").status_code,
            404,
        )

    def test_project_model_artifacts_use_resource_permissions(self):
        artifact = Artifact(
            project_id=self.project.id,
            name="Role model",
            type="model",
            storage_path="",
            storage_uri="file:///missing/role-model.bin",
            file_size=1,
            format="bin",
        )
        self.db.add(artifact)
        self.db.commit()

        self._as("viewer")
        self.assertEqual(
            self.client.get(f"/api/projects/{self.project.id}/models").status_code,
            200,
        )
        self._as("operator")
        denied = self.client.delete(f"/api/models/{artifact.id}")
        self.assertEqual(denied.status_code, 403, denied.text)
        self._as("editor")
        deleted = self.client.delete(f"/api/models/{artifact.id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)

    def test_project_model_library_uses_member_roles(self):
        self._as("editor")
        created = self.client.post("/api/model-library", json={
            "name": "Member model", "project_id": str(self.project.id),
        })
        self.assertEqual(created.status_code, 200, created.text)
        model_id = created.json()["id"]

        self._as("viewer")
        self.assertEqual(self.client.get(f"/api/model-library/{model_id}").status_code, 200)
        self._as("operator")
        denied = self.client.put(
            f"/api/model-library/{model_id}", json={"description": "denied"},
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        self._as("editor")
        self.assertEqual(
            self.client.put(
                f"/api/model-library/{model_id}", json={"description": "updated"},
            ).status_code,
            200,
        )
        self.assertEqual(self.client.delete(f"/api/model-library/{model_id}").status_code, 200)

    def test_workflow_agent_tasks_use_execution_roles(self):
        self._as("operator")
        created = self.client.post("/api/orchestration/tasks", json={
            "name": "Role agent task", "workflow_id": str(self.workflow.id),
        })
        self.assertEqual(created.status_code, 200, created.text)
        task_id = created.json()["id"]
        sent = self.client.post(
            f"/api/orchestration/tasks/{task_id}/messages",
            json={"content": "operator message"},
        )
        self.assertEqual(sent.status_code, 200, sent.text)

        self._as("viewer")
        self.assertEqual(self.client.get(f"/api/orchestration/tasks/{task_id}").status_code, 200)
        self.assertEqual(
            self.client.get(
                "/api/orchestration/tasks", params={"workflow_id": str(self.workflow.id)},
            ).status_code,
            200,
        )
        denied = self.client.post(
            f"/api/orchestration/tasks/{task_id}/messages",
            json={"content": "viewer denied"},
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        self._as("outsider")
        self.assertEqual(self.client.get(f"/api/orchestration/tasks/{task_id}").status_code, 404)
        self.assertEqual(
            self.client.get(
                "/api/orchestration/tasks", params={"workflow_id": str(self.workflow.id)},
            ).status_code,
            404,
        )

    def test_z_success_and_denied_writes_are_audited(self):
        actions = {
            (event.action, event.result)
            for event in self.db.query(AuditEvent).filter(AuditEvent.project_id == self.project.id)
        }
        self.assertIn(("project.update", "success"), actions)
        self.assertIn(("project.update", "denied"), actions)
        self.assertIn(("workflow.create", "success"), actions)
        self.assertIn(("workflow.update", "denied"), actions)
        self.assertIn(("workflow_run.start", "success"), actions)
        self.assertIn(("workflow_run.start", "denied"), actions)
        self.assertIn(("workflow_run.cancel", "success"), actions)
        self.assertIn(("workflow.template_instantiate", "success"), actions)
        self.assertIn(("workflow.template_instantiate", "denied"), actions)
        self.assertIn(("dataset.upload", "success"), actions)
        self.assertIn(("dataset.upload", "denied"), actions)
        self.assertIn(("model.delete", "success"), actions)
        self.assertIn(("model.delete", "denied"), actions)
        self.assertIn(("model_library.create", "success"), actions)
        self.assertIn(("model_library.update", "denied"), actions)
        self.assertIn(("agent_task.create", "success"), actions)
        self.assertIn(("agent_task.message", "success"), actions)
        self.assertIn(("agent_task.message", "denied"), actions)


class TestProjectWriteAuditCompleteness(unittest.TestCase):
    EXPECTED = {
        "projects": {"project.create", "project.update", "project.delete", "project.batch_delete"},
        "project_access": {
            "project.member.add", "project.member.role_change", "project.member.remove",
        },
        "workflows": {"workflow.create", "workflow.update", "workflow.delete"},
        "workflows_direct": {"workflow.update", "workflow.delete"},
        "workflow_versions": {"workflow.publish", "workflow.restore"},
        "templates": {"workflow.template_instantiate"},
        "runs": {"workflow_run.start", "workflow_run.cancel"},
        "datasets": {
            "dataset.upload", "dataset.batch_upload", "dataset.import_zip",
        },
        "experiments": {"experiment.create"},
        "training": {
            "training_job.start", "training_job.stop", "training_job.resume",
            "training_job.automl_start", "training_job.delete",
        },
        "schedules": {
            "schedule.create", "schedule.update", "schedule.pause",
            "schedule.resume", "schedule.backfill",
        },
        "models": {"model.delete"},
        "model_library": {
            "model_library.create", "model_library.update",
            "model_library.delete", "model_library.batch_delete",
        },
        "orchestration": {
            "agent_task.review", "agent_task.message", "agent_task.update",
            "agent_task.delete", "agent_task.create", "agent_task.batch_delete",
        },
        "model_registry": {
            "registered_model.create", "registered_model.delete",
            "model_artifact.upload",
            "model_version.register", "model_version.approve",
            "model_version.reject", "model_version.archive",
            "inference_deployment.create", "inference_deployment.start",
            "inference_deployment.stop", "inference_deployment.delete",
        },
    }

    def test_every_project_write_module_declares_audited_actions(self):
        for module_name, expected_actions in self.EXPECTED.items():
            with self.subTest(module=module_name):
                module = importlib.import_module(f"app.api.{module_name}")
                mapping = getattr(module, "PROJECT_WRITE_ACTIONS", None)
                self.assertIsInstance(mapping, dict)
                self.assertEqual(set(mapping.values()), expected_actions)
                source = __import__("inspect").getsource(module)
                for action in expected_actions:
                    self.assertGreaterEqual(source.count(f'"{action}"'), 2, action)


if __name__ == "__main__":
    unittest.main()
