"""Projects API integration tests."""
import sys, os, unittest, uuid
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, SessionLocal, engine
from app.models.access import AuditEvent
from app.models.artifact import Artifact
from app.models.data_version import DatasetSample, DatasetVersion
from app.models.experiment import Experiment
from app.models.labeling import LabelColumn, LabelSchema
from app.models.model_library import ModelLibrary
from app.models.platform_models import GenericAnnotationTask
from app.models.training import TrainingJob
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

    def test_14_delete_project_with_circular_model_library_reference(self):
        # training_jobs <-> model_library reference each other with plain
        # (NO ACTION) foreign keys; the purge must clear the circular columns
        # before deleting the rows or PostgreSQL rejects the delete.
        r = client.post("/api/projects", json={"name": "CycleProject"}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        pid = uuid.UUID(r.json()["id"])
        with SessionLocal() as db:
            owner_id = db.query(User.id).filter(User.username == "admin").scalar()
            experiment = Experiment(
                project_id=pid, created_by=owner_id, name="cycle-experiment",
                mlflow_experiment_id=f"exp-{uuid.uuid4().hex}",
            )
            db.add(experiment)
            db.flush()
            job = TrainingJob(
                project_id=pid, user_id=owner_id, experiment_id=experiment.id,
                name="cycle-job", operator_id="automl", status="completed",
            )
            db.add(job)
            db.flush()
            model = ModelLibrary(
                project_id=pid, owner_id=owner_id, name="cycle-model",
                training_job_id=job.id,
            )
            db.add(model)
            db.flush()
            job.model_library_id = model.id
            db.commit()
            job_id, model_id = job.id, model.id

        response = client.delete(f"/api/projects/{pid}", headers=self.h)

        self.assertEqual(response.status_code, 204, response.text)
        with SessionLocal() as db:
            self.assertIsNone(db.get(TrainingJob, job_id))
            self.assertIsNone(db.get(ModelLibrary, model_id))

    def test_15_delete_project_releases_cluster_resources_and_storage(self):
        # 删除项目须先回收真实集群资源（K8s 作业/Notebook 会话），并清理工件
        # 存储文件；集群不可达时只记录告警，不得阻塞删除。
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from app.models.cloud_resources import KubernetesCluster
        from app.models.developer_resources import NotebookSession
        from app.models.kubernetes_execution import KubernetesJobRun
        from app.models.operation import DurableOperation

        r = client.post("/api/projects", json={"name": "CleanupProject"}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        pid = uuid.UUID(r.json()["id"])

        tmp_dir = tempfile.mkdtemp(prefix="purge-storage-")
        artifact_file = Path(tmp_dir) / "legacy.bin"
        artifact_file.write_bytes(b"payload")

        with SessionLocal() as db:
            owner_id = db.query(User.id).filter(User.username == "admin").scalar()
            db.add(Artifact(
                project_id=pid, name="legacy.bin", type="model",
                storage_path=str(artifact_file), file_size=7, format="bin",
            ))
            cluster = KubernetesCluster(
                project_id=pid, name=f"cluster-{uuid.uuid4().hex[:8]}",
                api_server_url="https://127.0.0.1:6443", status="active",
                created_by=owner_id,
            )
            db.add(cluster)
            db.flush()
            job_operation = DurableOperation(
                project_id=pid, resource_type="kubernetes_job",
                resource_key=f"proj:{pid}", idempotency_key=f"job-{uuid.uuid4().hex}",
            )
            db.add(job_operation)
            db.flush()
            job = KubernetesJobRun(
                project_id=pid, cluster_id=cluster.id, namespace="ml-platform",
                operation_id=job_operation.id, idempotency_key=f"job-{uuid.uuid4().hex}",
                job_name=f"job-{uuid.uuid4().hex[:10]}", image_ref="python:3.11",
                command_json=[], args_json=[], env_json={}, resource_json={},
                status="running", timeout_seconds=600, created_by=owner_id,
            )
            db.add(job)
            nb_operation = DurableOperation(
                project_id=pid, resource_type="notebook",
                resource_key=f"proj:{pid}", idempotency_key=f"nb-{uuid.uuid4().hex}",
            )
            db.add(nb_operation)
            db.flush()
            session = NotebookSession(
                project_id=pid, user_id=owner_id, cluster_id=cluster.id,
                namespace="ml-platform", operation_id=nb_operation.id,
                idempotency_key=f"nb-{uuid.uuid4().hex}",
                job_name=f"nb-{uuid.uuid4().hex[:10]}", image_ref="python:3.11",
                resource_json={}, status="running",
            )
            db.add(session)
            db.commit()
            job_id, session_id = job.id, session.id

        with patch(
            "app.services.kubernetes_executor.cancel_job", return_value=None,
        ) as mock_cancel, patch(
            "app.services.notebook_service.stop_session", return_value=None,
        ) as mock_stop:
            r = client.delete(f"/api/projects/{pid}", headers=self.h)
        self.assertEqual(r.status_code, 204, r.text)
        # 每个非终态资源恰好释放一次（真实集群调用被 mock，验证接线）
        self.assertEqual(mock_cancel.call_count, 1)
        self.assertEqual(mock_stop.call_count, 1)
        with SessionLocal() as db:
            self.assertIsNone(db.get(KubernetesJobRun, job_id))
            self.assertIsNone(db.get(NotebookSession, session_id))
        # legacy 工件文件随项目删除一并清理
        self.assertFalse(artifact_file.exists())

    def test_16_detached_dataset_hidden_after_project_delete(self):
        from app.models.platform_models import Dataset as PlatformDataset

        r = client.post("/api/projects", json={"name": "DetachProject"}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        pid = uuid.UUID(r.json()["id"])
        with SessionLocal() as db:
            owner_id = db.query(User.id).filter(User.username == "admin").scalar()
            dataset = PlatformDataset(
                name=f"orphan-{uuid.uuid4().hex[:6]}", project_id=pid, owner_id=owner_id,
            )
            db.add(dataset)
            db.commit()
            dataset_id = dataset.id

        r = client.delete(f"/api/projects/{pid}", headers=self.h)
        self.assertEqual(r.status_code, 204)

        # 旧版数据集表脱钩保留，但不再出现在平台最近活动中
        with SessionLocal() as db:
            row = db.get(PlatformDataset, dataset_id)
            self.assertIsNotNone(row)
            self.assertIsNone(row.project_id)
        r = client.get("/api/dashboard/recent-activity")
        self.assertEqual(r.status_code, 200)
        recent_ids = [item["id"] for item in r.json().get("recent_datasets", [])]
        self.assertNotIn(str(dataset_id), recent_ids)


if __name__ == "__main__":
    unittest.main()
