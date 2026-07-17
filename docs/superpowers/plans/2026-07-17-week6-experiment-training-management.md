# Week 6 Experiment and Training Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver project-scoped MLflow experiment tracking, Celery-based iterative training and AutoML, metric history, early stopping, durable checkpoints and recovery, plus isolated TensorBoard access.

**Architecture:** The platform database remains the source of truth for authorization and TrainingJob lifecycle while MLflow owns Experiment Run parameters, metric history, tags, and experiment artifacts. Backend services hide MLflow and TensorBoard details from API routes; Celery executes all training; final models still enter ArtifactService and ModelLibrary.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/SQLite, Celery 5.4, Redis 7, MLflow, MinIO, scikit-learn incremental estimators, TensorBoard, React 18, TypeScript, Ant Design, ECharts, Vitest, Playwright, Docker Compose.

---

## File Map

- `ml-platform/backend/app/models/experiment.py`: platform Experiment binding and ownership.
- `ml-platform/backend/app/models/training.py`: business task state, Celery metadata, heartbeat, epoch, checkpoint, and resume lineage.
- `ml-platform/backend/app/schemas/experiment.py`: validated Experiment and Run comparison request/response contracts.
- `ml-platform/backend/app/services/experiment_tracking.py`: tracking protocol, MLflow adapter, DTOs, and error mapping.
- `ml-platform/backend/app/services/iterative_training.py`: deterministic incremental classifier/regressor, metrics, early stopping, and checkpoint serialization.
- `ml-platform/backend/app/services/training_execution.py`: database/Artifact/MLflow orchestration shared by Celery tasks.
- `ml-platform/backend/app/tasks/training_tasks.py`: Celery task entrypoints, claim, heartbeat, cancel, retry, and AutoML execution.
- `ml-platform/backend/app/tasks/training_recovery.py`: stale TrainingJob reconciliation.
- `ml-platform/backend/app/api/experiments.py`: project-authorized Experiment/Run/query/compare API.
- `ml-platform/backend/app/api/training.py`: artifact-only job creation, stop, checkpoint, resume, and TensorBoard session APIs.
- `ml-platform/backend/app/tensorboard_gateway/`: signed session validation, isolated TensorBoard process manager, and proxy application.
- `ml-platform/frontend/src/api/experiments.ts`: typed Experiment/Run/compare API client.
- `ml-platform/frontend/src/api/training.ts`: expanded job/checkpoint/resume/session client.
- `ml-platform/frontend/src/pages/TrainingJobsPage.tsx`: Experiment and Training Job operational tabs.
- `ml-platform/backend/tests/week_manifest.py`: unique Week 6 backend test ownership.
- `ml-platform/frontend/src/weekAcceptance.test.ts`: unique Week 6 frontend test ownership.

## Task 1: Week 6 Test Manifest and Production Configuration

**Files:**
- Modify: `ml-platform/backend/tests/week_manifest.py`
- Modify: `ml-platform/backend/app/config.py`
- Modify: `ml-platform/backend/.env.example`
- Modify: `ml-platform/backend/requirements.txt`
- Create: `ml-platform/backend/tests/test_experiment_config.py`

- [x] **Step 1: Add failing configuration tests**

Create tests that construct `Settings` in local and production modes and assert typed defaults plus production validation:

