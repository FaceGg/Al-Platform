"""Datasets API integration tests."""
import sys, os, unittest, uuid, io
from datetime import datetime, timezone
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, SessionLocal, engine
from app.models.artifact import Artifact
from app.models.data_version import DatasetVersion
from app.models.experiment import Experiment
from app.models.model_library import ModelLibrary
from app.models.platform_models import GenericAnnotationTask
from app.models.training import TrainingJob
from app.models.user import User
from app.services.artifact_service import build_artifact_service
from tests.auth_test_support import ensure_admin

Base.metadata.create_all(bind=engine)
client = TestClient(app)


def login():
    r = client.post("/api/auth/login", data={"username": "admin", "password": "admin123"})
    return {"Authorization": "Bearer " + r.json()["access_token"]}


class TestLargeDatasetPreviewAndExport(unittest.TestCase):
    """limit=0 previews of hundreds of thousands of rows once OOM-killed
    backend workers; previews are capped and CSV export streams."""

    @classmethod
    def setUpClass(cls):
        ensure_admin(username="large_dataset_admin")
        r = client.post(
            "/api/auth/login", data={"username": "large_dataset_admin", "password": "admin123"},
        )
        cls.h = {"Authorization": "Bearer " + r.json()["access_token"]}
        r = client.post("/api/projects", json={"name": "LargeDatasetProject"}, headers=cls.h)
        cls.project_id = r.json()["id"]
        rows = 600  # above the 500-row preview cap
        content = "idx,value\n" + "".join(
            f"{index},{index * 2}\n" for index in range(rows)
        )
        r = client.post(
            f"/api/projects/{cls.project_id}/datasets/upload",
            files={"file": ("large.csv", io.BytesIO(content.encode("utf-8")), "text/csv")},
            headers=cls.h,
        )
        assert r.status_code == 200, r.text
        cls.dataset_id = r.json()["id"]
        cls.rows = rows

    def test_preview_limit_zero_is_capped(self):
        r = client.get(f"/api/datasets/{self.dataset_id}/preview?limit=0", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data["preview"]), 500)
        self.assertEqual(data["total_rows"], self.rows)

    def test_preview_explicit_limit_respected(self):
        r = client.get(f"/api/datasets/{self.dataset_id}/preview?limit=50", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["preview"]), 50)

    def test_export_csv_streams_all_rows(self):
        r = client.get(f"/api/datasets/{self.dataset_id}/export?format=csv", headers=self.h)
        self.assertEqual(r.status_code, 200)
        # The original filename must ride along for the frontend download.
        self.assertIn("filename*=utf-8''large.csv", r.headers["content-disposition"])
        # Excel needs the UTF-8 BOM to render Chinese correctly.
        self.assertTrue(r.content.startswith(b"\xef\xbb\xbf"))
        lines = r.content.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(lines[0], "idx,value")
        self.assertEqual(len(lines), self.rows + 1)
        self.assertEqual(lines[-1], f"{self.rows - 1},{(self.rows - 1) * 2}")

    def test_download_returns_original_file(self):
        r = client.get(f"/api/datasets/{self.dataset_id}/download", headers=self.h)
        self.assertEqual(r.status_code, 200)
        lines = r.content.decode("utf-8").strip().splitlines()
        self.assertEqual(len(lines), self.rows + 1)


class TestDatasetsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure admin exists for fresh DB
        ensure_admin()
        cls.h = login()
        r = client.post("/api/projects", json={"name": "DatasetTestProject"}, headers=cls.h)
        cls.project_id = r.json()["id"]
        cls.artifact_ids = []
        cls.csv_path = ""

    def _make_csv(self, content="col1,col2\n1,2\n3,4\n5,6\n"):
        return io.BytesIO(content.encode("utf-8"))

    def test_01_upload_csv_dataset(self):
        csv = self._make_csv()
        r = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("test.csv", csv, "text/csv")},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("id", data)
        self.assertEqual(data["artifact_id"], data["id"])
        self.assertEqual(data["row_count"], 3)
        self.assertEqual([column["name"] for column in data["schema"]], ["col1", "col2"])
        self.assertEqual(len(data["sha256"]), 64)
        self.__class__.artifact_ids.append(data["id"])

    def test_02_upload_second_csv(self):
        csv = self._make_csv("col1,col2\n10,20\n30,40\n50,60\n")
        r = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("test2.csv", csv, "text/csv")},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.__class__.artifact_ids.append(data["id"])

    def test_03_preview_dataset(self):
        aid = self.artifact_ids[0]
        r = client.get(f"/api/datasets/{aid}/preview", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("columns", data)
        self.assertIn("preview", data)
        self.assertIn("total_rows", data)

    def test_03_preview_limit_returns_all_rows_when_zero(self):
        rows = "\n".join(f"{index},{index * 10}" for index in range(1, 16))
        csv = self._make_csv(f"col1,col2\n{rows}\n")
        r = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("preview-limit.csv", csv, "text/csv")},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200)
        aid = r.json()["id"]

        default = client.get(f"/api/datasets/{aid}/preview", headers=self.h).json()
        self.assertEqual(len(default["preview"]), 10)
        self.assertEqual(default["total_rows"], 15)

        capped = client.get(f"/api/datasets/{aid}/preview?limit=2", headers=self.h).json()
        self.assertEqual(len(capped["preview"]), 2)

        everything = client.get(f"/api/datasets/{aid}/preview?limit=0", headers=self.h).json()
        self.assertEqual(len(everything["preview"]), 15)
        self.assertEqual(everything["total_rows"], 15)

    def test_03_raw_download_matches_stored_dataset_bytes(self):
        aid = self.artifact_ids[0]
        response = client.get(f"/api/datasets/{aid}/download", headers=self.h)

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, b"col1,col2\n1,2\n3,4\n5,6\n")
        self.assertIn("test.csv", response.headers["content-disposition"])

    def test_03a_list_project_dataset_artifacts(self):
        r = client.get(f"/api/projects/{self.project_id}/datasets", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreaterEqual(data["total"], 2)
        self.assertTrue(all(item["type"] == "dataset" for item in data["items"]))
        self.assertTrue(all(item["project_id"] == self.project_id for item in data["items"]))
        self.assertTrue(all("storage_path" not in item for item in data["items"]))

    def test_03b_list_all_owned_datasets_without_selecting_a_project(self):
        r = client.get("/api/datasets", headers=self.h)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreaterEqual(data["total"], 2)
        self.assertTrue(all(item["type"] == "dataset" for item in data["items"]))
        self.assertTrue(all(item["project_id"] for item in data["items"]))

    def test_03b1_listed_dataset_includes_its_project_name(self):
        r = client.get("/api/datasets", headers=self.h)
        self.assertEqual(r.status_code, 200)
        item = next(entry for entry in r.json()["items"] if entry["id"] == self.artifact_ids[0])
        self.assertEqual(item["project_name"], "DatasetTestProject")

    def test_03b2_dataset_lists_hide_internal_normalized_artifact(self):
        r = client.get("/api/datasets", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(any(item["name"] == "normalized.csv" for item in r.json()["items"]))

    def test_03c_delete_allows_dataset_artifact_without_task_reference(self):
        uploaded = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("immutable.csv", self._make_csv(), "text/csv")},
            headers=self.h,
        )
        self.assertEqual(uploaded.status_code, 200)
        dataset_id = uploaded.json()["id"]
        response = client.delete(f"/api/datasets/{dataset_id}", headers=self.h)
        self.assertEqual(response.status_code, 204)

    def test_03c1_delete_rejects_dataset_artifact_used_by_annotation_task(self):
        uploaded = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("task-used.csv", self._make_csv(), "text/csv")},
            headers=self.h,
        )
        self.assertEqual(uploaded.status_code, 200)
        dataset_id = uploaded.json()["id"]
        with SessionLocal() as db:
            version = db.query(DatasetVersion).filter(
                DatasetVersion.original_artifact_id == uuid.UUID(dataset_id),
            ).one()
            owner_id = db.query(User.id).filter(User.username == "admin").scalar()
            task = GenericAnnotationTask(
                project_id=uuid.UUID(self.project_id),
                dataset_version_id=version.id,
                label_schema_id=uuid.uuid4(),
                owner_id=owner_id,
                idempotency_key=f"task-used-{dataset_id}",
                task_snapshot={},
                label_snapshot={},
                status="running",
            )
            db.add(task)
            db.commit()
        response = client.delete(f"/api/datasets/{dataset_id}", headers=self.h)
        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "DATASET_IN_USE")
        self.assertEqual(detail["task_status"], "running")

    def test_03c2_delete_allows_dataset_used_only_by_archived_task(self):
        uploaded = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("archived-task.csv", self._make_csv(), "text/csv")},
            headers=self.h,
        )
        self.assertEqual(uploaded.status_code, 200)
        dataset_id = uploaded.json()["id"]
        with SessionLocal() as db:
            version = db.query(DatasetVersion).filter(
                DatasetVersion.original_artifact_id == uuid.UUID(dataset_id),
            ).one()
            owner_id = db.query(User.id).filter(User.username == "admin").scalar()
            task = GenericAnnotationTask(
                project_id=uuid.UUID(self.project_id),
                dataset_version_id=version.id,
                label_schema_id=uuid.uuid4(),
                owner_id=owner_id,
                idempotency_key=f"archived-task-{dataset_id}",
                task_snapshot={},
                label_snapshot={},
                status="cancelled",
                archived_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(task)
            db.commit()
        response = client.delete(f"/api/datasets/{dataset_id}", headers=self.h)
        self.assertEqual(response.status_code, 204)

    def test_03d_zero_row_dataset_can_be_deleted(self):
        uploaded = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("empty.csv", self._make_csv("col1,col2\n"), "text/csv")},
            headers=self.h,
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.json()["row_count"], 0)
        dataset_id = uploaded.json()["id"]
        deleted = client.delete(f"/api/datasets/{dataset_id}", headers=self.h)
        self.assertEqual(deleted.status_code, 204)

    def test_03e_delete_unreferenced_legacy_artifact(self):
        uploaded = client.post(
            f"/api/projects/{self.project_id}/datasets/batch-upload",
            files=[("files", ("legacy.bin", io.BytesIO(b"legacy"), "application/octet-stream"))],
            headers=self.h,
        )
        self.assertEqual(uploaded.status_code, 200)
        dataset_id = uploaded.json()["files"][0]["artifact_id"]
        deleted = client.delete(f"/api/datasets/{dataset_id}", headers=self.h)
        self.assertEqual(deleted.status_code, 204)

    def test_04_preview_nonexistent_dataset(self):
        r = client.get(f"/api/datasets/{uuid.uuid4()}/preview", headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_05_upload_to_nonexistent_project(self):
        csv = self._make_csv()
        r = client.post(
            f"/api/projects/{uuid.uuid4()}/datasets/upload",
            files={"file": ("test.csv", csv, "text/csv")},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 404)

    def test_06_upload_large_csv(self):
        """Upload a CSV with 500 rows."""
        csv = io.BytesIO(("col1,col2\n" + "\n".join(f"{i},{i*2}" for i in range(500))).encode("utf-8"))
        r = client.post(
            f"/api/projects/{self.project_id}/datasets/upload",
            files={"file": ("large.csv", csv, "text/csv")},
            headers=self.h,
        )
        self.assertEqual(r.status_code, 200)

    def test_07_export_dataset(self):
        r = client.get(f"/api/projects/{self.project_id}/datasets/export?format=csv", headers=self.h)
        self.assertIn(r.status_code, [200, 404])

    def test_08_batch_upload_datasets(self):
        csv1 = ("col1,col2\n1,2\n", "batch1.csv", "text/csv")
        csv2 = ("a,b\nx,y\n", "batch2.csv", "text/csv")
        files = [
            ("files", csv1),
            ("files", csv2),
        ]
        r = client.post(
            f"/api/projects/{self.project_id}/datasets/batch",
            files=files,
            headers=self.h,
        )
        self.assertIn(r.status_code, [200, 201])
        if r.status_code == 200:
            data = r.json()
            self.assertIn("success", data)

    def test_09_list_project_model_artifacts_for_canvas_picker(self):
        # 画布闭环算子的模型制品参数走下拉：端点须只列项目内 model 工件。
        db = SessionLocal()
        try:
            art = Artifact(
                project_id=uuid.UUID(self.project_id),
                name=f"picker-model-{uuid.uuid4().hex[:6]}.joblib", type="model",
                storage_path="", storage_uri="s3://test/picker-model.joblib",
                file_size=8, format="joblib",
            )
            db.add(art)
            db.commit()
            model_name = art.name
        finally:
            db.close()

        r = client.get(f"/api/projects/{self.project_id}/model-artifacts", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertGreaterEqual(data["total"], 1)
        self.assertTrue(all(item["id"] and item["name"] for item in data["items"]))
        names = [item["name"] for item in data["items"]]
        self.assertIn(model_name, names)
        # 数据集工件不得混入模型列表
        datasets = client.get(f"/api/projects/{self.project_id}/datasets", headers=self.h).json()
        dataset_names = {item["name"] for item in datasets["items"]}
        self.assertFalse(any(name in dataset_names for name in names))

    def test_10_model_artifacts_filter_orphans_and_format(self):
        # ①ONNX 工件不进画布下拉（load_model_artifact 仅支持 joblib）；
        # ②来源自动建模任务已删除且未被注册/模型库引用的 automl 工件（孤儿）不列出；
        # ③任务仍存在的 automl 工件与手动上传工件正常列出；
        # ④任务已删但已被模型库引用的 automl 工件保留；
        # ⑤展示名统一为「项目名称-实验名称-算法名称」。
        db = SessionLocal()
        suffix = uuid.uuid4().hex[:6]
        try:
            admin = db.query(User).filter(User.username == "admin").first()
            experiment = Experiment(
                project_id=uuid.UUID(self.project_id), created_by=admin.id,
                name=f"exp-{suffix}", mlflow_experiment_id=f"mlflow-{suffix}",
            )
            db.add(experiment)
            db.flush()
            alive_job = TrainingJob(
                project_id=uuid.UUID(self.project_id), user_id=admin.id,
                name=f"alive-job-{suffix}", status="completed",
                experiment_id=experiment.id,
            )
            db.add(alive_job)
            db.flush()
            rows = [
                ("alive-automl.joblib", "joblib",
                 {"source": "automl", "training_job_id": str(alive_job.id),
                  "best_algorithm": "random_forest"},
                 f"DatasetTestProject-exp-{suffix}-random_forest"),
                ("orphan-automl.joblib", "joblib",
                 {"source": "automl", "training_job_id": str(uuid.uuid4())},
                 None),
                ("manual-upload.joblib", "joblib", {"source": "upload"},
                 f"manual-upload.joblib-{suffix}"),
                ("converted.onnx", "onnx", {}, None),
            ]
            expected_visible = []
            for name, fmt, metadata, expected_display in rows:
                art = Artifact(
                    project_id=uuid.UUID(self.project_id),
                    name=f"{name}-{suffix}", type="model",
                    storage_path="", storage_uri=f"s3://test/{name}",
                    file_size=8, format=fmt, metadata_=metadata,
                )
                db.add(art)
                if fmt == "joblib" and not name.startswith("orphan"):
                    expected_visible.append(expected_display)
            db.flush()
            # 任务已删但已导入模型库的工件：应保留（实验名不可考，展示名保持原名）
            library_artifact = Artifact(
                project_id=uuid.UUID(self.project_id),
                name=f"library-automl.joblib-{suffix}", type="model",
                storage_path="", storage_uri="s3://test/library-automl.joblib",
                file_size=8, format="joblib",
                metadata_={"source": "automl", "training_job_id": str(uuid.uuid4())},
            )
            db.add(library_artifact)
            db.flush()
            db.add(ModelLibrary(
                name=f"library-entry-{suffix}", owner_id=admin.id,
                project_id=uuid.UUID(self.project_id),
                model_artifact_id=library_artifact.id, format="joblib",
            ))
            expected_visible.append(library_artifact.name)
            db.commit()
        finally:
            db.close()

        r = client.get(f"/api/projects/{self.project_id}/model-artifacts", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        items = r.json()["items"]
        names_listed = [item["name"] for item in items]
        for expected_display in expected_visible:
            self.assertIn(expected_display, names_listed)
        # 存储名不再直接透出（统一为「项目-实验-算法」展示名）
        self.assertNotIn(f"alive-automl.joblib-{suffix}", names_listed)
        self.assertNotIn(f"orphan-automl.joblib-{suffix}", names_listed)
        self.assertNotIn(f"converted.onnx-{suffix}", names_listed)
        # 端点只返回 joblib（ONNX 不进画布下拉）
        self.assertTrue(all(item.get("format") == "joblib" for item in items))


if __name__ == "__main__":
    unittest.main()
