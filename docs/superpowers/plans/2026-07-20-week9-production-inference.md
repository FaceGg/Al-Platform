# Week 9 Production Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Week 8 model registry into a production inference service with immutable weighted revisions, durable rollout and rollback, deployment API keys, fail-closed Redis limits, redacted telemetry, model cards, and safe domain events.

**Architecture:** Keep `InferenceDeployment` as the stable project-scoped service identity and retain the JWT prediction route for console testing. The control plane chooses a target from an immutable revision with a deterministic weighted hash and calls the private ONNX runtime through an internal runtime key. Week 9 defines a safe `DomainEvent` recorder contract with a no-op implementation; Week 10 will implement the transactional outbox and notification delivery.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, PostgreSQL, SQLite local mode, Redis, Celery, ONNX Runtime, React 18, TypeScript, Ant Design, Vitest, Playwright, Docker Compose, GitHub Actions.

**Granularity:** Each checkbox is one 2–5 minute action, except a test/build command that may run longer without requiring additional implementation decisions.

---

## File Map

### Backend control plane

- Modify `ml-platform/backend/app/models/model_registry.py`: add revision, target, rollout, API-key, request-log, metric-bucket, and model-card ORM entities.
- Modify `ml-platform/backend/app/models/__init__.py`: export all Week 9 entities.
- Modify `ml-platform/backend/app/schemas/model_registry.py`: add strict rollout, key, log, metric, and model-card DTOs.
- Create `ml-platform/backend/app/events/domain.py`: frozen safe event contract and null recorder.
- Create `ml-platform/backend/app/services/inference_api_keys.py`: key lifecycle and verification.
- Create `ml-platform/backend/app/services/inference_rate_limit.py`: atomic Redis token bucket.
- Create `ml-platform/backend/app/services/inference_observability.py`: redacted logs, minute buckets, retention, and bounded queries.
- Create `ml-platform/backend/app/services/model_cards.py`: generated card data and versioned human guidance.
- Create `ml-platform/backend/app/services/inference_rollout.py`: revision creation, CAS rollout, routing, rollback, reconciliation, and event recording.
- Modify `ml-platform/backend/app/services/inference_deployment.py`: revision-aware runtime specifications and restart reconciliation.
- Modify `ml-platform/backend/app/services/inference_runtime_client.py`: address private sessions by runtime key.
- Modify `ml-platform/backend/app/inference_runtime/runtime.py`: load multiple revision targets for one stable deployment.
- Modify `ml-platform/backend/app/inference_runtime/app.py`: retain private authenticated routes while accepting runtime keys.
- Modify `ml-platform/backend/app/api/model_registry.py`: expose control-plane Week 9 routes without changing Week 8 response shapes.
- Create `ml-platform/backend/app/api/inference_production.py`: API-key production prediction route.
- Modify `ml-platform/backend/app/tasks/inference_tasks.py`: idempotent rollout and reconciliation tasks.
- Modify `ml-platform/backend/app/tasks/celery_app.py`: stable task discovery and Beat schedule.
- Modify `ml-platform/backend/app/config.py`: bounded rollout, rate-limit, observation, and retention settings.
- Modify `ml-platform/backend/app/main.py`: register models, router, and null recorder.
- Create `ml-platform/backend/alembic/versions/20260720_09_production_inference.py`: linear migration from `20260718_08`.

### Backend tests

- Create `ml-platform/backend/tests/test_inference_production_models.py`.
- Create `ml-platform/backend/tests/test_inference_rollout.py`.
- Create `ml-platform/backend/tests/test_inference_api_keys.py`.
- Create `ml-platform/backend/tests/test_inference_rate_limit.py`.
- Create `ml-platform/backend/tests/test_inference_observability.py`.
- Create `ml-platform/backend/tests/test_model_cards.py`.
- Create `ml-platform/backend/tests/test_api_inference_production.py`.
- Modify `ml-platform/backend/tests/test_inference_runtime.py`.
- Modify `ml-platform/backend/tests/test_inference_deployment.py`.
- Modify `ml-platform/backend/tests/test_api_model_registry.py`.
- Modify `ml-platform/backend/tests/test_database_production.py`.
- Modify `ml-platform/backend/tests/test_celery_workflows.py`.
- Modify `ml-platform/backend/tests/week_manifest.py` and `ml-platform/backend/tests/test_suite_manifest.py`.

### Frontend and delivery

- Modify `ml-platform/frontend/src/api/modelRegistry.ts` and `modelRegistry.test.ts`.
- Modify `ml-platform/frontend/src/pages/ModelLibraryPage.tsx` and `ModelLibraryPage.test.tsx`.
- Modify `ml-platform/frontend/src/i18n/index.tsx`.
- Modify `ml-platform/frontend/e2e/model-inference.spec.ts`.
- Modify `ml-platform/backend/tests/test_inference_production_stack.py`.
- Modify `ml-platform/docker-compose.yml` and `ml-platform/.github/workflows/ci.yml`.
- Modify `docs/operations/inference.md` and create `docs/week9-production-inference-acceptance.md` during implementation.
- Update `DEVELOPMENT_PLAN.md`, `PLATFORM_STATUS.md`, and shared experience only during final integration after verification.

---

### Task 1: Freeze the Week 9 failing test boundary

**Files:**
- Create: `ml-platform/backend/tests/test_inference_production_models.py`
- Create: `ml-platform/backend/tests/test_inference_rollout.py`
- Create: `ml-platform/backend/tests/test_inference_api_keys.py`
- Create: `ml-platform/backend/tests/test_inference_rate_limit.py`
- Create: `ml-platform/backend/tests/test_inference_observability.py`
- Create: `ml-platform/backend/tests/test_model_cards.py`
- Create: `ml-platform/backend/tests/test_api_inference_production.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: Write the first failing model and event tests**

```python
def test_target_weights_must_total_10000(self):
    db = self.db
    revision = make_revision(db)
    db.add(make_target(revision, weight_bps=9999))
    db.commit()
    with self.assertRaisesRegex(InferenceRolloutError, "TARGET_WEIGHTS_INVALID"):
        InferenceRolloutService(FakeRuntime()).validate_targets(db, revision.id)

