import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_registry import ModelCard, ModelVersion, RegisteredModel
from app.models.project import Project
from app.models.user import User
from app.services.model_cards import ModelCardError, ModelCardService


class TestModelCards(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.actor = User(username="model-card-owner", password_hash="hash")
        self.db.add(self.actor)
        self.db.flush()
        project = Project(name="Model cards", owner_id=self.actor.id)
        self.db.add(project)
        self.db.flush()
        artifact = Artifact(
            project_id=project.id,
            name="model.onnx",
            type="model",
            storage_path="",
            storage_uri="s3://models/card.onnx",
            format="onnx",
            metadata_={"sha256": "b" * 64, "dataset_artifact_id": "dataset-1"},
        )
        self.db.add(artifact)
        self.db.flush()
        registered = RegisteredModel(
            project_id=project.id,
            name="Card model",
            created_by_id=self.actor.id,
        )
        self.db.add(registered)
        self.db.flush()
        self.version = ModelVersion(
            registered_model_id=registered.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=artifact.id,
            onnx_artifact_id=artifact.id,
            feature_schema=[{"name": "current", "dtype": "float64"}],
            output_schema={"name": "fault", "dtype": "int64"},
            metrics={"accuracy": 0.95},
            conversion_metadata={"sha256": "b" * 64},
            approval_status="approved",
            approval_comment="validated",
            approved_by_id=self.actor.id,
            created_by_id=self.actor.id,
        )
        self.db.add(self.version)
        self.db.commit()
        self.service = ModelCardService()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_ensure_for_version_freezes_system_generated_evidence(self):
        card = self.service.ensure_for_version(self.db, self.version)
        self.db.commit()
        persisted = self.db.query(ModelCard).filter_by(model_version_id=self.version.id).one()
        self.assertEqual(persisted.id, card.id)
        self.assertEqual(persisted.input_schema, self.version.feature_schema)
        self.assertEqual(persisted.output_schema, self.version.output_schema)
        self.assertEqual(persisted.metrics, self.version.metrics)
        self.assertTrue(persisted.approval_history)
        self.assertEqual(
            persisted.training_data_lineage["dataset_artifact_id"],
            "dataset-1",
        )
        self.assertEqual(
            persisted.source_artifact_ids,
            [str(self.version.source_artifact_id)],
        )
        self.assertEqual(persisted.release_status, "unreleased")

    def test_human_guidance_can_change_without_mutating_system_fields(self):
        card = self.service.ensure_for_version(self.db, self.version)
        original_metrics = dict(card.metrics)
        original_input_schema = list(card.input_schema)
        original_output_schema = dict(card.output_schema)
        updated = self.service.update_guidance(
            self.db,
            card.id,
            "Use for spot-weld fault screening with calibrated sensors.",
        )
        self.assertEqual(
            updated.operational_guidance,
            "Use for spot-weld fault screening with calibrated sensors.",
        )
        self.assertEqual(updated.guidance_revision, 2)
        self.assertEqual(updated.metrics, original_metrics)
        self.assertEqual(updated.input_schema, original_input_schema)
        self.assertEqual(updated.output_schema, original_output_schema)

    def test_export_contains_lineage_and_guidance_but_omits_sensitive_runtime_data(self):
        card = self.service.ensure_for_version(self.db, self.version)
        self.service.update_guidance(
            self.db,
            card.id,
            "Use for spot-weld fault screening with calibrated sensors.",
        )
        exported = self.service.export(self.db, card.id)
        self.assertEqual(
            exported["source_artifact_ids"],
            [str(self.version.source_artifact_id)],
        )
        self.assertEqual(
            exported["training_data_lineage"]["dataset_artifact_id"],
            "dataset-1",
        )
        self.assertEqual(exported["release_status"], "unreleased")
        self.assertEqual(
            exported["operational_guidance"],
            "Use for spot-weld fault screening with calibrated sensors.",
        )
        self.assertEqual(exported["guidance_revision"], 2)
        serialized = json.dumps(exported, default=str)
        for forbidden in (
            "storage_uri", "raw_exception", "credentials", "records", "predictions",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_public_update_rejects_system_generated_fields(self):
        card = self.service.ensure_for_version(self.db, self.version)
        with self.assertRaises(ModelCardError) as raised:
            self.service.update(self.db, card.id, {"metrics": {"accuracy": 1.0}})
        self.assertEqual(raised.exception.code, "MODEL_CARD_SYSTEM_FIELD_IMMUTABLE")


if __name__ == "__main__":
    unittest.main()
