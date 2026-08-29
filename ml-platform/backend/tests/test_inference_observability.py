import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentTarget,
    InferenceApiKey,
    InferenceDeployment,
    InferenceMetricBucket,
    InferenceRequestLog,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.user import User
from app.services.inference_observability import (
    InferenceObservability,
    InferenceObservabilityError,
    safe_request_log,
)


class TestInferenceObservability(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        actor = User(username="observability-owner", password_hash="hash")
        self.db.add(actor)
        self.db.flush()
        project = Project(name="Observability", owner_id=actor.id)
        self.db.add(project)
        self.db.flush()
        artifact = Artifact(
            project_id=project.id,
            name="model.onnx",
            type="model",
            storage_path="",
            storage_uri="s3://models/observability.onnx",
            format="onnx",
        )
        self.db.add(artifact)
        self.db.flush()
        registered = RegisteredModel(
            project_id=project.id,
            name="Observed model",
            created_by_id=actor.id,
        )
        self.db.add(registered)
        self.db.flush()
        self.version = ModelVersion(
            registered_model_id=registered.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=artifact.id,
            onnx_artifact_id=artifact.id,
            approval_status="approved",
            created_by_id=actor.id,
        )
        self.db.add(self.version)
        self.db.flush()
        self.deployment = InferenceDeployment(
            project_id=project.id,
            name="primary",
            model_version_id=self.version.id,
            created_by_id=actor.id,
        )
        self.db.add(self.deployment)
        self.db.flush()
        self.revision = DeploymentRevision(
            deployment_id=self.deployment.id,
            revision_number=1,
            strategy="immediate",
            status="stable",
            created_by_id=actor.id,
        )
        self.db.add(self.revision)
        self.db.flush()
        self.db.add(DeploymentTarget(
            revision_id=self.revision.id,
            model_version_id=self.version.id,
            weight_bps=10000,
            role="stable",
        ))
        self.api_key = InferenceApiKey(
            deployment_id=self.deployment.id,
            prefix="wpk_test_001",
            secret_hash="not-plaintext",
            scopes=["inference.predict"],
            created_by_id=actor.id,
        )
        self.db.add(self.api_key)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_record_request_persists_only_bounded_metadata(self):
        request_id = str(uuid.uuid4())
        occurred_at = datetime(2026, 7, 20, 12, 34, tzinfo=timezone.utc)
        log = InferenceObservability().record_request(
            self.db,
            request_id,
            self.deployment.id,
            self.revision.id,
            self.version.id,
            self.api_key.id,
            2,
            13,
            "success",
            occurred_at=occurred_at,
        )
        self.db.commit()
        persisted = self.db.query(InferenceRequestLog).filter_by(id=log.id).one()
        self.assertEqual(persisted.request_id, request_id)
        self.assertEqual(persisted.batch_size, 2)
        self.assertEqual(persisted.duration_ms, 13)
        self.assertFalse(any(
            name in persisted.__dict__
            for name in ("records", "input", "predictions", "secret", "payload")
        ))

    def test_record_request_can_persist_log_without_synchronous_bucket_aggregation(self):
        log = InferenceObservability().record_request(
            self.db,
            "request-log-only",
            self.deployment.id,
            self.revision.id,
            self.version.id,
            self.api_key.id,
            1,
            7,
            "success",
            aggregate=False,
        )
        self.db.commit()
        self.assertIsNotNone(self.db.get(InferenceRequestLog, log.id))
        self.assertEqual(self.db.query(InferenceMetricBucket).count(), 0)

    def test_safe_request_log_never_exposes_payload_or_key_secret(self):
        log = InferenceObservability().record_request(
            self.db,
            "request-safe-view",
            self.deployment.id,
            self.revision.id,
            self.version.id,
            self.api_key.id,
            1,
            7,
            "error",
            error_code="INFERENCE_RUNTIME_UNAVAILABLE",
        )
        view = safe_request_log(log)
        self.assertEqual(set(view), {
            "id",
            "request_id",
            "deployment_id",
            "revision_id",
            "model_version_id",
            "api_key_id",
            "batch_size",
            "duration_ms",
            "status",
            "error_code",
            "occurred_at",
            "expires_at",
        })
        self.assertEqual(view["error_code"], "INFERENCE_RUNTIME_UNAVAILABLE")
        for forbidden in (
            "storage_uri", "raw_exception", "request_body", "predictions", "secret",
        ):
            self.assertNotIn(forbidden, view)

    def test_record_request_upserts_exact_minute_bucket_counts(self):
        service = InferenceObservability()
        minute = datetime(2026, 7, 20, 12, 34, tzinfo=timezone.utc)
        for index, status in enumerate(("success", "error", "limited")):
            service.record_request(
                self.db,
                f"request-{status}",
                self.deployment.id,
                self.revision.id,
                self.version.id,
                self.api_key.id,
                index + 1,
                (index + 1) * 10,
                status,
                error_code=None if status == "success" else f"INFERENCE_{status.upper()}",
                occurred_at=minute + timedelta(seconds=index),
            )
        self.db.commit()
        buckets = service.query_metrics(
            self.db,
            self.deployment.id,
            minute,
            minute + timedelta(minutes=1),
        )
        self.assertEqual(len(buckets), 1)
        bucket = buckets[0]
        self.assertEqual(bucket.request_count, 3)
        self.assertEqual(bucket.success_count, 1)
        self.assertEqual(bucket.error_count, 1)
        self.assertEqual(bucket.limited_count, 1)

        summary = service.summarize_metrics(buckets)
        self.assertEqual(summary["traffic_weights"], {str(self.version.id): 10000})
        self.assertEqual(summary["p95_latency_ms"], 50)

    def test_prune_removes_logs_expiring_at_the_boundary_only(self):
        service = InferenceObservability()
        boundary = datetime(2026, 7, 20, 12, 34, tzinfo=timezone.utc)
        expired = service.record_request(
            self.db,
            "request-expired",
            self.deployment.id,
            self.revision.id,
            self.version.id,
            self.api_key.id,
            1,
            10,
            "success",
            occurred_at=boundary - timedelta(days=31),
        )
        retained = service.record_request(
            self.db,
            "request-retained",
            self.deployment.id,
            self.revision.id,
            self.version.id,
            self.api_key.id,
            1,
            10,
            "success",
            occurred_at=boundary - timedelta(days=30),
        )
        expired.expires_at = boundary
        retained.expires_at = boundary + timedelta(microseconds=1)
        self.db.commit()
        self.assertEqual(service.prune(self.db, boundary), 1)
        self.db.commit()
        self.assertIsNone(self.db.get(InferenceRequestLog, expired.id))
        self.assertIsNotNone(self.db.get(InferenceRequestLog, retained.id))

    def test_log_query_rejects_over_31_days_and_page_sizes_over_200(self):
        service = InferenceObservability()
        since = datetime(2026, 6, 1, tzinfo=timezone.utc)
        with self.assertRaises(InferenceObservabilityError):
            service.query_logs(
                self.db,
                self.deployment.id,
                since,
                since + timedelta(days=31, microseconds=1),
            )
        with self.assertRaises(InferenceObservabilityError):
            service.query_logs(
                self.db,
                self.deployment.id,
                since,
                since + timedelta(days=1),
                page=1,
                page_size=201,
            )

    def test_bucket_creation_recovers_from_concurrent_first_insert(self):
        minute = datetime(2026, 7, 20, 12, 34)
        existing = InferenceMetricBucket(
            deployment_id=self.deployment.id,
            bucket_start=minute,
            latency_buckets={},
            traffic_weights={},
        )
        self.db.add(existing)
        self.db.commit()

        class RacingQuery:
            def __init__(self, query):
                self.query = query
                self.first_call = True

            def filter(self, *criteria):
                self.query = self.query.filter(*criteria)
                return self

            def with_for_update(self):
                self.query = self.query.with_for_update()
                return self

            def first(self):
                if self.first_call:
                    self.first_call = False
                    return None
                return self.query.first()

        class RacingSession:
            def __init__(self, db):
                self.db = db
                self.racing_query = None

            def query(self, model):
                query = self.db.query(model)
                if model is InferenceMetricBucket:
                    if self.racing_query is None:
                        self.racing_query = RacingQuery(query)
                    return self.racing_query
                return query

            def __getattr__(self, name):
                return getattr(self.db, name)

        bucket = InferenceObservability()._bucket(
            RacingSession(self.db), self.deployment.id, minute,
        )
        self.assertEqual(bucket.id, existing.id)
        self.assertEqual(
            self.db.query(InferenceMetricBucket).filter_by(
                deployment_id=self.deployment.id, bucket_start=minute,
            ).count(),
            1,
        )

    def test_postgres_bucket_creation_uses_atomic_conflict_safe_insert(self):
        minute = datetime(2026, 7, 20, 12, 34)
        existing = InferenceMetricBucket(
            id=uuid.uuid4(),
            deployment_id=self.deployment.id,
            bucket_start=minute,
            latency_buckets={},
            traffic_weights={},
        )

        class Query:
            def __init__(self):
                self.calls = 0

            def filter(self, *_criteria):
                return self

            def with_for_update(self):
                return self

            def first(self):
                self.calls += 1
                return None if self.calls == 1 else existing

        class PostgresSession:
            bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

            def __init__(self):
                self.query_value = Query()
                self.executed = []

            def query(self, _model):
                return self.query_value

            def get_bind(self):
                return self.bind

            def execute(self, statement):
                self.executed.append(statement)

        db = PostgresSession()
        bucket = InferenceObservability()._bucket(db, self.deployment.id, minute)

        self.assertIs(bucket, existing)
        self.assertEqual(len(db.executed), 1)
        sql = str(db.executed[0].compile(dialect=postgresql_dialect()))
        self.assertIn("ON CONFLICT (deployment_id, bucket_start) DO NOTHING", sql)


if __name__ == "__main__":
    unittest.main()
