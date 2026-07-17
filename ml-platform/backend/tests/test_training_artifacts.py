import tempfile
import unittest
import uuid
from pathlib import Path

from app.database import Base, SessionLocal, engine
from app.models.model_library import ModelLibrary
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.artifact_service import ArtifactService
from app.services.training_service import TrainingService
from app.storage.local import LocalStorage


Base.metadata.create_all(bind=engine)


class TestTrainingArtifactLoop(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = SessionLocal()
        user = User(username=f"trainer_{uuid.uuid4().hex}", password_hash="hash", role="user")
        self.db.add(user)
        self.db.flush()
        project = Project(name="Training Project", owner_id=user.id)
        self.db.add(project)
        self.db.commit()
        self.user_id = user.id
        self.project_id = project.id
        source = Path(self.temp_dir.name) / "weld.csv"
        rows = ["current,force,quality"] + [
            f"{8 + index % 4},{3 + index % 2},{index % 2}" for index in range(40)
        ]
        source.write_text("\n".join(rows), encoding="utf-8")
        self.artifact_service = ArtifactService(
            self.db, LocalStorage(Path(self.temp_dir.name) / "artifact-store"),
        )
        self.dataset = self.artifact_service.create_dataset(self.project_id, source, "weld.csv")

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_training_creates_model_artifact_and_library_entry(self):
        job = TrainingJob(
            project_id=self.project_id,
            user_id=self.user_id,
            name="weld-quality-model",
            operator_id="random_forest_train",
            dataset_artifact_id=self.dataset.id,
            params={"target_column": "quality", "n_estimators": 10},
            status="pending",
        )
        self.db.add(job)
        self.db.commit()

        TrainingService(self.db, self.artifact_service).run(job.id)

        self.db.refresh(job)
        self.assertEqual(job.status, "completed")
        self.assertIsNotNone(job.model_artifact_id)
        self.assertIsNotNone(job.model_library_id)
        self.assertEqual([item["name"] for item in job.feature_schema], ["current", "force"])
        self.assertIn("accuracy", job.metrics)
        model = self.db.query(ModelLibrary).filter(ModelLibrary.id == job.model_library_id).one()
        self.assertEqual(model.status, "completed")
        self.assertEqual(model.dataset_artifact_id, self.dataset.id)


if __name__ == "__main__":
    unittest.main()
