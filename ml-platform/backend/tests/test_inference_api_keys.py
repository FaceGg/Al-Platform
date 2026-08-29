import unittest
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

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
from app.services.inference_api_keys import (
    ApiKeyView,
    InferenceApiKeyError,
    InferenceApiKeyService,
)


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
        persisted = self.db.query(InferenceApiKey).filter_by(
            id=created.record.id,
        ).one()
        self.assertTrue(created.plaintext)
        self.assertNotEqual(persisted.secret_hash, created.plaintext)
        self.assertTrue(created.plaintext.startswith(persisted.prefix))
        self.assertNotIn(created.plaintext, repr(persisted.__dict__))
        listed = self.service.list_for_deployment(self.db, self.deployment.id)
        self.assertEqual(len(listed), 1)
        self.assertIsInstance(listed[0], ApiKeyView)
        safe_fields = {
            "id", "prefix", "scopes", "expires_at", "last_used_at",
            "revoked_at", "created_at",
        }
        serialized = asdict(listed[0])
        self.assertEqual(set(serialized), safe_fields)
        self.assertNotIn("secret_hash", serialized)
        self.assertNotIn("plaintext", serialized)

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
        with self.assertRaises(InferenceApiKeyError) as raised:
            self.service.verify(
                self.db,
                created.plaintext,
                deployment_id=uuid.uuid4(),
                scope="inference.predict",
            )
        self.assertEqual(raised.exception.code, "INFERENCE_API_KEY_INVALID")

        with self.assertRaises(InferenceApiKeyError) as raised:
            self.service.verify(
                self.db,
                created.plaintext + "wrong",
                deployment_id=self.deployment.id,
                scope="inference.predict",
            )
        self.assertEqual(raised.exception.code, "INFERENCE_API_KEY_INVALID")

        with self.assertRaises(InferenceApiKeyError) as raised:
            self.service.verify(
                self.db,
                created.plaintext,
                deployment_id=self.deployment.id,
                scope="inference.admin",
            )
        self.assertEqual(raised.exception.code, "INFERENCE_API_KEY_OUT_OF_SCOPE")

    def test_successful_verification_updates_only_last_used_at(self):
        created = self.service.create(
            self.db,
            self.deployment.id,
            self.actor.id,
            ["inference.predict"],
            None,
        )
        self.db.commit()

        verified = self.service.verify(self.db, created.plaintext)

        self.assertIsNotNone(verified.last_used_at)
        self.assertEqual(verified.secret_hash, created.record.secret_hash)

    def test_repeated_verification_reuses_secret_check_but_reloads_authorization_state(self):
        created = self.service.create(
            self.db,
            self.deployment.id,
            self.actor.id,
            ["inference.predict"],
            None,
        )
        self.db.commit()

        first_service = InferenceApiKeyService()
        second_service = InferenceApiKeyService()
        with patch.object(first_service._context, "verify", wraps=first_service._context.verify) as verify:
            first_service.verify(
                self.db,
                created.plaintext,
                deployment_id=self.deployment.id,
                scope="inference.predict",
                touch_last_used=False,
            )
            second_service.verify(
                self.db,
                created.plaintext,
                deployment_id=self.deployment.id,
                scope="inference.predict",
                touch_last_used=False,
            )

        self.assertEqual(verify.call_count, 1)
        self.service.revoke(self.db, created.record.id, self.actor.id)
        self.db.commit()
        with self.assertRaises(InferenceApiKeyError) as raised:
            self.service.verify(
                self.db,
                created.plaintext,
                deployment_id=self.deployment.id,
                scope="inference.predict",
                touch_last_used=False,
            )
        self.assertEqual(raised.exception.code, "INFERENCE_API_KEY_REVOKED")

    def test_unknown_scope_expiry_and_explicit_revocation_have_distinct_codes(self):
        with self.assertRaises(InferenceApiKeyError) as raised:
            self.service.create(
                self.db,
                self.deployment.id,
                self.actor.id,
                ["inference.unknown"],
                None,
            )
        self.assertEqual(raised.exception.code, "INFERENCE_API_KEY_SCOPE_INVALID")
        self.db.rollback()

        expired = self.service.create(
            self.db,
            self.deployment.id,
            self.actor.id,
            ["inference.predict"],
            datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        self.db.commit()
        with self.assertRaises(InferenceApiKeyError) as raised:
            self.service.verify(self.db, expired.plaintext)
        self.assertEqual(raised.exception.code, "INFERENCE_API_KEY_EXPIRED")

        revoked = self.service.create(
            self.db,
            self.deployment.id,
            self.actor.id,
            ["inference.predict"],
            None,
        )
        revoked_record = self.service.revoke(
            self.db,
            revoked.record.id,
            self.actor.id,
        )
        self.db.commit()
        self.assertIsNotNone(revoked_record.revoked_at)
        with self.assertRaises(InferenceApiKeyError) as raised:
            self.service.verify(self.db, revoked.plaintext)
        self.assertEqual(raised.exception.code, "INFERENCE_API_KEY_REVOKED")
        repeated = self.service.revoke(
            self.db,
            revoked.record.id,
            self.actor.id,
        )
        self.assertEqual(repeated.id, revoked_record.id)
        self.assertEqual(repeated.revoked_at, revoked_record.revoked_at)

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
        with self.assertRaises(InferenceApiKeyError) as raised:
            self.service.verify(self.db, created.plaintext)
        self.assertEqual(raised.exception.code, "INFERENCE_API_KEY_REVOKED")


if __name__ == "__main__":
    unittest.main()