```python
class TestExperimentConfiguration(unittest.TestCase):
    def test_local_defaults_do_not_require_tracking_services(self):
        configured = Settings(_env_file=None, app_mode="local")
        self.assertEqual(configured.training_checkpoint_interval_epochs, 5)
        self.assertEqual(configured.training_stale_after_seconds, 300)

    def test_production_requires_mlflow_and_tensorboard_secret(self):
        with self.assertRaises(ValueError):
            Settings(
                _env_file=None,
                app_mode="production",
                database_url="postgresql+psycopg://postgres:test@db/app",
                secret_key="x" * 32,
                task_backend="celery",
                celery_broker_url="redis://redis:6379/0",
                celery_result_backend="redis://redis:6379/0",
                redis_events_url="redis://redis:6379/1",
                artifact_storage_backend="minio",
                minio_endpoint="minio:9000",
                minio_bucket="artifacts",
                minio_access_key="key",
                minio_secret_key="secret",
            )
```

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_experiment_config -v`
Expected: FAIL because MLflow/TensorBoard settings do not exist.

- [x] **Step 3: Add settings and dependencies**

Add fields with these exact semantics:

```python
mlflow_tracking_uri: str | None = None
mlflow_backend_store_uri: SecretStr | None = Field(default=None, exclude=True)
mlflow_artifact_root: str | None = None
tensorboard_gateway_url: str | None = None
tensorboard_session_secret: SecretStr | None = Field(default=None, exclude=True)
tensorboard_session_secret_file: Path | None = None
tensorboard_session_ttl_seconds: int = Field(default=300, ge=30, le=3600)
tensorboard_idle_timeout_seconds: int = Field(default=600, ge=60, le=86400)
training_checkpoint_interval_epochs: int = Field(default=5, ge=1, le=1000)
training_stale_after_seconds: int = Field(default=300, ge=30, le=86400)
```

Production validation must require tracking URI, artifact root, gateway URL, and a resolved session secret. Add `mlflow==3.1.*` and `tensorboard==2.19.*` to requirements and document every variable in `.env.example` without real credentials.

- [x] **Step 4: Register and run tests**

Add `test_experiment_config` as the first Week 6 module. Run:

```powershell
python -m unittest tests.test_experiment_config -v
python run_suite.py --week 5
```

Expected: configuration tests pass and Week 5 remains 13/13.

- [x] **Step 5: Commit**

```powershell
git add ml-platform/backend/app/config.py ml-platform/backend/.env.example ml-platform/backend/requirements.txt ml-platform/backend/tests/test_experiment_config.py ml-platform/backend/tests/week_manifest.py
git commit -m "feat: add experiment tracking configuration"
```

## Task 2: Experiment and Training Persistence

**Files:**
- Create: `ml-platform/backend/app/models/experiment.py`
- Modify: `ml-platform/backend/app/models/training.py`
- Modify: `ml-platform/backend/app/models/__init__.py`
- Modify: `ml-platform/backend/app/database_migrations.py`
- Create: `ml-platform/backend/alembic/versions/20260717_04_experiment_training_tracking.py`
- Create: `ml-platform/backend/tests/test_experiment_models.py`
- Modify: `ml-platform/backend/tests/test_database_production.py`

- [x] **Step 1: Write failing ORM and migration tests**

Test project-scoped uniqueness, relationships, nullable compatibility for legacy jobs, indexes, SQLite compatibility, and Alembic head:

```python
experiment = Experiment(
    project_id=project.id,
    created_by=user.id,
    name="Weld quality baseline",
    description="Baseline experiment",
    mlflow_experiment_id="42",
)
job = TrainingJob(
    project_id=project.id,
    user_id=user.id,
    experiment=experiment,
    name="incremental-classifier",
    status="pending",
    total_epochs=20,
    monitor_name="val_accuracy",
    monitor_mode="max",
)
self.assertEqual(job.experiment, experiment)
self.assertEqual(job.attempt, 0)
```

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_experiment_models tests.test_database_production -v`
Expected: FAIL because the model, columns, and revision are absent.

- [x] **Step 3: Implement models and migration**

Create Experiment with `UniqueConstraint("project_id", "name")` and indexes on project and MLflow ID. Extend TrainingJob with the fields frozen in the design. Use UUID foreign keys with `ondelete="SET NULL"` for Experiment and resume source, UTC-naive database timestamps consistent with existing models, `attempt` default 0, and `current_epoch` default 0.

The Alembic revision must create `experiments`, add TrainingJob columns and indexes, and define a complete downgrade. SQLite compatibility must add the same nullable columns without attempting foreign-key table rebuilds.

- [x] **Step 4: Verify GREEN and migration idempotency**

Run:

```powershell
python -m unittest tests.test_experiment_models tests.test_database_production -v
python -m unittest tests.test_database_transfer -v
```

