import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_registry import (
    InferenceApiKey,
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.user import User
from app.services.inference_api_keys import InferenceApiKeyError, InferenceApiKeyService


class TestInferenceApiKeys(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.actor = User(username="api-key-owner", password_hash="hash")
        self.db.add(self.actor)
        self.db.flush()
        project = Project(name="API keys", owner_id=self.actor.id)
        self.db.add(project)
        self.db.flush()
        artifact = Artifact(
            project_id=project.id,
            name="model.onnx",
            type="model",
            storage_path="",
            storage_uri="s3://models/key.onnx",
            format="onnx",
        )
        self.db.add(artifact)
        self.db.flush()
        registered = RegisteredModel(
            project_id=project.id,
            name="Key model",
            created_by_id=self.actor.id,
        )
        self.db.add(registered)
        self.db.flush()
        version = ModelVersion(
            registered_model_id=registered.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=artifact.id,
            onnx_artifact_id=artifact.id,
            approval_status="approved",
            created_by_id=self.actor.id,
        )
        self.db.add(version)
        self.db.flush()
        self.deployment = InferenceDeployment(
            project_id=project.id,
            name="primary",
            model_version_id=version.id,
            created_by_id=self.actor.id,
        )
        self.db.add(self.deployment)
        self.db.commit()
        self.service = InferenceApiKeyService()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_create_returns_plaintext_once_and_persists_only_hash(self):
        created = self.service.create(
            self.db,
            self.deployment.id,
            self.actor.id,
            ["inference.predict"],
            None,
        )
        self.db.commit()
        persisted = self.db.query(InferenceApiKey).filter_by(id=created.record.id).one()
        self.assertTrue(created.plaintext)
        self.assertNotEqual(persisted.secret_hash, created.plaintext)
        self.assertTrue(created.plaintext.startswith(persisted.prefix))
        self.assertNotIn(created.plaintext, repr(persisted.__dict__))

    def test_verify_is_deployment_and_scope_bound(self):
        created = self.service.create(
            self.db,
            self.deployment.id,
            self.actor.id,
            ["inference.predict"],
            None,
        )
        self.db.commit()
        verified = self.service.verify(
            self.db,
            created.plaintext,
            deployment_id=self.deployment.id,
            scope="inference.predict",
        )
        self.assertEqual(verified.id, created.record.id)
        with self.assertRaisesRegex(InferenceApiKeyError, "API_KEY_INVALID"):
            self.service.verify(
                self.db,
                created.plaintext,
                deployment_id=uuid.uuid4(),
                scope="inference.predict",
            )

    def test_rotation_invalidates_the_previous_plaintext(self):
        created = self.service.create(
            self.db,
            self.deployment.id,
            self.actor.id,
            ["inference.predict"],
            None,
        )
        self.db.commit()
        rotated = self.service.rotate(self.db, created.record.id, self.actor.id)
        self.db.commit()
        self.assertNotEqual(rotated.plaintext, created.plaintext)
        with self.assertRaisesRegex(InferenceApiKeyError, "API_KEY_INVALID"):
            self.service.verify(self.db, created.plaintext)


if __name__ == "__main__":
    unittest.main()