def test_rollout_event_contains_only_safe_payload(self):
    db = self.db
    recorder = RecordingEventRecorder()
    service = InferenceRolloutService(FakeRuntime(), event_recorder=recorder)
    service.record_rollout_completed(db, deployment_id, revision_id, actor_id)
    event = recorder.events[-1]
    self.assertEqual(event.event_type, "rollout.completed")
    self.assertEqual(set(event.payload), {"revision_id", "deployment_id", "model_version_ids"})
```

Use real SQLAlchemy sessions and a fake recorder. Do not mock constraints.

- [x] **Step 2: Run the seven modules and verify RED**

```powershell
cd ml-platform/backend
python -m unittest tests.test_inference_production_models tests.test_inference_rollout tests.test_inference_api_keys tests.test_inference_rate_limit tests.test_inference_observability tests.test_model_cards tests.test_api_inference_production -v
```

Expected: import failures name the missing Week 9 model and service modules.

- [x] **Step 3: Register the exact Week 9 modules**

Add this list to `WEEK_TEST_MODULES`:

```python
9: [
    "test_inference_production_models",
    "test_inference_rollout",
    "test_inference_api_keys",
    "test_inference_rate_limit",
    "test_inference_observability",
    "test_model_cards",
    "test_api_inference_production",
],
```

Run `python -m unittest tests.test_suite_manifest -v`. Expected: every file is assigned once; failures are limited to the missing production implementation.

- [x] **Step 4: Commit the RED contract tests**

```powershell
git add ml-platform/backend/tests
git commit -m "test: freeze week 9 inference contracts"
```

### Task 2: Add persistence models and the linear migration

**Files:**
- Modify: `ml-platform/backend/app/models/model_registry.py`
- Modify: `ml-platform/backend/app/models/__init__.py`
- Create: `ml-platform/backend/alembic/versions/20260720_09_production_inference.py`
- Modify: `ml-platform/backend/tests/test_inference_production_models.py`
- Modify: `ml-platform/backend/tests/test_database_production.py`

- [x] **Step 1: Add revision strategy/state constants (2–5 min)**

Add `REVISION_STRATEGIES`, `REVISION_STATES`, and `ROLLOUT_STATES`; import no model yet.

- [x] **Step 2: Add `DeploymentRevision` (2–5 min)**

Add the revision class from the following block and export it from `app.models`.

- [x] **Step 3: Add `DeploymentTarget` (2–5 min)**

Add the target class from the following block and its `DeploymentRevision.targets` relationship.

Implement these exact entities and values:

```python
REVISION_STRATEGIES = ("immediate", "canary", "rolling")
REVISION_STATES = ("draft", "candidate", "stable", "superseded", "failed")
ROLLOUT_STATES = ("pending", "preloading", "progressing", "paused", "completed", "failed", "rolled_back")

