"""Dashboard API integration tests."""
import sys, os, unittest, uuid
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine
from app.database import SessionLocal
from app.models.artifact import Artifact
from app.models.api_model import PlatformAPI
from app.models.model_library import ModelLibrary
from app.models.project import Project
from app.models.user import User

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login(username: str, password: str):
    response = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    return {"Authorization": "Bearer " + response.json()["access_token"]}


class TestDashboardAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        client.post(
            "/api/auth/register",
            json={"username": "admin", "password": "admin123"},
        )
        cls.admin_headers = login("admin", "admin123")

    def test_01_dashboard_stats(self):
        r = client.get("/api/dashboard/stats", headers=self.admin_headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        # Stats are nested under core_assets
        self.assertIn("core_assets", data)
        self.assertIn("total_algorithms", data["core_assets"])

    def test_02_dashboard_stats_business(self):
        r = client.get("/api/dashboard/stats", headers=self.admin_headers)
        data = r.json()
        self.assertIn("business_stats", data)
        self.assertIn("total_projects", data["business_stats"])

    def test_03_dashboard_stats_models(self):
        r = client.get("/api/dashboard/stats", headers=self.admin_headers)
        data = r.json()
        self.assertIn("model_status", data)

    def test_04_dashboard_algorithm_coverage(self):
        r = client.get("/api/dashboard/stats", headers=self.admin_headers)
        data = r.json()
        self.assertIn("algorithm_coverage", data)

    def test_05_dashboard_stats_types(self):
        r = client.get("/api/dashboard/stats", headers=self.admin_headers)
        data = r.json()
        self.assertIsInstance(data["core_assets"]["total_algorithms"], int)
        self.assertIsInstance(data["business_stats"]["total_projects"], int)
        self.assertIsInstance(data["algorithm_coverage"], list)

    def test_06_dataset_stats_include_artifact_datasets(self):
        before = client.get(
            "/api/dashboard/stats", headers=self.admin_headers,
        ).json()["core_assets"]["total_datasets"]
        with SessionLocal() as db:
            owner = User(username=f"dashboard-owner-{uuid.uuid4().hex}", password_hash="hash")
            db.add(owner)
            db.flush()
            project = Project(name=f"dashboard-project-{uuid.uuid4().hex}", owner_id=owner.id)
            db.add(project)
            db.flush()
            db.add(Artifact(
                project_id=project.id,
                name="dashboard-dataset.csv",
                type="dataset",
                storage_path="datasets/dashboard-dataset.csv",
                storage_uri="file:///datasets/dashboard-dataset.csv",
                file_size=16,
                format="csv",
            ))
            db.commit()

        after = client.get(
            "/api/dashboard/stats", headers=self.admin_headers,
        ).json()["core_assets"]["total_datasets"]
        self.assertGreaterEqual(after, before + 1)

    def test_07_regular_user_dashboard_is_scoped_but_admin_sees_all(self):
        marker = f"dashboard-scope-{uuid.uuid4().hex}"
        member_username = f"{marker}-member"
        member_password = "dashboard-member-password"
        registered = client.post(
            "/api/auth/register",
            json={
                "username": member_username,
                "password": member_password,
            },
        )
        self.assertEqual(registered.status_code, 200)
        member_headers = login(member_username, member_password)

        try:
            with SessionLocal() as db:
                member = db.query(User).filter(
                    User.username == member_username,
                ).one()
                outsider = User(
                    username=f"{marker}-outsider",
                    password_hash="hash",
                    role="engineer",
                )
                db.add(outsider)
                db.flush()

                visible_project = Project(
                    name=f"{marker}-visible-project",
                    owner_id=member.id,
                )
                hidden_project = Project(
                    name=f"{marker}-hidden-project",
                    owner_id=outsider.id,
                )
                db.add_all([visible_project, hidden_project])
                db.flush()
                db.add_all([
                    Artifact(
                        project_id=visible_project.id,
                        name=f"{marker}-visible.csv",
                        type="dataset",
                        storage_path=f"datasets/{marker}-visible.csv",
                        storage_uri=f"file:///datasets/{marker}-visible.csv",
                        file_size=16,
                        format="csv",
                        metadata_={"row_count": 3},
                    ),
                    Artifact(
                        project_id=hidden_project.id,
                        name=f"{marker}-hidden.csv",
                        type="dataset",
                        storage_path=f"datasets/{marker}-hidden.csv",
                        storage_uri=f"file:///datasets/{marker}-hidden.csv",
                        file_size=16,
                        format="csv",
                        metadata_={"row_count": 5},
                    ),
                    ModelLibrary(
                        name=f"{marker}-visible-model",
                        project_id=visible_project.id,
                        owner_id=member.id,
                        status="completed",
                    ),
                    ModelLibrary(
                        name=f"{marker}-hidden-model",
                        project_id=hidden_project.id,
                        owner_id=outsider.id,
                        status="completed",
                    ),
                    PlatformAPI(
                        name=f"{marker}-visible-api",
                        owner_id=member.id,
                        is_public=False,
                    ),
                    PlatformAPI(
                        name=f"{marker}-hidden-api",
                        owner_id=outsider.id,
                        is_public=False,
                    ),
                ])
                db.commit()

            member_stats = client.get(
                "/api/dashboard/stats", headers=member_headers,
            ).json()
            admin_stats = client.get(
                "/api/dashboard/stats", headers=self.admin_headers,
            ).json()

            self.assertLess(
                member_stats["business_stats"]["total_projects"],
                admin_stats["business_stats"]["total_projects"],
            )
            self.assertLess(
                member_stats["core_assets"]["total_datasets"],
                admin_stats["core_assets"]["total_datasets"],
            )
            self.assertLess(
                member_stats["core_assets"]["total_models"],
                admin_stats["core_assets"]["total_models"],
            )
            self.assertLess(
                member_stats["core_assets"]["total_apis"],
                admin_stats["core_assets"]["total_apis"],
            )
            self.assertEqual(member_stats["business_stats"]["total_users"], 1)
        finally:
            with SessionLocal() as db:
                db.query(PlatformAPI).filter(
                    PlatformAPI.name.like(f"{marker}%"),
                ).delete(synchronize_session=False)
                db.query(ModelLibrary).filter(
                    ModelLibrary.name.like(f"{marker}%"),
                ).delete(synchronize_session=False)
                db.query(Artifact).filter(
                    Artifact.name.like(f"{marker}%"),
                ).delete(synchronize_session=False)
                db.query(Project).filter(
                    Project.name.like(f"{marker}%"),
                ).delete(synchronize_session=False)
                db.query(User).filter(
                    User.username.in_([
                        member_username,
                        f"{marker}-outsider",
                    ]),
                ).delete(synchronize_session=False)
                db.commit()


if __name__ == "__main__":
    unittest.main()
