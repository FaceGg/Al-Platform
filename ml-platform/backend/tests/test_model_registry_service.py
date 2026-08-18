import io
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sklearn.linear_model import LogisticRegression

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_library import ModelLibrary
from app.models.model_registry import ModelCard, ModelVersion, RegisteredModel
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.services.artifact_service import ArtifactAccessError, ArtifactService
from app.services.model_registry import ModelRegistryError, ModelRegistryService
from app.services.onnx_conversion import ConversionResult
from app.storage.local import LocalStorage


class TestModelRegistryService(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.Session()
        self.owner = User(username="registry-service-owner", password_hash="hash")
        self.db.add(self.owner)
        self.db.flush()
        self.project = Project(name="Registry service", owner_id=self.owner.id)
        self.other_project = Project(name="Other registry", owner_id=self.owner.id)
        self.db.add_all([self.project, self.other_project])
        self.db.flush()
        self.storage = LocalStorage(self.root / "storage")
        self.artifacts = ArtifactService(self.db, self.storage)
        self.service = ModelRegistryService(
            artifact_service=self.artifacts,
            converter=self._fake_converter,
            validator=self._fake_validator,
        )
        self.model = self.service.create_registered_model(
            self.db,
            project_id=self.project.id,
            actor_id=self.owner.id,
            name="Weld Fault",
            description="Classifier",
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temporary.cleanup()

    @staticmethod
    def _result(destination: Path, feature_schema=None, output_schema=None):
        return ConversionResult(
            input_names=("features",),
            output_names=("label", "probabilities"),
            opset=17,
            sha256="b" * 64,
            size=destination.stat().st_size,
            converter="test-converter",
            feature_schema=feature_schema or [
                {"name": "current", "dtype": "float64"},
                {"name": "voltage", "dtype": "float64"},
            ],
            output_schema=output_schema or {
                "name": "fault", "dtype": "int64", "task": "classification",
            },
        )

    def _fake_converter(self, source, destination, **_kwargs):
        destination.write_bytes(b"valid-onnx")
        return self._result(destination)

    def _fake_validator(self, path, feature_schema, output_schema):
        return self._result(path, feature_schema, output_schema)

    def _platform_source(self, project=None):
        project = project or self.project
        job = TrainingJob(
            project_id=project.id,
            user_id=self.owner.id,
            name=f"training-{uuid.uuid4().hex}",
            status="completed",
            feature_schema=[
                {"name": "current", "dtype": "float64"},
                {"name": "voltage", "dtype": "float64"},
            ],
            target_schema={
                "name": "fault", "dtype": "int64", "task": "classification",
            },
        )
        self.db.add(job)
        self.db.flush()
        source_path = self.root / f"{job.id}.joblib"
        fitted = LogisticRegression().fit(
            np.asarray([[0.0, 0.0], [1.0, 1.0]]), np.asarray([0, 1]),
        )
        joblib.dump({
            "model": fitted,
            "feature_schema": job.feature_schema,
            "target_schema": job.target_schema,
        }, source_path)
        artifact = self.artifacts.create_from_file(
            project.id,
            source_path,
            source_path.name,
            "model",
            metadata={"source": "training", "training_job_id": str(job.id)},
            commit=False,
        )
        library = ModelLibrary(
            name=job.name,
            project_id=project.id,
            owner_id=self.owner.id,
            status="completed",
            framework="scikit-learn",
            backbone="LogisticRegression",
            metrics={"accuracy": 0.95},
            format="joblib",
            training_job_id=job.id,
            model_artifact_id=artifact.id,
        )
        self.db.add(library)
        self.db.flush()
        job.model_artifact_id = artifact.id
        job.model_library_id = library.id
        self.db.commit()
        return library, artifact

    def test_stream_upload_enforces_limit_and_records_integrity(self):
        artifact = self.artifacts.create_from_stream(
            self.project.id,
            io.BytesIO(b"onnx-payload"),
            "model.onnx",
            "model",
            metadata={"source": "upload"},
            max_bytes=64,
        )
        self.assertEqual(artifact.file_size, 12)
        self.assertEqual(len(artifact.metadata_["sha256"]), 64)
        self.assertTrue(self.storage.exists(artifact.storage_uri))

        with self.assertRaises(ArtifactAccessError):
            self.artifacts.create_from_stream(
                self.project.id,
                io.BytesIO(b"too-large"),
                "large.onnx",
                "model",
                max_bytes=4,
            )

    def test_platform_source_requires_training_provenance(self):
        library, artifact = self._platform_source()
        artifact.metadata_ = {"source": "upload"}
        self.db.commit()

        with self.assertRaises(ModelRegistryError) as raised:
            self.service.register_platform_version(
                self.db,
                model_id=self.model.id,
                source_model_library_id=library.id,
                actor_id=self.owner.id,
            )
        self.assertEqual(raised.exception.code, "MODEL_SOURCE_UNTRUSTED")

    def test_cross_project_source_is_hidden(self):
        library, _artifact = self._platform_source(self.other_project)
        with self.assertRaises(ModelRegistryError) as raised:
            self.service.register_platform_version(
                self.db,
                model_id=self.model.id,
                source_model_library_id=library.id,
                actor_id=self.owner.id,
            )
        self.assertEqual(raised.exception.code, "MODEL_SOURCE_NOT_FOUND")

    def test_platform_registration_creates_separate_onnx_artifact_and_snapshot(self):
        library, artifact = self._platform_source()
        version = self.service.register_platform_version(
            self.db,
            model_id=self.model.id,
            source_model_library_id=library.id,
            actor_id=self.owner.id,
        )
        self.assertEqual(version.version_number, 1)
        self.assertNotEqual(version.onnx_artifact_id, artifact.id)
        self.assertEqual(version.metrics, {"accuracy": 0.95})
        self.assertEqual(version.conversion_metadata["opset"], 17)
        library.metrics["accuracy"] = 0.1
        self.db.commit()
        self.assertEqual(version.metrics, {"accuracy": 0.95})

    def test_platform_registration_flushes_version_before_model_card(self):
        library, _artifact = self._platform_source()
        self.db.autoflush = False

        version = self.service.register_platform_version(
            self.db,
            model_id=self.model.id,
            source_model_library_id=library.id,
            actor_id=self.owner.id,
        )

        card = self.db.query(ModelCard).filter_by(model_version_id=version.id).one()
        self.assertEqual(card.model_version_id, version.id)

    def test_registration_compensates_onnx_when_commit_fails(self):
        library, _artifact = self._platform_source()
        original_commit = self.db.commit
        with patch.object(self.db, "commit", side_effect=RuntimeError("db failed")):
            with self.assertRaisesRegex(RuntimeError, "db failed"):
                self.service.register_platform_version(
                    self.db,
                    model_id=self.model.id,
                    source_model_library_id=library.id,
                    actor_id=self.owner.id,
                )
        self.db.rollback()
        original_commit()
        onnx_rows = self.db.query(Artifact).filter(Artifact.format == "onnx").all()
        self.assertEqual(onnx_rows, [])

    def test_versions_allocate_monotonically(self):
        library, _artifact = self._platform_source()
        first = self.service.register_platform_version(
            self.db, model_id=self.model.id,
            source_model_library_id=library.id, actor_id=self.owner.id,
        )
        second = self.service.register_platform_version(
            self.db, model_id=self.model.id,
            source_model_library_id=library.id, actor_id=self.owner.id,
        )
        self.assertEqual((first.version_number, second.version_number), (1, 2))

    def test_outer_transaction_can_compensate_converted_artifact(self):
        library, _artifact = self._platform_source()
        version = self.service.register_platform_version(
            self.db,
            model_id=self.model.id,
            source_model_library_id=library.id,
            actor_id=self.owner.id,
            commit=False,
        )
        onnx = self.db.query(Artifact).filter_by(id=version.onnx_artifact_id).one()
        uri = onnx.storage_uri

        self.db.rollback()
        self.service.compensate_version_artifact(uri)

        self.assertFalse(self.storage.exists(uri))

    def test_onnx_registration_requires_project_owned_onnx(self):
        source = self.root / "uploaded.onnx"
        source.write_bytes(b"uploaded-onnx")
        artifact = self.artifacts.create_from_file(
            self.project.id, source, source.name, "model",
            metadata={"source": "upload"},
        )
        version = self.service.register_onnx_version(
            self.db, model_id=self.model.id, source_artifact_id=artifact.id,
            actor_id=self.owner.id,
            feature_schema=[{"name": "current", "dtype": "float64"}],
            output_schema={"name": "fault", "dtype": "int64", "task": "classification"},
        )
        self.assertEqual(version.source_kind, "onnx_artifact")
        self.assertEqual(version.onnx_artifact_id, artifact.id)

    def test_registration_creates_model_card_with_generated_evidence(self):
        source = self.root / "card-source.onnx"
        source.write_bytes(b"uploaded-onnx")
        artifact = self.artifacts.create_from_file(
            self.project.id, source, source.name, "model",
            metadata={"source": "upload", "dataset_artifact_id": "dataset-1"},
        )
        self.db.autoflush = False
        version = self.service.register_onnx_version(
            self.db, model_id=self.model.id, source_artifact_id=artifact.id,
            actor_id=self.owner.id,
            feature_schema=[{"name": "current", "dtype": "float64"}],
            output_schema={"name": "fault", "dtype": "int64"},
        )
        card = self.db.query(ModelCard).filter_by(model_version_id=version.id).one()
        self.assertEqual(card.input_schema, version.feature_schema)
        self.assertEqual(card.training_data_lineage["dataset_artifact_id"], "dataset-1")

    def test_approval_refreshes_card_evidence_without_overwriting_guidance(self):
        from app.services.model_cards import ModelCardService

        source = self.root / "approval-card.onnx"
        source.write_bytes(b"uploaded-onnx")
        artifact = self.artifacts.create_from_file(
            self.project.id, source, source.name, "model", metadata={"source": "upload"},
        )
        version = self.service.register_onnx_version(
            self.db, model_id=self.model.id, source_artifact_id=artifact.id,
            actor_id=self.owner.id,
            feature_schema=[{"name": "current", "dtype": "float64"}],
            output_schema={"name": "fault", "dtype": "int64"},
        )
        card = ModelCardService().ensure_for_version(self.db, version)
        ModelCardService().update_guidance(self.db, card.id, "Use calibrated sensors only.")

        self.service.approve(self.db, version.id, self.owner.id, "validated")

        refreshed = self.db.query(ModelCard).filter_by(model_version_id=version.id).one()
        self.assertEqual(refreshed.operational_guidance, "Use calibrated sensors only.")
        self.assertEqual(refreshed.approval_status, "approved")
        self.assertEqual(refreshed.approval_history[-1]["comment"], "validated")

    def test_approval_state_machine_is_idempotent_and_terminal(self):
        library, _artifact = self._platform_source()
        version = self.service.register_platform_version(
            self.db, model_id=self.model.id,
            source_model_library_id=library.id, actor_id=self.owner.id,
        )
        approved = self.service.approve(self.db, version.id, self.owner.id, "ready")
        again = self.service.approve(self.db, version.id, self.owner.id, "ignored")
        self.assertEqual(approved.approval_status, "approved")
        self.assertEqual(again.approval_comment, "ready")
        with self.assertRaises(ModelRegistryError) as raised:
            self.service.reject(self.db, version.id, self.owner.id, "bad")
        self.assertEqual(raised.exception.code, "MODEL_VERSION_STATE_CONFLICT")

    def test_rejection_requires_comment_and_archive_is_terminal(self):
        library, _artifact = self._platform_source()
        version = self.service.register_platform_version(
            self.db, model_id=self.model.id,
            source_model_library_id=library.id, actor_id=self.owner.id,
        )
        with self.assertRaises(ModelRegistryError) as raised:
            self.service.reject(self.db, version.id, self.owner.id, " ")
        self.assertEqual(raised.exception.code, "MODEL_REJECTION_COMMENT_REQUIRED")
        archived = self.service.archive(self.db, version.id, self.owner.id, "old")
        self.assertEqual(archived.approval_status, "archived")
        with self.assertRaises(ModelRegistryError):
            self.service.approve(self.db, version.id, self.owner.id)


if __name__ == "__main__":
    unittest.main()
