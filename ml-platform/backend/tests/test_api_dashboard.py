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
from app.models.model_registry import InferenceDeployment, ModelVersion, RegisteredModel
from app.models.project import Project
from app.models.training import TrainingJob
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
        with SessionLocal() as db:
            administrator = db.query(User).filter(User.username == "admin").one()
            administrator.role = "admin"
            db.commit()
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
            json={"username": member_username, "password": member_password},
        )
        self.assertEqual(registered.status_code, 200)
        member_headers = login(member_username, member_password)

        try:
            with SessionLocal() as db:
                member = db.query(User).filter(User.username == member_username).one()
                outsider = User(
                    username=f"{marker}-outsider",
                    password_hash="hash",
                    role="engineer",
                )
                db.add(outsider)
                db.flush()
                visible_project = Project(name=f"{marker}-visible-project", owner_id=member.id)
                hidden_project = Project(name=f"{marker}-hidden-project", owner_id=outsider.id)
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
                    TrainingJob(
                        project_id=visible_project.id,
                        user_id=member.id,
                        name=f"{marker}-visible-model",
                        status="completed",
                    ),
                    TrainingJob(
                        project_id=hidden_project.id,
                        user_id=outsider.id,
                        name=f"{marker}-hidden-model",
                        status="completed",
                    ),
                    PlatformAPI(name=f"{marker}-visible-api", owner_id=member.id, is_public=False),
                    PlatformAPI(name=f"{marker}-hidden-api", owner_id=outsider.id, is_public=False),
                ])
                db.commit()

            member_stats = client.get(
                "/api/dashboard/stats", headers=member_headers,
            ).json()
            admin_stats = client.get(
                "/api/dashboard/stats", headers=self.admin_headers,
            ).json()
            self.assertLess(member_stats["business_stats"]["total_projects"], admin_stats["business_stats"]["total_projects"])
            self.assertLess(member_stats["core_assets"]["total_datasets"], admin_stats["core_assets"]["total_datasets"])
            self.assertLess(member_stats["core_assets"]["total_models"], admin_stats["core_assets"]["total_models"])
            self.assertLess(member_stats["core_assets"]["total_apis"], admin_stats["core_assets"]["total_apis"])
            self.assertEqual(member_stats["business_stats"]["total_users"], 1)
        finally:
            with SessionLocal() as db:
                db.query(PlatformAPI).filter(PlatformAPI.name.like(f"{marker}%")).delete(synchronize_session=False)
                db.query(TrainingJob).filter(TrainingJob.name.like(f"{marker}%")).delete(synchronize_session=False)
                db.query(Artifact).filter(Artifact.name.like(f"{marker}%")).delete(synchronize_session=False)
                db.query(Project).filter(Project.name.like(f"{marker}%")).delete(synchronize_session=False)
                db.query(User).filter(User.username.in_([member_username, f"{marker}-outsider"])).delete(synchronize_session=False)
                db.commit()

    def test_08_model_status_uses_training_jobs_and_running_deployments(self):
        marker = f"dashboard-live-{uuid.uuid4().hex}"
        before = client.get(
            "/api/dashboard/stats", headers=self.admin_headers,
        ).json()

        with SessionLocal() as db:
            owner = User(username=f"{marker}-owner", password_hash="hash")
            db.add(owner)
            db.flush()
            project = Project(name=f"{marker}-project", owner_id=owner.id)
            db.add(project)
            db.flush()
            artifact = Artifact(
                project_id=project.id,
                name=f"{marker}.joblib",
                type="model",
                storage_path=f"models/{marker}.joblib",
                storage_uri=f"file:///models/{marker}.joblib",
                file_size=16,
                format="joblib",
            )
            db.add(artifact)
            db.flush()
            library = ModelLibrary(
                name=f"{marker}-library",
                project_id=project.id,
                owner_id=owner.id,
                status="completed",
                model_artifact_id=artifact.id,
            )
            db.add(library)
            db.flush()
            jobs = [
                TrainingJob(project_id=project.id, user_id=owner.id, name=f"{marker}-queued", status="queued"),
                TrainingJob(project_id=project.id, user_id=owner.id, name=f"{marker}-running", status="running"),
                TrainingJob(project_id=project.id, user_id=owner.id, name=f"{marker}-completed", status="completed"),
                TrainingJob(
                    project_id=project.id,
                    user_id=owner.id,
                    name=f"{marker}-published",
                    status="completed",
                    model_library_id=library.id,
                    model_artifact_id=artifact.id,
                ),
                TrainingJob(project_id=project.id, user_id=owner.id, name=f"{marker}-failed", status="failed"),
                TrainingJob(project_id=project.id, user_id=owner.id, name=f"{marker}-cancelled", status="cancelled"),
            ]
            model = RegisteredModel(
                project_id=project.id,
                name=f"{marker}-registered",
                created_by_id=owner.id,
            )
            db.add_all([*jobs, model])
            db.flush()
            version = ModelVersion(
                registered_model_id=model.id,
                version_number=1,
                source_kind="platform_joblib",
                source_model_library_id=library.id,
                source_artifact_id=artifact.id,
                onnx_artifact_id=artifact.id,
                created_by_id=owner.id,
            )
            api = PlatformAPI(name=f"{marker}-api", owner_id=owner.id, is_public=False)
            db.add_all([version, api])
            db.flush()
            db.add(InferenceDeployment(
                project_id=project.id,
                name=f"{marker}-deployment",
                model_version_id=version.id,
                desired_state="running",
                observed_state="running",
                created_by_id=owner.id,
            ))
            db.commit()

        after_create = client.get(
            "/api/dashboard/stats", headers=self.admin_headers,
        ).json()
        self.assertEqual(
            after_create["model_status"]["training"] - before["model_status"]["training"],
            2,
        )
        self.assertEqual(
            after_create["model_status"]["completed"] - before["model_status"]["completed"],
            1,
        )
        self.assertEqual(
            after_create["model_status"]["published"] - before["model_status"]["published"],
            1,
        )
        self.assertEqual(
            after_create["core_assets"]["total_models"] - before["core_assets"]["total_models"],
            4,
        )
        self.assertEqual(
            after_create["core_assets"]["total_apis"] - before["core_assets"]["total_apis"],
            1,
        )

        with SessionLocal() as db:
            db.query(TrainingJob).filter(TrainingJob.name == f"{marker}-completed").delete()
            db.query(PlatformAPI).filter(PlatformAPI.name == f"{marker}-api").delete()
            db.commit()

        after_delete = client.get(
            "/api/dashboard/stats", headers=self.admin_headers,
        ).json()
        self.assertEqual(after_delete["model_status"]["completed"], before["model_status"]["completed"])
        self.assertEqual(after_delete["core_assets"]["total_models"], before["core_assets"]["total_models"] + 3)
        self.assertEqual(after_delete["core_assets"]["total_apis"], before["core_assets"]["total_apis"])

        with SessionLocal() as db:
            db.query(InferenceDeployment).filter(InferenceDeployment.name == f"{marker}-deployment").delete()
            db.query(ModelVersion).filter(ModelVersion.registered_model_id.in_(
                db.query(RegisteredModel.id).filter(RegisteredModel.name == f"{marker}-registered")
            )).delete(synchronize_session=False)
            db.query(RegisteredModel).filter(RegisteredModel.name == f"{marker}-registered").delete()
            db.query(TrainingJob).filter(TrainingJob.name.like(f"{marker}%")).delete(synchronize_session=False)
            db.query(ModelLibrary).filter(ModelLibrary.name == f"{marker}-library").delete()
            db.query(Artifact).filter(Artifact.name == f"{marker}.joblib").delete()
            db.query(Project).filter(Project.name == f"{marker}-project").delete()
            db.query(User).filter(User.username == f"{marker}-owner").delete()
            db.commit()

if __name__ == "__main__":
    unittest.main()