Expected: all pass, including two consecutive Alembic upgrades and `alembic check`.

- [x] **Step 5: Commit**

```powershell
git add ml-platform/backend/app/models ml-platform/backend/app/database_migrations.py ml-platform/backend/alembic/versions/20260717_04_experiment_training_tracking.py ml-platform/backend/tests/test_experiment_models.py ml-platform/backend/tests/test_database_production.py
git commit -m "feat: add experiment and training tracking schema"
```

## Task 3: MLflow Tracking Adapter

**Files:**
- Create: `ml-platform/backend/app/services/experiment_tracking.py`
- Create: `ml-platform/backend/tests/test_experiment_tracking.py`

- [x] **Step 1: Write failing adapter contract tests**

Use an in-memory fake client object and assert stable DTOs and errors:

```python
tracking = MlflowExperimentTracking(client=fake_client, artifact_root="s3://artifacts/mlflow")
experiment_id = tracking.ensure_experiment("project/p1/e1")
run = tracking.start_run(
    experiment_id,
    run_name="baseline",
    tags={"platform.project_id": "p1", "platform.job_id": "j1"},
)
tracking.log_params(run.run_id, {"epochs": 10, "restore_best": True})
tracking.log_metrics(run.run_id, {"val_accuracy": 0.92}, step=3)
self.assertEqual(tracking.get_metric_history(run.run_id, "val_accuracy")[0].step, 3)
```

Cover parent/child runs, list/search filters, batch compare, artifact listing/download, terminal statuses, non-finite metric rejection, and conversion of MLflow exceptions to `TrackingUnavailable` or `TrackingNotFound`.

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_experiment_tracking -v`
Expected: FAIL because the adapter module is absent.

- [x] **Step 3: Implement protocol and MLflow adapter**

Define immutable DTOs `TrackedRun`, `TrackedMetric`, and `TrackedArtifact`, plus protocol methods used by later tasks. The concrete adapter receives an `MlflowClient`; module import must not connect to MLflow. Normalize params to strings, accept only finite numeric metrics, and preserve integer steps.

- [x] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_experiment_tracking -v`
Expected: all adapter contract tests pass without a network service.

- [x] **Step 5: Commit**

```powershell
git add ml-platform/backend/app/services/experiment_tracking.py ml-platform/backend/tests/test_experiment_tracking.py
git commit -m "feat: add mlflow experiment tracking adapter"
```

## Task 4: Project-Authorized Experiment API

**Files:**
- Create: `ml-platform/backend/app/schemas/experiment.py`
- Create: `ml-platform/backend/app/api/experiments.py`
- Modify: `ml-platform/backend/app/main.py`
- Create: `ml-platform/backend/tests/test_api_experiments.py`

- [x] **Step 1: Write failing API tests**

Cover create/list/detail, duplicate name, owner isolation, MLflow failure rollback, Run pagination, and 2-to-10 Run comparison:

```python
created = client.post("/api/experiments", json={
    "project_id": project_id,
    "name": "Weld baseline",
    "description": "Compare incremental models",
}, headers=owner_headers)
self.assertEqual(created.status_code, 201)
self.assertTrue(created.json()["mlflow_experiment_id"])
self.assertEqual(
    client.get(f"/api/experiments/{created.json()['id']}", headers=other_headers).status_code,
    404,
)
```

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_api_experiments -v`
Expected: FAIL with 404 routes.

- [x] **Step 3: Implement schemas and routes**

Use Pydantic models for create and compare. Resolve the owned Project before creating MLflow state. If database commit fails after MLflow creation, retain the MLflow experiment but return a structured database error; do not attempt irreversible MLflow deletion. Compare returns a deterministic matrix containing each selected Run's params, latest metrics, metric history, status, timestamps, and missing-value markers.

- [x] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_api_experiments -v`
Expected: all authorization and comparison tests pass.

- [x] **Step 5: Commit**

```powershell
git add ml-platform/backend/app/schemas/experiment.py ml-platform/backend/app/api/experiments.py ml-platform/backend/app/main.py ml-platform/backend/tests/test_api_experiments.py
git commit -m "feat: add project experiment api"
```

