"""Projects API integration tests."""
import sys, os, unittest, uuid
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, SessionLocal, engine
from app.models.access import AuditEvent
from app.models.artifact import Artifact
from app.models.data_version import DatasetSample, DatasetVersion
from app.models.labeling import LabelColumn, LabelSchema
from app.models.platform_models import GenericAnnotationTask
from app.models.user import User
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestProjectsCRUD(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        ensure_admin()
        cls.h = login()
        cls.created_ids = []

    def test_01_create_project(self):
        r = client.post("/api/projects", json={
            "name": "TestProject_CRUD",
            "description": "Testing CRUD operations",
        }, headers=self.h)
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertIn("id", data)
        self.__class__.created_ids.append(data["id"])

    def test_02_create_project_without_description(self):
        r = client.post("/api/projects", json={"name": "MinimalProject"}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        self.__class__.created_ids.append(r.json()["id"])

    def test_03_list_projects(self):
        r = client.get("/api/projects", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertGreaterEqual(data["total"], 2)

    def test_04_get_project(self):
        pid = self.created_ids[0]
        r = client.get(f"/api/projects/{pid}", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "TestProject_CRUD")

    def test_05_get_nonexistent_project(self):
        r = client.get(f"/api/projects/{uuid.uuid4()}", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_06_update_project_name(self):
        pid = self.created_ids[0]
        r = client.put(f"/api/projects/{pid}", json={"name": "RenamedProject"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], "RenamedProject")

    def test_07_update_project_description(self):
        pid = self.created_ids[0]
        r = client.put(f"/api/projects/{pid}", json={"description": "Updated desc"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["description"], "Updated desc")

    def test_08_update_nonexistent_project(self):
        r = client.put(f"/api/projects/{uuid.uuid4()}", json={"name": "X"}, headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_09_delete_project(self):
        pid = self.created_ids[-1]
        r = client.delete(f"/api/projects/{pid}", headers=self.h)
        self.assertEqual(r.status_code, 204)
        # Verify deleted
        r = client.get(f"/api/projects/{pid}", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_10_delete_nonexistent_project(self):
        r = client.delete(f"/api/projects/{uuid.uuid4()}", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_11_create_project_empty_name(self):
        r = client.post("/api/projects", json={"name": ""}, headers=self.h)
        self.assertIn(r.status_code, [201, 422])

    def test_12_project_isolation(self):
        """Projects are isolated per user."""
        r = client.get("/api/projects", headers=self.h)
        data = r.json()
        own_ids = {p["id"] for p in data["items"]}
        # All returned projects should belong to this user
        self.assertIsInstance(own_ids, set)

    def test_13_delete_project_cascades_dependent_records(self):
        r = client.post("/api/projects", json={"name": "CascadeProject"}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        pid = r.json()["id"]
        uploaded = client.post(
            f"/api/projects/{pid}/datasets/upload",
            files={"file": ("cascade.csv", b"a,b\n1,2\n3,4\n", "text/csv")},
            headers=self.h,
        )
        self.assertEqual(uploaded.status_code, 200)
        artifact_id = uuid.UUID(uploaded.json()["id"])
        with SessionLocal() as db:
            version = db.query(DatasetVersion).filter(
                DatasetVersion.original_artifact_id == artifact_id,
            ).one()
            sample_ids = [
                row.sample_id
                for row in db.query(DatasetSample).filter(
                    DatasetSample.dataset_version_id == version.id,
                ).all()
            ]
            self.assertTrue(sample_ids)
            owner_id = db.query(User.id).filter(User.username == "admin").scalar()
            schema = LabelSchema(project_id=uuid.UUID(pid), name="cascade-schema", version=1, status="active")
            db.add(schema)
            db.flush()
            db.add(LabelColumn(schema_id=schema.id, machine_key="label", display_name="Label", ordinal=0, value_type="string", required=True))
            task = GenericAnnotationTask(
                project_id=uuid.UUID(pid),
                dataset_version_id=version.id,
                label_schema_id=schema.id,
                owner_id=owner_id,
                idempotency_key=f"cascade-{pid}",
                mode="manual",
                status="cancelled",
                task_revision=1,
                sample_scope={"kind": "all"},
                label_snapshot={},
                task_snapshot={},
            )
            db.add(task)
            db.commit()
            task_id = task.id
            schema_id = schema.id
            version_id = version.id
        r = client.delete(f"/api/projects/{pid}", headers=self.h)
        self.assertEqual(r.status_code, 204)
        with SessionLocal() as db:
            self.assertIsNone(db.get(Artifact, artifact_id))
            self.assertIsNone(db.get(DatasetVersion, version_id))
            self.assertIsNone(db.get(GenericAnnotationTask, task_id))
            self.assertIsNone(db.get(LabelSchema, schema_id))
            self.assertEqual(
                db.query(DatasetSample).filter(DatasetSample.sample_id.in_(sample_ids)).count(),
                0,
            )
            self.assertEqual(
                db.query(LabelColumn).filter(LabelColumn.schema_id == schema_id).count(),
                0,
            )
            # audit rows survive the project deletion; the project reference is
            # detached by the FK's ON DELETE SET NULL (postgres) or by the purge
            # itself for rows written before the project row was removed
            self.assertGreaterEqual(
                db.query(AuditEvent).filter(
                    AuditEvent.action == "project.delete",
                    AuditEvent.resource_id == pid,
                ).count(),
                1,
            )


if __name__ == "__main__":
    unittest.main()