class DeploymentRevision(Base):
    __tablename__ = "deployment_revisions"
    __table_args__ = (
        UniqueConstraint("deployment_id", "revision_number", name="uq_deployment_revisions_number"),
        CheckConstraint("strategy IN ('immediate','canary','rolling')", name="ck_deployment_revisions_strategy"),
        CheckConstraint("status IN ('draft','candidate','stable','superseded','failed')", name="ck_deployment_revisions_status"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deployment_id = Column(UUID(as_uuid=True), ForeignKey("inference_deployments.id", ondelete="CASCADE"), nullable=False)
    revision_number = Column(Integer, nullable=False)
    strategy = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="draft")
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    activated_at = Column(DateTime)

class DeploymentTarget(Base):
    __tablename__ = "deployment_targets"
    __table_args__ = (
        UniqueConstraint("revision_id", "model_version_id", name="uq_deployment_targets_revision_model"),
        CheckConstraint("weight_bps >= 0 AND weight_bps <= 10000", name="ck_deployment_targets_weight"),
        CheckConstraint("role IN ('stable','candidate')", name="ck_deployment_targets_role"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_id = Column(UUID(as_uuid=True), ForeignKey("deployment_revisions.id", ondelete="CASCADE"), nullable=False)
    model_version_id = Column(UUID(as_uuid=True), ForeignKey("model_versions.id", deferrable=True, initially="DEFERRED"), nullable=False)
    weight_bps = Column(Integer, nullable=False)
    role = Column(String(16), nullable=False)
```

- [x] **Step 4: Add `DeploymentRollout` (2–5 min)**

Add `DeploymentRollout` with the frozen states, `from_revision_id`, `to_revision_id`, `current_step`, `lock_version`, JSON `step_schedule`, JSON `thresholds`, `last_error_code`, and timestamps. Add a PostgreSQL partial unique index that permits only one `pending`, `preloading`, `progressing`, or `paused` rollout per deployment; service row locking enforces the same rule in SQLite tests.

- [x] **Step 5: Add `InferenceApiKey` (2–5 min)**

Add `InferenceApiKey` with `deployment_id`, 12-character `prefix`, PBKDF2 `secret_hash`, JSON scopes, expiry, revocation, last-used, actor, and timestamps.

- [x] **Step 6: Add `InferenceRequestLog` (2–5 min)**

Add request/deployment/revision/version/key IDs, batch size, integer duration, constrained status, stable error code, occurrence and expiry.

- [x] **Step 7: Add `InferenceMetricBucket` (2–5 min)**

Add unique deployment/minute, request/success/error/limited/load-failure counts, `batch_size_sum`, latency sum/max, fixed-boundary `latency_buckets` JSON, and `traffic_weights` JSON.

- [x] **Step 8: Add `ModelCard` and exports (2–5 min)**

Add one card per model version with generated lineage/schema/metrics/approval fields, risk text, operational guidance, and `guidance_revision`; export all seven classes from `app.models.__init__`.

- [x] **Step 9: Write migration tests before the revision (2–5 min)**

Set `HEAD_REVISION = "20260720_09_production_inference"`. Assert 45 business tables, all seven table names, named indexes, backfilled one stable revision and 10000-basis-point target for every Week 8 deployment, one model card per version, and complete downgrade to `20260718_08`.

Run:

```powershell
python -m unittest tests.test_inference_production_models tests.test_database_production -v
```

Expected: RED because the revision file and tables are absent.

- [x] **Step 10: Create the revision header and seven tables (2–5 min)**

The revision header must be:

```python
revision = "20260720_09_production_inference"
down_revision = "20260718_08"
branch_labels = None
depends_on = None
```

Create tables in dependency order with the exact ORM constraint/index names.

- [x] **Step 11: Add deterministic backfill (2–5 min)**

Backfill with SQLAlchemy `sa.table` plus `op.bulk_insert`/connection queries so UUID handling works on PostgreSQL and SQLite. Use each legacy deployment ID as its initial stable revision ID and each model-version ID as its initial model-card ID.

- [x] **Step 12: Add complete downgrade (2–5 min)**

Drop only Week 9 tables and indexes in reverse dependency order and leave all legacy rows untouched.

- [x] **Step 13: Run migration GREEN**

```powershell
python -m unittest tests.test_inference_production_models tests.test_database_production -v
python -m compileall -q app alembic
```

Expected: clean database upgrades twice, `alembic check` passes, current head is `20260720_09_production_inference`, backfills match, and downgrade returns to `20260718_08`.

- [x] **Step 14: Commit models and migration (2–5 min)**

```powershell
git add ml-platform/backend/app/models ml-platform/backend/alembic/versions/20260720_09_production_inference.py ml-platform/backend/tests/test_inference_production_models.py ml-platform/backend/tests/test_database_production.py
git commit -m "feat: add production inference persistence"
```

### Task 3: Freeze the safe domain-event seam

**Files:**
- Create: `ml-platform/backend/app/events/domain.py`
- Modify: `ml-platform/backend/app/main.py`
- Modify: `ml-platform/backend/tests/test_inference_rollout.py`

- [x] **Step 1: Write the exact protocol test**

```python
class RecordingEventRecorder:
    def __init__(self):
        self.events = []
    def record(self, db, event):
        self.events.append(event)

def test_null_recorder_does_not_commit(self):
    db = Mock()
    db.commit = Mock(side_effect=AssertionError("recorder must not commit"))
    NullDomainEventRecorder().record(db, safe_event())
    db.commit.assert_not_called()
```

Run `python -m unittest tests.test_inference_rollout -v`. Expected: RED because `app.events.domain` is absent.

- [x] **Step 2: Implement the frozen public contract**

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
import uuid
from sqlalchemy.orm import Session

@dataclass(frozen=True)
class DomainEvent:
    event_id: uuid.UUID
    idempotency_key: str
    event_type: str
    severity: str
    occurred_at: datetime
    project_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    resource_type: str
    resource_id: str | None
    payload: dict

class DomainEventRecorder(Protocol):
    def record(self, db: Session, event: DomainEvent) -> None:
        raise NotImplementedError

class NullDomainEventRecorder:
    def record(self, db: Session, event: DomainEvent) -> None:
        return None
```

Add this exact factory and constants:

```python
SAFE_EVENT_TYPES = frozenset({
    "rollout.started",
    "rollout.failed",
    "rollout.completed",
    "rollback.completed",
    "runtime.load_failed",
    "rate_limit.threshold_exceeded",
    "inference.error_rate.threshold_exceeded",
})
SAFE_PAYLOAD_KEYS = frozenset({
    "revision_id", "deployment_id", "model_version_ids", "error_code", "step",
})

def create_domain_event(
    *, idempotency_key, event_type, severity, occurred_at, project_id,
    actor_id, resource_type, resource_id, payload,
):
    if event_type not in SAFE_EVENT_TYPES:
        raise ValueError("DOMAIN_EVENT_TYPE_INVALID")
    safe_payload = {
        key: value for key, value in payload.items() if key in SAFE_PAYLOAD_KEYS
    }
    return DomainEvent(
        event_id=uuid.uuid4(),
        idempotency_key=idempotency_key,
        event_type=event_type,
        severity=severity,
        occurred_at=occurred_at,
        project_id=project_id,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=safe_payload,
    )
```

Inject `NullDomainEventRecorder` by default. The recorder never calls commit; the caller owns the transaction. Rollout idempotency keys use `rollout:{rollout_id}:{state}:{lock_version}` so a repeated Celery delivery records the same logical event in Week 10's future outbox.

- [x] **Step 3: Verify no notification implementation leaked into Week 9**

```powershell
python -m unittest tests.test_inference_rollout -v
rg -n "notification|outbox|smtp|wecom|webhook" app/events/domain.py alembic/versions/20260720_09_production_inference.py
```

Expected: event tests pass and the search returns no notification table, provider, or network sender.

- [x] **Step 4: Commit the event contract**

```powershell
git add ml-platform/backend/app/events ml-platform/backend/app/main.py ml-platform/backend/tests/test_inference_rollout.py
git commit -m "feat: define safe inference domain events"
```

### Task 4: Implement API-key lifecycle and fail-closed Redis limiting

**Files:**
- Create: `ml-platform/backend/app/services/inference_api_keys.py`
- Create: `ml-platform/backend/app/services/inference_rate_limit.py`
- Modify: `ml-platform/backend/app/config.py`
- Modify: `ml-platform/backend/tests/test_inference_api_keys.py`
- Modify: `ml-platform/backend/tests/test_inference_rate_limit.py`

- [x] **Step 1: Write failing key-lifecycle tests**

```python
def test_create_returns_plaintext_once_and_persists_only_hash(self):
    db = self.db
    result = InferenceApiKeyService().create(
        db, deployment_id, actor_id, ["inference.predict"], expires_at=None,
    )
    self.assertTrue(result.plaintext.startswith("mli_"))
    self.assertNotEqual(result.plaintext, result.record.secret_hash)
    self.assertEqual(
        InferenceApiKeyService().verify(db, result.plaintext).id,
        result.record.id,
    )

def test_rotation_revokes_old_key_in_same_transaction(self):
    db = self.db
    old = create_key(db)
    new = InferenceApiKeyService().rotate(db, old.record.id, actor_id)
    self.assertIsNotNone(old.record.revoked_at)
    self.assertNotEqual(old.plaintext, new.plaintext)
```

Cover unknown scope, expiry, revocation, wrong deployment, wrong secret, and list serialization without `secret_hash` or plaintext.

- [x] **Step 2: Write failing limiter tests and run RED**

```python
def test_redis_failure_never_becomes_allow(self):
    limiter = RedisTokenBucket(FailingRedis())
    with self.assertRaises(RateLimitBackendUnavailable):
        limiter.consume("deployment:d1:key:k1", capacity=20, refill_per_second=1)

def test_rejected_decision_has_retry_after(self):
    decision = RedisTokenBucket(ScriptedRedis(tokens=0)).consume(
        "deployment:d1:key:k1", capacity=20, refill_per_second=1,
    )
    self.assertFalse(decision.allowed)
    self.assertGreaterEqual(decision.retry_after_seconds, 1)
```

Run:

```powershell
python -m unittest tests.test_inference_api_keys tests.test_inference_rate_limit -v
```

Expected: RED because both service modules are absent.

- [x] **Step 3: Implement one-time keys with PBKDF2**

```python
class InferenceApiKeyService:
    _context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

    def create(self, db, deployment_id, actor_id, scopes, expires_at):
        normalized = tuple(sorted(set(scopes)))
        if not normalized or set(normalized) - {"inference.predict"}:
            raise InferenceApiKeyError("INFERENCE_API_KEY_SCOPE_INVALID")
        plaintext = "mli_" + secrets.token_urlsafe(32)
        record = InferenceApiKey(
            deployment_id=deployment_id,
            prefix=plaintext[:12],
            secret_hash=self._context.hash(plaintext),
            scopes=list(normalized),
            expires_at=expires_at,
            created_by_id=actor_id,
        )
        db.add(record)
        db.flush()
        return CreatedApiKey(record=record, plaintext=plaintext)
```

`verify` selects by the 12-character prefix, verifies PBKDF2 in constant-time library code, checks expiry/revocation/scope/deployment, updates only `last_used_at`, and raises stable `INFERENCE_API_KEY_INVALID`, `INFERENCE_API_KEY_EXPIRED`, `INFERENCE_API_KEY_REVOKED`, or `INFERENCE_API_KEY_OUT_OF_SCOPE` codes. `rotate` revokes then creates in the caller's transaction.

- [x] **Step 4: Implement one atomic Redis script**

Use one Lua `EVAL` to refill, consume, store token count/update time, and set TTL. `consume(key, capacity, refill_per_second)` returns `RateLimitDecision(allowed, remaining, retry_after_seconds)`. Redis connection, timeout, or script failures raise `RateLimitBackendUnavailable("RATE_LIMIT_BACKEND_UNAVAILABLE")`; production never falls back to memory.

Add these bounded settings:

```python
inference_rate_limit_capacity: int = Field(default=100, ge=1, le=100000)
inference_rate_limit_refill_per_second: float = Field(default=10.0, gt=0, le=10000)
inference_log_retention_days: int = Field(default=30, ge=1, le=365)
inference_rollout_observation_seconds: int = Field(default=60, ge=10, le=3600)
```

- [x] **Step 5: Run GREEN and scan for secret exposure**

```powershell
python -m unittest tests.test_inference_api_keys tests.test_inference_rate_limit tests.test_config -v
rg -n "plaintext|secret_hash|mli_|X-Inference-Api-Key" app/services app/models app/api
```

Expected: all lifecycle and limiter tests pass; plaintext appears only in the one-time result and response path, never in logs, audit changes, repr, summaries, or exports.

- [x] **Step 6: Commit key and limiter services**

```powershell
git add ml-platform/backend/app/services/inference_api_keys.py ml-platform/backend/app/services/inference_rate_limit.py ml-platform/backend/app/config.py ml-platform/backend/tests/test_inference_api_keys.py ml-platform/backend/tests/test_inference_rate_limit.py
git commit -m "feat: secure production inference access"
```

### Task 5: Add redacted logs, minute metrics, and model cards

**Files:**
- Create: `ml-platform/backend/app/services/inference_observability.py`
- Create: `ml-platform/backend/app/services/model_cards.py`
- Modify: `ml-platform/backend/app/services/model_registry.py`
- Modify: `ml-platform/backend/tests/test_inference_observability.py`
- Modify: `ml-platform/backend/tests/test_model_cards.py`

- [x] **Step 1: Write the redaction and aggregation tests**

```python
def test_request_log_has_no_payload_fields(self):
    db = self.db
    log = InferenceObservability().record_request(
        db, request_id=request_id, deployment_id=deployment_id,
        revision_id=revision_id, model_version_id=version_id,
        api_key_id=key_id, batch_size=2, duration_ms=17,
        status="success", error_code=None,
    )
    safe = safe_request_log(log)
    self.assertNotIn("records", safe)
    self.assertNotIn("predictions", safe)
    self.assertNotIn("storage_uri", safe)
    self.assertNotIn("secret", safe)

def test_two_requests_increment_one_minute_bucket(self):
    db = self.db
    observed = datetime(2026, 7, 20, 12, 34, 42)
    service = InferenceObservability(clock=lambda: observed)
    service.record_request(db, **successful_request())
    service.record_request(db, **failed_request("INFERENCE_FAILED"))
    bucket = db.query(InferenceMetricBucket).one()
    self.assertEqual(bucket.bucket_start, datetime(2026, 7, 20, 12, 34))
    self.assertEqual((bucket.request_count, bucket.success_count, bucket.error_count), (2, 1, 1))
```

Run `python -m unittest tests.test_inference_observability -v`. Expected: RED because the service is absent.

- [x] **Step 2: Implement log writing and bounded metric queries**

Round occurrence time to the minute. Insert the allowlisted request log and upsert its bucket in the caller's transaction. Store duration as a non-negative integer, status from `success/error/limited`, stable code only, and retention expiry. Accumulate batch size, the active revision weights, and fixed latency histogram boundaries `[5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000]`; calculate p50/p95/p99 from those bucket counts without scanning raw logs. Expose average/max/histogram percentiles, counts, average batch size, traffic weights, and load failures. Reject query windows over 31 days and page sizes over 200. A retention task deletes expired logs and old buckets, never cards.

- [x] **Step 3: Write the generated-card tests**

```python
def test_card_system_fields_are_generated_and_guidance_versions(self):
    db = self.db
    card = ModelCardService().ensure_for_version(db, approved_version)
    original_input = card.input_schema
    updated = ModelCardService().update_guidance(
        db, card.id, "Use only on validated resistance-welding lines",
    )
    self.assertEqual(updated.guidance_revision, 2)
    self.assertEqual(updated.input_schema, original_input)

def test_card_update_rejects_system_fields(self):
    db = self.db
    with self.assertRaisesRegex(ModelCardError, "MODEL_CARD_SYSTEM_FIELD_IMMUTABLE"):
        ModelCardService().update(db, card.id, {"metrics": {"accuracy": 1.0}})
```

Run `python -m unittest tests.test_model_cards -v`. Expected: RED because `ModelCardService` is absent.

- [x] **Step 4: Implement card generation and export**

`ensure_for_version` copies immutable feature/output schema, frozen metrics, source artifact and training lineage by stable IDs, approval status/actor/time/comment, and current release references. `update_guidance` changes only `operational_guidance` and increments `guidance_revision`. JSON export omits storage URIs, credentials, request records, predictions, and raw exceptions. Call `ensure_for_version` after version registration and after approval-history changes without overwriting human guidance.

- [x] **Step 5: Run GREEN and commit**

```powershell
python -m unittest tests.test_inference_observability tests.test_model_cards tests.test_model_registry_service -v
git add ml-platform/backend/app/services ml-platform/backend/tests/test_inference_observability.py ml-platform/backend/tests/test_model_cards.py
git commit -m "feat: add inference telemetry and model cards"
```

Expected: aggregation, retention, redaction, immutable fields, guidance versioning, and registry integration pass.

### Task 6: Implement weighted routing and durable rollout CAS

**Files:**
- Create: `ml-platform/backend/app/services/inference_rollout.py`
- Modify: `ml-platform/backend/app/services/inference_deployment.py`
- Modify: `ml-platform/backend/app/services/inference_runtime_client.py`
- Modify: `ml-platform/backend/app/inference_runtime/runtime.py`
- Modify: `ml-platform/backend/app/inference_runtime/app.py`
- Modify: `ml-platform/backend/tests/test_inference_rollout.py`
- Modify: `ml-platform/backend/tests/test_inference_runtime.py`
- Modify: `ml-platform/backend/tests/test_inference_deployment.py`

- [x] **Step 1: Write failing deterministic-routing and CAS tests**

```python
def test_weighted_router_is_stable(self):
    db = self.db
    revision = make_revision_with_targets(db, [(stable_version, 7000), (candidate_version, 3000)])
    first = WeightedTargetRouter().select(revision, "request-42")
    second = WeightedTargetRouter().select(revision, "request-42")
    self.assertEqual(first.model_version_id, second.model_version_id)
    self.assertEqual(first.revision_id, revision.id)

def test_active_rollout_selects_revision_then_target(self):
    db = self.db
    rollout = make_progressing_rollout(db, candidate_weight_bps=1000)
    routed = WeightedTargetRouter().select_active(
        rollout.deployment, "request-42",
    )
    self.assertIn(routed.revision_id, {rollout.from_revision_id, rollout.to_revision_id})

def test_stale_rollout_command_is_rejected(self):
    db = self.db
    rollout = make_rollout(db, lock_version=2)
    with self.assertRaisesRegex(InferenceRolloutError, "ROLLOUT_REVISION_CONFLICT"):
        InferenceRolloutService(FakeRuntime()).advance(
            db, rollout.id, expected_lock_version=1,
        )
```

Add cases for unapproved/cross-project/duplicate targets, total weights, concurrent active rollout, preload failure, threshold failure, restored stable weights, repeat rollback, and restart reconciliation.

- [x] **Step 2: Run the rollout tests and verify RED**

```powershell
python -m unittest tests.test_inference_rollout tests.test_inference_runtime tests.test_inference_deployment -v
```

Expected: missing service/runtime-key behavior fails while existing Week 8 tests continue to execute.

- [x] **Step 3: Implement stable weighted selection**

```python
def select(self, revision, routing_key):
    targets = sorted(revision.targets, key=lambda item: str(item.model_version_id))
    if sum(item.weight_bps for item in targets) != 10000:
        raise InferenceRolloutError("TARGET_WEIGHTS_INVALID")
    digest = hashlib.sha256(
        f"{revision.deployment_id}:{routing_key}".encode("utf-8")
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") % 10000
    cumulative = 0
    for target in targets:
        cumulative += target.weight_bps
        if bucket < cumulative:
            return RoutedTarget(revision.id, target.model_version_id)
    raise InferenceRolloutError("TARGET_WEIGHTS_INVALID")
```

- [x] **Step 4: Implement the state machine and safe events**

Expose `create_candidate`, `preload`, `advance`, `pause`, `resume`, `rollback`, and `reconcile`. Use default steps `[0, 1000, 5000, 10000]` and frozen thresholds `{"max_error_rate": 0.01, "max_p95_ms": 500}`. Route in two stages while a rollout progresses: use the current step to choose the stable or candidate revision, then use that revision's target weights to choose the actual model version. Lock the rollout row, compare `expected_lock_version`, increment it in the same update, and persist step/state/error/timestamps. Restore last-known stable weights before recording `paused`, `failed`, or `rolled_back`. Emit only the seven frozen safe events through `DomainEventRecorder`; never commit inside the recorder.

- [x] **Step 5: Extend the private runtime with compatibility**

Add `runtime_key` to `LoadedDeployment`; when omitted, default to the Week 8 deployment ID. Index sessions by runtime key so `revision-1:model-a` and `revision-2:model-b` can coexist for one stable deployment. Internal list and prediction responses return `runtime_key`, `deployment_id`, `revision_id`, `model_version_id`, and version number. Keep `/internal/deployments/{runtime_key}` private behind `X-Inference-Internal-Token`; preserve Week 8 fields and `DEPLOYMENT_SPEC_CONFLICT` behavior.

- [x] **Step 6: Run GREEN and commit**

```powershell
python -m unittest tests.test_inference_rollout tests.test_inference_runtime tests.test_inference_deployment -v
git add ml-platform/backend/app/services/inference_rollout.py ml-platform/backend/app/services/inference_deployment.py ml-platform/backend/app/services/inference_runtime_client.py ml-platform/backend/app/inference_runtime ml-platform/backend/tests/test_inference_rollout.py ml-platform/backend/tests/test_inference_runtime.py ml-platform/backend/tests/test_inference_deployment.py
git commit -m "feat: add revision rollout and routing"
```

Expected: Week 8 compatibility, two-target load, deterministic routing, CAS, automatic restore, idempotent rollback, and restart reconciliation all pass.

### Task 7: Expose strict control-plane and production prediction APIs

**Files:**
- Modify: `ml-platform/backend/app/schemas/model_registry.py`
- Modify: `ml-platform/backend/app/api/model_registry.py`
- Create: `ml-platform/backend/app/api/inference_production.py`
- Modify: `ml-platform/backend/app/main.py`
- Modify: `ml-platform/backend/tests/test_api_model_registry.py`
- Modify: `ml-platform/backend/tests/test_api_inference_production.py`

- [ ] **Step 1: Write failing strict-route tests**

```python
def test_rollout_rejects_unknown_fields(self):
    response = self.client.post(
        f"/api/inference-deployments/{self.deployment_id}/rollouts",
        json={"strategy": "canary", "targets": [], "unexpected": True},
        headers=self.owner_headers,
    )
    self.assertEqual(response.status_code, 422)

def test_production_prediction_requires_api_key(self):
    response = self.client.post(
        f"/api/v1/inference/{self.deployment_id}/predict",
        json={"records": [{"current": 1.0}]},
    )
    self.assertEqual(response.status_code, 401)
    self.assertEqual(response.json()["detail"]["code"], "INFERENCE_API_KEY_INVALID")
```

Run `python -m unittest tests.test_api_model_registry tests.test_api_inference_production -v`. Expected: RED because schemas/routes are absent.

- [ ] **Step 2: Add strict schemas and control-plane routes**

Add `TargetCreate`, `RolloutCreate`, `RolloutCommand`, `ApiKeyCreate`, `MetricQuery`, `RequestLogQuery`, and `ModelCardGuidanceUpdate`, all inheriting the existing strict schema. Add list/detail/create/pause/resume/rollback routes, key create/list/rotate/revoke routes, paginated log/metric routes, and card read/update/export routes. Resolve deployment ownership before related resource lookup. Outsiders get hidden 404; visible members without permission get 403. Key plaintext appears only in create/rotate responses.

- [ ] **Step 3: Implement the API-key production route**

At `POST /api/v1/inference/{deployment_id}/predict`, read `X-Inference-Api-Key`, verify deployment scope, call Redis before runtime, choose the target using `X-Request-ID` or a generated UUID, call its runtime key, and return:

```json
{
  "request_id": "9b397ad4-966a-40e4-9509-56b5af0ea32f",
  "deployment_id": "d4130d3d-ae1f-462e-b06f-e61e6f75a9ab",
  "revision_id": "172a3579-5557-4520-96ec-b17097537f4f",
  "model_version_id": "e25372b8-c6ac-467d-8ec5-eeb9b68860e0",
  "version_number": 2,
  "predictions": [1],
  "probabilities": [[0.1, 0.9]],
  "duration_ms": 4.2
}
```

Map invalid key to 401, schema/size to 422/413, rate rejection to 429 plus `Retry-After`, Redis outage to `RATE_LIMIT_BACKEND_UNAVAILABLE` 503, and runtime failures to stable codes. Persist log/metric allowlists only; never write records, predictions, storage URI, key material, or raw exception text.

- [ ] **Step 4: Run API GREEN and commit**

```powershell
python -m unittest tests.test_api_model_registry tests.test_api_inference_production tests.test_api_project_access tests.test_module_imports -v
git add ml-platform/backend/app/schemas/model_registry.py ml-platform/backend/app/api/model_registry.py ml-platform/backend/app/api/inference_production.py ml-platform/backend/app/main.py ml-platform/backend/tests/test_api_model_registry.py ml-platform/backend/tests/test_api_inference_production.py
git commit -m "feat: expose production inference APIs"
```

Expected: strict bodies, roles, hidden outsider behavior, one-time key output, weighted response identity, stable errors, and old JWT prediction all pass.

### Task 8: Add idempotent Celery rollout and retention work

**Files:**
- Modify: `ml-platform/backend/app/tasks/inference_tasks.py`
- Modify: `ml-platform/backend/app/tasks/celery_app.py`
- Modify: `ml-platform/backend/tests/test_celery_workflows.py`
- Modify: `ml-platform/backend/tests/test_inference_deployment.py`

- [ ] **Step 1: Write failing task registration tests**

```python
def test_week9_task_names_are_stable(self):
    self.assertIn("ml_platform.advance_inference_rollout", celery_app.tasks)
    self.assertIn("ml_platform.rollback_inference_rollout", celery_app.tasks)
    self.assertIn("ml_platform.reconcile_inference_rollouts", celery_app.tasks)
    self.assertIn("ml_platform.prune_inference_telemetry", celery_app.tasks)
    self.assertEqual(
        celery_app.conf.beat_schedule["inference-rollout-reconciliation"]["schedule"],
        60.0,
    )

def test_duplicate_step_does_not_duplicate_runtime_load(self):
    first = self.service.advance(self.db, self.rollout.id, expected_lock_version=0)
    second = self.service.advance(self.db, self.rollout.id, expected_lock_version=0)
    self.assertEqual(first.state, second.state)
    self.assertEqual(self.runtime.load_calls, 1)
```

Run `python -m unittest tests.test_celery_workflows tests.test_inference_deployment -v`. Expected: RED on missing task names or duplicate side effects.

- [ ] **Step 2: Implement tasks with database-owned idempotency**

Register these exact names:

```python
@celery_app.task(name="ml_platform.advance_inference_rollout")
def advance_inference_rollout(rollout_id, expected_lock_version):
    with SessionLocal() as db:
        rollout = build_inference_rollout_service().advance(
            db, rollout_id, expected_lock_version=expected_lock_version,
        )
        return {"id": str(rollout.id), "state": rollout.state, "lock_version": rollout.lock_version}

@celery_app.task(name="ml_platform.reconcile_inference_rollouts")
def reconcile_inference_rollouts():
    with SessionLocal() as db:
        return build_inference_rollout_service().reconcile(db)
```

Add analogous rollback and telemetry-prune tasks. Each opens its own session, catches only known stable domain errors, and relies on persisted rollout state/lock version before a runtime side effect. Repeated delivery with the same expected version returns the persisted state without loading twice. Add 60-second rollout reconciliation and daily telemetry pruning to Beat.

- [ ] **Step 3: Run GREEN and commit**

```powershell
python -m unittest tests.test_celery_workflows tests.test_inference_deployment tests.test_inference_observability -v
git add ml-platform/backend/app/tasks ml-platform/backend/tests/test_celery_workflows.py ml-platform/backend/tests/test_inference_deployment.py
git commit -m "feat: orchestrate inference rollouts"
```

Expected: registration, Beat, duplicate delivery, stale CAS, restart recovery, rollback, and retention tests pass.

### Task 9: Build typed production-operations frontend

**Files:**
- Modify: `ml-platform/frontend/src/api/modelRegistry.ts`
- Modify: `ml-platform/frontend/src/api/modelRegistry.test.ts`
- Modify: `ml-platform/frontend/src/pages/ModelLibraryPage.tsx`
- Modify: `ml-platform/frontend/src/pages/ModelLibraryPage.test.tsx`
- Modify: `ml-platform/frontend/src/i18n/index.tsx`

- [ ] **Step 1: Write failing typed-client tests**

```typescript
it("creates a canary rollout and reads metric pages", async () => {
  vi.mocked(client.post).mockResolvedValueOnce({ data: { id: "r1", state: "pending" } });
  await createRollout("d1", {
    strategy: "canary",
    targets: [{ model_version_id: "v2", weight_bps: 10000, role: "candidate" }],
  });
  expect(client.post).toHaveBeenCalledWith(
    "/inference-deployments/d1/rollouts",
    expect.objectContaining({ strategy: "canary" }),
  );
  vi.mocked(client.get).mockResolvedValueOnce({ data: { items: [], total: 0 } });
  await expect(listInferenceMetrics("d1", metricWindow)).resolves.toEqual({ items: [], total: 0 });
});
```

Run:

```powershell
cd ml-platform/frontend
npm test -- --run src/api/modelRegistry.test.ts src/pages/ModelLibraryPage.test.tsx
```

Expected: RED on missing types/client calls/UI controls.

- [ ] **Step 2: Add typed API clients**

Define `DeploymentRevision`, `DeploymentTarget`, `DeploymentRollout`, `InferenceApiKey`, `CreatedInferenceApiKey`, `InferenceMetricBucket`, `InferenceRequestLog`, and `ModelCard`. Implement create/list/pause/resume/rollback, key create/list/rotate/revoke, metrics/log queries, and card read/update/export. Normalize only arrays or `{items,total}` and preserve server error codes. Never call `console.log` with a created key.

- [ ] **Step 3: Extend the existing operations page**

Add compact release progress and target-weight views, pause/resume/rollback confirmations, key management with one-time plaintext modal, three metric summaries (throughput, error rate, latency), paginated redacted logs, and a model-card drawer. Reuse existing role state: owner/editor manage releases and keys, operator operates releases and console prediction, viewer reads. Keep loading, empty, denied, failed, and mobile horizontal-scroll states. Give every icon command an explicit `aria-label`; use icons from the existing Ant Design icon library.

- [ ] **Step 4: Add symmetric bilingual strings and GREEN tests**

Add the identical `modelRegistry.production` key tree to English and Chinese. Tests must verify one-time key display disappears after closing, rollback confirmation, viewer read-only state, failed rollout code, metric empty state, and card guidance update.

```powershell
npm test -- --run src/api/modelRegistry.test.ts src/pages/ModelLibraryPage.test.tsx
npm run build
```

Expected: focused Vitest tests and TypeScript/Vite production build pass with no hard-coded visible Week 9 command strings.

- [ ] **Step 5: Commit the frontend**

```powershell
git add ml-platform/frontend/src/api/modelRegistry.ts ml-platform/frontend/src/api/modelRegistry.test.ts ml-platform/frontend/src/pages/ModelLibraryPage.tsx ml-platform/frontend/src/pages/ModelLibraryPage.test.tsx ml-platform/frontend/src/i18n/index.tsx
git commit -m "feat: add inference release operations UI"
```

### Task 10: Verify the real production lifecycle and Chromium flow

**Files:**
- Modify: `ml-platform/backend/tests/test_inference_production_stack.py`
- Modify: `ml-platform/backend/tests/test_suite_manifest.py`
- Modify: `ml-platform/docker-compose.yml`
- Modify: `ml-platform/.github/workflows/ci.yml`
- Modify: `ml-platform/frontend/e2e/model-inference.spec.ts`

- [ ] **Step 1: Add the gated real-service acceptance case**

```python
@unittest.skipUnless(
    os.getenv("RUN_INFERENCE_INTEGRATION") == "1",
    "production inference integration disabled",
)
def test_rollout_key_restart_and_rollback(self):
    self.assertEqual(alembic_head(), "20260720_09_production_inference")
    deployment = self.create_approved_deployment(version_number=1)
    plaintext = self.create_api_key(deployment["id"])["plaintext"]
    self.assertEqual(self.predict(plaintext, deployment["id"])["version_number"], 1)
    rollout = self.create_candidate(deployment["id"], version_number=2)
    self.advance_to_completion(rollout["id"])
    self.assertEqual(self.predict(plaintext, deployment["id"])["version_number"], 2)
    self.clear_runtime_sessions()
    self.reconcile()
    self.assertEqual(self.predict(plaintext, deployment["id"])["version_number"], 2)
    self.rollback(rollout["id"])
    self.assertEqual(self.predict(plaintext, deployment["id"])["version_number"], 1)
```

Also exhaust a low-capacity Redis bucket and assert 429 plus `Retry-After`, stop Redis and assert stable 503 without runtime invocation, then inspect database logs/events for forbidden values.

- [ ] **Step 2: Run the local gate and verify expected skip/RED**

```powershell
cd ml-platform/backend
python -m unittest tests.test_inference_production_stack tests.test_ci_workflow -v
```

Expected: the real-service case is explicitly skipped without `RUN_INFERENCE_INTEGRATION`; configuration assertions fail until Compose/CI settings are wired.

- [ ] **Step 3: Update isolated Compose and CI**

Keep `inference-runtime` on `expose: ["7000"]` with no host port. Pass the existing 32-character runtime secret and URL plus rate/rollout settings consistently to backend, worker, scheduler, runtime, and test process. In CI use a unique Compose project and temporary volumes, upgrade PostgreSQL to `20260720_09_production_inference`, run `RUN_INFERENCE_INTEGRATION=1`, collect logs only after existing redaction, scan for the known internal secret and created test key, and upload results. Never stop or recreate the user's default Compose stack.

- [ ] **Step 4: Extend browser acceptance without fixed sleeps**

Use real login and public APIs to prepare two approved versions. Through `/models`, start a canary, inspect revision/weight metadata, create a key and confirm plaintext is shown once, pause/resume, finish, predict actual v2, rollback to v1, and verify viewer controls are absent. Use accessible roles/names and response or state predicates.

- [ ] **Step 5: Run local GREEN checks**

```powershell
python -m unittest tests.test_suite_manifest tests.test_ci_workflow tests.test_inference_production_stack -v
cd ..\frontend
npm run build
npx playwright test e2e/model-inference.spec.ts --project=chromium
```

Expected: local configuration and Chromium checks pass; real service result must be obtained from isolated WSL/CI before completion.

- [ ] **Step 6: Commit delivery integration**

```powershell
git add ml-platform/backend/tests ml-platform/docker-compose.yml ml-platform/.github/workflows/ci.yml ml-platform/frontend/e2e/model-inference.spec.ts
git commit -m "test: verify production inference lifecycle"
```

### Task 11: Document and complete Week 9 acceptance

**Files:**
- Modify: `ml-platform/backend/tests/week_manifest.py`
- Modify: `ml-platform/backend/tests/test_suite_manifest.py`
- Modify: `docs/operations/inference.md`
- Create: `docs/week9-production-inference-acceptance.md`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `PLATFORM_STATUS.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Run the Week 9 and compatibility backend suites**

```powershell
cd ml-platform/backend
python run_suite.py --week 9
python -m unittest tests.test_inference_production_models tests.test_inference_rollout tests.test_inference_api_keys tests.test_inference_rate_limit tests.test_inference_observability tests.test_model_cards tests.test_api_inference_production tests.test_inference_runtime tests.test_inference_deployment tests.test_api_model_registry tests.test_celery_workflows -v
python run_suite.py --week 8
```

Expected: all Week 9 modules and all Week 8 compatibility modules pass; the production stack may skip only when its explicit environment gate is disabled.

- [ ] **Step 2: Run frontend, migration, security, and diff gates**

```powershell
cd ../frontend
npm test -- --run
npm run build
npm audit --audit-level=high --registry=https://registry.npmjs.org
cd ../backend
python -m unittest tests.test_database_production -v
python -m compileall -q app
rg -n "records|predictions|storage_uri|secret_hash|plaintext|traceback" app/api/inference_production.py app/services/inference_observability.py app/events/domain.py app/services/inference_rollout.py
git diff --check
```

Expected: frontend tests/build/audit pass, migration double-upgrade/current/check/downgrade passes, compile and diff checks are clean, and the source scan shows forbidden values only in explicit rejection/redaction code.

- [ ] **Step 3: Run isolated production and remote CI gates**

Build from the same Git commit, use isolated PostgreSQL/Redis/MinIO/runtime resources, and run the gated lifecycle. Record image digest, migration head, readiness, rollout/rollback results, rate-limit 429/503 results, runtime restart reconciliation, redaction scan, Chromium trace, and remote Actions URL. Clean only the isolated project and volumes.

- [ ] **Step 4: Write operations and acceptance evidence**

Document revision states, 0/10/50/100 flow, pause/resume/rollback, runtime-key privacy, API-key creation/rotation/revocation, 429/503 behavior, log/metric retention, card fields/export, stable errors, recovery, and verification commands. The acceptance record includes exact counts and evidence but no credentials, keys, model input, predictions, storage paths, customer data, or raw exceptions.

- [ ] **Step 5: Update status and reusable experience only after all gates pass**

Append the observed behavior, verified root cause, solution, verification, prevention, and remaining work to `DEVELOPMENT_PLAN.md`; update `PLATFORM_STATUS.md`; append reusable experience under `agent_spot_welding` in the shared experience file. Preserve all history. Week 9 remains `进行中` until code, tests, documentation, isolated production, Chromium, and remote CI are all green.

- [ ] **Step 6: Commit final evidence**

```powershell
git add docs ml-platform/backend/tests/week_manifest.py ml-platform/backend/tests/test_suite_manifest.py DEVELOPMENT_PLAN.md PLATFORM_STATUS.md
git commit -m "docs: complete week 9 inference acceptance"
```

Do not stage unrelated user changes. The shared experience file is outside the repository and is updated separately without secrets.

---

## Self-Review

**Spec coverage:** Persistence is Task 2; safe cross-week events are Task 3; keys and fail-closed limiting are Task 4; logs, metrics, retention, and cards are Task 5; rollout, rollback, weighted routing, runtime compatibility, and reconciliation are Task 6; strict APIs are Task 7; Celery idempotency is Task 8; UI is Task 9; production/Chromium evidence is Task 10; full acceptance and documentation are Task 11.

**Content scan:** Every production change has an exact path, a preceding failing test, an exact command with expected failure/success, a concrete implementation contract, and a commit boundary. No deferred implementation markers or abbreviated code bodies remain.

**Type consistency:** The runtime compatibility field is always `runtime_key`; public identity remains `deployment_id`; routing returns `revision_id` and actual `model_version_id`; all weights are integer basis points; `lock_version` is the sole rollout CAS field. The event contract is exactly `DomainEventRecorder.record(self, db: Session, event: DomainEvent) -> None`, and the recorder never commits.

**Migration consistency:** Week 9 revision is exactly `20260720_09_production_inference` with `down_revision = "20260718_08"`. It is the single Alembic head and leaves one linear successor point for Week 10. It creates no notification, endpoint, delivery, or outbox table.

**Compatibility:** Existing deployment IDs, names, desired/observed states, JWT console route, and Week 8 response fields remain valid. Existing deployments receive one stable revision and 10000-basis-point target during migration; no code mutates the legacy `model_version_id` after migration.