## Task 5: Incremental Trainer, Metrics, Early Stopping, and Checkpoints

**Files:**
- Create: `ml-platform/backend/app/services/iterative_training.py`
- Create: `ml-platform/backend/tests/test_iterative_training.py`

- [x] **Step 1: Write deterministic failing trainer tests**

Generate fixed classification and regression frames. Cover metrics per epoch, early stop, `restore_best`, cancellation callback, checkpoint interval, serialization round trip, incompatible checkpoint version, and resumed patience:

```python
result = trainer.fit(
    frame,
    target_column="quality",
    config=TrainingConfig(total_epochs=20, monitor="val_accuracy", mode="max", patience=2),
    metric_callback=metrics.append,
    checkpoint_callback=checkpoints.append,
    cancel_requested=lambda: False,
)
self.assertGreaterEqual(len(metrics), 2)
self.assertLess(result.epochs_completed, 20)
self.assertEqual(result.model_state.epoch, result.epochs_completed)
restored = TrainingCheckpoint.loads(checkpoints[-1].payload)
self.assertEqual(restored.format_version, 1)
```

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_iterative_training -v`
Expected: FAIL because trainer types do not exist.

- [x] **Step 3: Implement the pure training core**

Implement frozen `TrainingConfig`, `EpochMetrics`, `CheckpointEnvelope`, and `TrainingResult`. Use fixed train/validation split and StandardScaler. Use `SGDClassifier(loss="log_loss", random_state=42)` or `SGDRegressor(random_state=42)`, one `partial_fit` per epoch, finite float metrics, and joblib bytes. The core receives callbacks and has no SQLAlchemy, Celery, ArtifactService, or MLflow imports.

- [x] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_iterative_training -v`
Expected: all deterministic trainer tests pass on CPU.

- [x] **Step 5: Commit**

```powershell
git add ml-platform/backend/app/services/iterative_training.py ml-platform/backend/tests/test_iterative_training.py
git commit -m "feat: add resumable incremental trainer"
```

## Task 6: Training Execution Service and Celery Task

**Files:**
- Create: `ml-platform/backend/app/services/training_execution.py`
- Create: `ml-platform/backend/app/tasks/training_tasks.py`
- Modify: `ml-platform/backend/app/tasks/celery_app.py`
- Create: `ml-platform/backend/tests/test_training_tasks.py`

- [x] **Step 1: Write failing orchestration tests**

Use real SQLite ORM plus fake ArtifactService/tracking and the real iterative trainer. Assert atomic claim, MLflow Run binding, epoch heartbeat, latest/best checkpoint upload, final Artifact/ModelLibrary lineage, duplicate delivery skip, failure mapping, and cancellation:

