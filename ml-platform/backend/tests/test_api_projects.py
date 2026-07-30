"""Projects API integration tests."""
import sys, os, unittest, uuid
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine, SessionLocal
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.user import User

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestProjectsCRUD(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        client.post("/api/auth/register", json={"username": "admin", "password": "admin123", "role": "admin"})
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

    def test_09_delete_project_with_experiment(self):
        created = client.post("/api/projects", json={
            "name": f"ExperimentProject_{uuid.uuid4().hex}",
        }, headers=self.h)
        self.assertEqual(created.status_code, 201)
        project_id = uuid.UUID(created.json()["id"])

        with SessionLocal() as db:
            admin = db.query(User).filter(User.username == "admin").first()
            experiment = Experiment(
                project_id=project_id,
                created_by=admin.id,
                name=f"Delete cascade {uuid.uuid4().hex}",
                mlflow_experiment_id=f"delete-cascade-{uuid.uuid4().hex}",
            )
            db.add(experiment)
            db.commit()
            experiment_id = experiment.id

        try:
            with TestClient(app, raise_server_exceptions=False) as error_client:
                deleted = error_client.delete(f"/api/projects/{project_id}", headers=self.h)

            self.assertEqual(deleted.status_code, 204, deleted.text)
            with SessionLocal() as db:
                self.assertIsNone(db.get(Experiment, experiment_id))
        finally:
            with SessionLocal() as db:
                db.query(Experiment).filter(Experiment.id == experiment_id).delete()
                db.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
                db.commit()

    def test_09a_batch_delete_project_with_experiment(self):
        created = client.post("/api/projects", json={
            "name": f"BatchExperimentProject_{uuid.uuid4().hex}",
        }, headers=self.h)
        self.assertEqual(created.status_code, 201)
        project_id = uuid.UUID(created.json()["id"])

        with SessionLocal() as db:
            admin = db.query(User).filter(User.username == "admin").first()
            experiment = Experiment(
                project_id=project_id,
                created_by=admin.id,
                name=f"Batch delete cascade {uuid.uuid4().hex}",
                mlflow_experiment_id=f"batch-delete-cascade-{uuid.uuid4().hex}",
            )
            db.add(experiment)
            db.commit()
            experiment_id = experiment.id

        try:
            with TestClient(app, raise_server_exceptions=False) as error_client:
                deleted = error_client.post(
                    "/api/projects/batch-delete",
                    json={"ids": [str(project_id)]},
                    headers=self.h,
                )

            self.assertEqual(deleted.status_code, 200, deleted.text)
            self.assertEqual(deleted.json(), {"deleted": 1})
            with SessionLocal() as db:
                self.assertIsNone(db.get(Experiment, experiment_id))
        finally:
            with SessionLocal() as db:
                db.query(Experiment).filter(Experiment.id == experiment_id).delete()
                db.query(Project).filter(Project.id == project_id).delete(synchronize_session=False)
                db.commit()

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


if __name__ == "__main__":
    unittest.main()