```python
outcome = execute_training_job(
    job.id,
    session_factory=session_factory,
    artifact_service_factory=fake_artifacts,
    tracking_factory=lambda: fake_tracking,
    worker_id="worker-1",
)
self.assertEqual(outcome.status, "completed")
self.assertEqual(fake_tracking.metric_steps("val_accuracy"), sorted(fake_tracking.metric_steps("val_accuracy")))
self.assertTrue(job.latest_checkpoint_uri.startswith("mlflow-artifacts:/"))
self.assertIsNotNone(job.model_artifact_id)
```

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_training_tasks -v`
Expected: FAIL because execution service and task are absent.

- [x] **Step 3: Implement execution and Celery entrypoint**

Claim pending jobs with a row lock on PostgreSQL and conditional update fallback on SQLite. Start or resume a tracked Run, materialize Dataset Artifact, delegate to iterative trainer, upload checkpoints through tracking, and register the final model through ArtifactService. Commit terminal database state only after final artifacts and ModelLibrary are valid. Register task name `ml_platform.execute_training` and enable late ack plus worker-lost rejection inherited from Celery config.

- [x] **Step 4: Verify GREEN and worker import**

Run:

```powershell
python -m unittest tests.test_training_tasks -v
python -c "from app.tasks.celery_app import celery_app; assert 'ml_platform.execute_training' in celery_app.tasks"
```

Expected: all tests pass and task is registered.

- [x] **Step 5: Commit**

```powershell
git add ml-platform/backend/app/services/training_execution.py ml-platform/backend/app/tasks/training_tasks.py ml-platform/backend/app/tasks/celery_app.py ml-platform/backend/tests/test_training_tasks.py
git commit -m "feat: execute training through celery"
```

## Task 7: Checkpoint Resume, Stop, and Stale Recovery API

**Files:**
- Create: `ml-platform/backend/app/tasks/training_recovery.py`
- Modify: `ml-platform/backend/app/api/training.py`
- Modify: `ml-platform/backend/app/services/readiness_service.py`
- Create: `ml-platform/backend/tests/test_training_recovery.py`
- Modify: `ml-platform/backend/tests/test_training.py`

- [x] **Step 1: Replace permissive legacy assertions with failing contracts**

Require exact success/error results for stop, checkpoint list, and resume. Add stale recovery tests:

```python
stale = TrainingJob(status="running", heartbeat_at=utcnow() - timedelta(minutes=10), latest_checkpoint_uri="mlflow-artifacts:/latest")
recovered = reconcile_stale_training_jobs(db, active_task_ids=set(), stale_after=timedelta(minutes=5))
self.assertEqual(recovered.requeued, 1)
self.assertEqual(stale.status, "pending")
self.assertEqual(stale.attempt, 1)
```

- [x] **Step 2: Verify RED**

Run: `python -m unittest tests.test_training tests.test_training_recovery -v`
Expected: FAIL because legacy routes are missing or accept 404.

- [x] **Step 3: Implement strict APIs and reconciliation**

Replace global filesystem checkpoint listing with job-scoped MLflow artifacts. Resume creates a new job copying immutable dataset/config fields and recording source lineage; it validates checkpoint ownership and format before enqueue. Stop changes only active jobs to `cancel_requested` and revokes the task. Reconciliation follows the exact three-branch design for checkpoint, no checkpoint, and cancellation.

- [x] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_training tests.test_training_recovery -v`
Expected: no permissive status-code assertions remain and all cases pass.

- [x] **Step 5: Commit**

```powershell
git add ml-platform/backend/app/api/training.py ml-platform/backend/app/tasks/training_recovery.py ml-platform/backend/app/services/readiness_service.py ml-platform/backend/tests/test_training.py ml-platform/backend/tests/test_training_recovery.py
git commit -m "feat: add training checkpoint recovery"
```

## Task 8: Artifact-Based AutoML with MLflow Child Runs

**Files:**
- Create: `ml-platform/backend/app/services/automl_execution.py`
- Modify: `ml-platform/backend/app/tasks/training_tasks.py`
- Modify: `ml-platform/backend/app/api/training.py`
- Create: `ml-platform/backend/tests/test_automl_tracking.py`

- [ ] **Step 1: Write failing AutoML tests**

Assert dataset paths are rejected, parent and child Run relationships, partial candidate failure, all-failed behavior, deterministic best selection, and final model lineage:

```python
result = execute_automl_job(job.id, candidates=[working_candidate, failing_candidate], dependencies=deps)
self.assertEqual(result.status, "completed")
self.assertEqual(fake_tracking.parent_run_count, 1)
self.assertEqual(fake_tracking.child_run_count, 2)
self.assertEqual(fake_tracking.failed_child_count, 1)
self.assertEqual(fake_tracking.parent_tags["platform.best_child_run_id"], working_candidate.run_id)
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_automl_tracking -v`
Expected: FAIL because the AutoML service is absent and old API accepts paths.

- [ ] **Step 3: Implement finite candidate execution**

Use Dataset Artifact materialization and candidates RandomForest, GradientBoosting, LogisticRegression/LinearRegression with deterministic 5-fold scoring. Start one child Run per candidate, log params/score/duration/error, continue after individual failure, select highest finite score, train the winner, then register final model through ArtifactService and ModelLibrary. Dispatch through task `ml_platform.execute_automl`.

- [ ] **Step 4: Verify GREEN**

Run: `python -m unittest tests.test_automl_tracking tests.test_training_artifacts -v`
Expected: all AutoML tracking and existing lineage tests pass.

- [ ] **Step 5: Commit**

```powershell
git add ml-platform/backend/app/services/automl_execution.py ml-platform/backend/app/tasks/training_tasks.py ml-platform/backend/app/api/training.py ml-platform/backend/tests/test_automl_tracking.py
git commit -m "feat: track automl trials in mlflow"
```

## Task 9: Isolated TensorBoard Gateway

**Files:**
- Create: `ml-platform/backend/app/tensorboard_gateway/__init__.py`
- Create: `ml-platform/backend/app/tensorboard_gateway/tokens.py`
- Create: `ml-platform/backend/app/tensorboard_gateway/processes.py`
- Create: `ml-platform/backend/app/tensorboard_gateway/app.py`
- Modify: `ml-platform/backend/app/api/training.py`
- Create: `ml-platform/backend/tests/test_tensorboard_gateway.py`

- [ ] **Step 1: Write failing security and lifecycle tests**

Cover valid token, tampering, expiry, traversal, run mismatch, process reuse, idle cleanup, fixed root containment, and backend owner authorization:

```python
token = signer.issue(session_id="s1", run_id="r1", relative_logdir="p1/r1", expires_at=clock.now() + 60)
claims = signer.verify(token)
self.assertEqual(claims.run_id, "r1")
with self.assertRaises(SessionTokenInvalid):
    signer.verify(token + "tampered")
with self.assertRaises(SessionPathInvalid):
    manager.resolve_logdir("../other-project")
```

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_tensorboard_gateway -v`
Expected: FAIL because gateway modules do not exist.

- [ ] **Step 3: Implement gateway and platform proxy contract**

Use URL-safe base64 JSON plus HMAC-SHA256 and constant-time comparison. Process manager allocates localhost ports, launches `python -m tensorboard.main` with fixed logdir and path prefix, records last access, reuses only matching Run sessions, and terminates expired processes. Gateway exposes internal session creation and proxy paths; platform creates signed sessions only after job ownership validation and returns a backend proxy URL. Never accept an absolute logdir or shell string.

- [ ] **Step 4: Verify GREEN and import smoke**

Run:

```powershell
python -m unittest tests.test_tensorboard_gateway -v
python -c "from app.tensorboard_gateway.app import app; assert app"
```

Expected: all isolation/lifecycle tests pass.

- [ ] **Step 5: Commit**

```powershell
git add ml-platform/backend/app/tensorboard_gateway ml-platform/backend/app/api/training.py ml-platform/backend/tests/test_tensorboard_gateway.py
git commit -m "feat: add isolated tensorboard gateway"
```

## Task 10: Frontend Experiment and Training APIs

**Files:**
- Create: `ml-platform/frontend/src/api/experiments.ts`
- Create: `ml-platform/frontend/src/api/experiments.test.ts`
- Modify: `ml-platform/frontend/src/api/training.ts`
- Modify: `ml-platform/frontend/src/api/training.test.ts`
- Modify: `ml-platform/frontend/src/weekAcceptance.test.ts`

- [ ] **Step 1: Write failing client tests**

Assert exact endpoints and typed payloads for create/list/detail/runs/compare, checkpoint list, stop, resume, and TensorBoard session:

```typescript
await compareExperimentRuns("experiment-1", ["run-1", "run-2"]);
expect(post).toHaveBeenCalledWith("/experiments/experiment-1/compare", {
  run_ids: ["run-1", "run-2"],
});
await resumeTrainingJob("job-1", "checkpoints/best.joblib");
expect(post).toHaveBeenCalledWith("/training/jobs/job-1/resume", {
  checkpoint_path: "checkpoints/best.joblib",
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- src/api/experiments.test.ts src/api/training.test.ts`
Expected: FAIL because clients are absent.

- [ ] **Step 3: Implement typed clients**

Define Experiment, ExperimentRun, MetricPoint, RunComparison, TrainingCheckpoint, and TensorBoardSession types. Keep unknown MLflow params JSON-safe and normalize API collections from either arrays or `{items}` only where existing API compatibility requires it.

- [ ] **Step 4: Verify GREEN and register Week 6 ownership**

Run: `npm test -- src/api/experiments.test.ts src/api/training.test.ts`
Expected: all API contract tests pass.

- [ ] **Step 5: Commit**

```powershell
git add ml-platform/frontend/src/api/experiments.ts ml-platform/frontend/src/api/experiments.test.ts ml-platform/frontend/src/api/training.ts ml-platform/frontend/src/api/training.test.ts ml-platform/frontend/src/weekAcceptance.test.ts
git commit -m "feat: add experiment tracking frontend api"
```

## Task 11: Experiment and Training Operations UI

**Files:**
- Modify: `ml-platform/frontend/src/pages/TrainingJobsPage.tsx`
- Modify: `ml-platform/frontend/src/pages/TrainingJobsPage.test.tsx`
- Modify: `ml-platform/frontend/src/i18n/index.tsx`

- [ ] **Step 1: Write failing interaction tests**

Mock API clients and test Experiment/Job tabs, create experiment, select 2 Runs, comparison rendering, checkpoint resume, stop confirmation, and TensorBoard open:

```typescript
render(<TrainingJobsPage />);
await user.click(await screen.findByRole("tab", { name: "Experiments" }));
await user.click(screen.getByRole("checkbox", { name: "run-a" }));
await user.click(screen.getByRole("checkbox", { name: "run-b" }));
await user.click(screen.getByRole("button", { name: "Compare" }));
expect(await screen.findByText("val_accuracy")).toBeInTheDocument();
expect(screen.getByText("0.94")).toBeInTheDocument();
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- src/pages/TrainingJobsPage.test.tsx`
Expected: FAIL because tabs and actions are absent.

- [ ] **Step 3: Implement the operational UI**

Use Ant Design Tabs, compact Tables, Drawer/Modal, Progress, Select, and icon buttons. Render metric history with existing ECharts dependency. Keep stable table dimensions, responsive modal width, no nested cards, and no direct MLflow/TensorBoard URL construction. Add complete Chinese and English translation keys with identical structure.

- [ ] **Step 4: Verify GREEN and build**

Run:

```powershell
npm test -- src/pages/TrainingJobsPage.test.tsx
npm run build
```

Expected: interaction tests and TypeScript/Vite build pass without text overflow warnings.

- [ ] **Step 5: Commit**

```powershell
git add ml-platform/frontend/src/pages/TrainingJobsPage.tsx ml-platform/frontend/src/pages/TrainingJobsPage.test.tsx ml-platform/frontend/src/i18n/index.tsx
git commit -m "feat: add experiment and training operations ui"
```

## Task 12: Compose, Readiness, and Real Production Integration

**Files:**
- Modify: `docker-compose.yml`
- Modify: `ml-platform/backend/Dockerfile`
- Create: `ml-platform/backend/Dockerfile.tensorboard`
- Modify: `ml-platform/backend/app/services/readiness_service.py`
- Modify: `ml-platform/backend/tests/test_readiness.py`
- Create: `ml-platform/backend/tests/test_experiment_production_stack.py`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Write failing readiness and integration tests**

Readiness must report `mlflow` and `tensorboard`; real integration, gated by `RUN_EXPERIMENT_INTEGRATION=1`, must create Experiment/Run, log metrics, upload/download checkpoint, execute Celery training, resume, compare, and create an isolated TensorBoard session.

- [ ] **Step 2: Verify RED/local skip**

Run:

```powershell
python -m unittest tests.test_readiness -v
python -m unittest tests.test_experiment_production_stack -v
```

Expected: readiness fails new assertions; production module skips only because the environment gate is disabled.

- [ ] **Step 3: Add deployable services and CI**

Create MLflow database during PostgreSQL initialization, start `mlflow server --host 0.0.0.0 --port 5000` with PostgreSQL backend and `s3://<bucket>/mlflow`, add MinIO credentials and endpoint, add non-root TensorBoard gateway on the internal network, and mount only the controlled event cache volume. Backend and Worker depend on healthy MLflow/gateway. CI starts identical services, runs Alembic twice/check, starts Worker, runs the real module, redacts logs, and always cleans up.

- [ ] **Step 4: Verify WSL Docker production stack**

Run in WSL:

```bash
docker compose config
docker compose build backend worker tensorboard-gateway
docker compose up -d
RUN_EXPERIMENT_INTEGRATION=1 python -m unittest tests.test_experiment_production_stack -v
curl --fail http://127.0.0.1:8000/api/ready
docker compose down
```

Expected: real integration passes; readiness reports database, Redis, Celery, storage, MLflow, and TensorBoard ready.

- [ ] **Step 5: Commit**

```powershell
git add docker-compose.yml ml-platform/backend/Dockerfile ml-platform/backend/Dockerfile.tensorboard ml-platform/backend/app/services/readiness_service.py ml-platform/backend/tests/test_readiness.py ml-platform/backend/tests/test_experiment_production_stack.py .github/workflows/ci.yml
git commit -m "ci: verify week 6 experiment services"
```

## Task 13: Documentation and Complete Acceptance

**Files:**
- Modify: `ml-platform/USAGE.md`
- Modify: `docs/baseline/FEATURE_INVENTORY.md`
- Modify: `docs/baseline/BUILD_AND_TEST.md`
- Modify: `docs/baseline/TECHNICAL_DEBT.md`
- Create: `docs/delivery/EXPERIMENT_TRAINING_OPERATIONS.md`
- Modify: `PLATFORM_STATUS.md`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Run Week 6 and backend regression**

```powershell
cd ml-platform/backend
python run_suite.py --week 6
python run_suite.py
```

Expected: every Week 6 and Week 1-6 module passes; production modules skip only when explicit gates are disabled.

- [ ] **Step 2: Run frontend and browser acceptance**

```powershell
cd ml-platform/frontend
npm test
npm run build
npx playwright test --project=chromium
npm audit --registry=https://registry.npmjs.org
```

Expected: all tests pass, build succeeds, Chromium covers experiment comparison/resume/TensorBoard session, and audit reports 0 vulnerabilities.

- [ ] **Step 3: Run migration, compile, and secret checks**

```powershell
cd ml-platform/backend
alembic upgrade head
alembic current
alembic check
python -m compileall app tools tests
cd ../..
git grep -n -E "AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|change-me-in-production" -- ':!docs/superpowers/**'
git diff --check
```

Expected: revision `20260717_04` is head, no new migration operations, compile succeeds, no real credentials, and diff check is clean.

- [ ] **Step 4: Write operations and status documentation**

Document MLflow/MinIO/PostgreSQL configuration, Experiment lifecycle, training/AutoML submission, checkpoint recovery, TensorBoard session behavior, rollback to local tracking-disabled mode, log locations, error codes, backup scope, and security limitations. Append every encountered problem with observed behavior, verified root cause, solution, verification, and prevention.

- [ ] **Step 5: Push and verify GitHub Actions**

Push the branch and wait for Windows quality, Ubuntu quality, production experiment integration, and Chromium acceptance. Record Run URL, job conclusions, MLflow/PostgreSQL/Redis/MinIO/Celery/TensorBoard versions, and test counts. Do not mark Week 6 complete before the final documentation commit also has a green Run.

- [ ] **Step 6: Final workspace audit**

```powershell
git status --short
git diff --check
```

Expected: only scoped Week 6 changes and the user's pre-existing uncommitted files are present. Clean only generated Week 6 paths under `temp_test`; do not modify user DOCX, `docs2/`, generated scripts, or pre-existing deletions.

- [ ] **Step 7: Commit final acceptance**

```powershell
git add DEVELOPMENT_PLAN.md PLATFORM_STATUS.md ml-platform/USAGE.md docs/baseline docs/delivery/EXPERIMENT_TRAINING_OPERATIONS.md
git commit -m "docs: complete week 6 experiment tracking"
git push origin codex/week-4-industrial-delivery
```
