# Week 8 Model Registry and Basic Inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a project-scoped immutable ONNX model registry and a dedicated basic inference runtime with approval, audited deployment lifecycle, schema-validated JSON predictions, production composition, and operations UI.

**Architecture:** Keep `ModelLibrary` as the mutable training-result catalog. Add PostgreSQL-backed `RegisteredModel`, immutable `ModelVersion`, and `InferenceDeployment` control-plane records. Convert trusted platform joblib artifacts to validated ONNX during registration, store ONNX as a separate Artifact, and use an internal authenticated ONNX Runtime service for load, unload, predict, health, and restart reconciliation.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, PostgreSQL, MinIO, Celery/Redis, ONNX, ONNX Runtime, skl2onnx, React 18, TypeScript, Ant Design, Vitest, Playwright, Docker Compose, GitHub Actions.

---

## File Map

### Backend control plane

- Create `ml-platform/backend/app/models/model_registry.py`: registry and deployment ORM entities.
- Create `ml-platform/backend/app/schemas/model_registry.py`: strict public request/response schemas.
- Create `ml-platform/backend/app/services/onnx_conversion.py`: parent-side conversion and ONNX validation boundary.
- Create `ml-platform/backend/app/services/onnx_worker.py`: allowlisted joblib-to-ONNX subprocess entry.
- Create `ml-platform/backend/app/services/model_registry.py`: upload, version allocation, conversion, compensation, and lifecycle rules.
- Create `ml-platform/backend/app/services/inference_runtime_client.py`: authenticated internal HTTP client.
- Create `ml-platform/backend/app/services/inference_deployment.py`: desired/observed state saga and prediction validation.
- Create `ml-platform/backend/app/api/model_registry.py`: public project-scoped registry/deployment API.
- Create `ml-platform/backend/app/tasks/inference_tasks.py`: periodic reconciliation task.
- Modify `ml-platform/backend/app/models/__init__.py`, `app/main.py`, `app/config.py`, `app/services/readiness_service.py`, `app/api/readiness.py`, `app/tasks/celery_app.py`, and `app/services/project_access.py`.

### Inference data plane

- Create `ml-platform/backend/app/inference_runtime/__init__.py`.
- Create `ml-platform/backend/app/inference_runtime/runtime.py`: ONNX session cache and tensor execution.
- Create `ml-platform/backend/app/inference_runtime/app.py`: internal authenticated FastAPI application.
- Create `ml-platform/backend/Dockerfile.inference`.
- Modify `docker-compose.yml` and `.github/workflows/ci.yml`.

### Migration and tests

- Create `ml-platform/backend/alembic/versions/20260718_08_model_registry_inference.py`.
- Create `ml-platform/backend/tests/test_model_registry_models.py`.
- Create `ml-platform/backend/tests/test_onnx_conversion.py`.
- Create `ml-platform/backend/tests/test_model_registry_service.py`.
- Create `ml-platform/backend/tests/test_inference_runtime.py`.
- Create `ml-platform/backend/tests/test_inference_deployment.py`.
- Create `ml-platform/backend/tests/test_api_model_registry.py`.
- Create `ml-platform/backend/tests/test_inference_production_stack.py`.
- Modify migration, configuration, readiness, access, CI, manifest, and module-import tests.

### Frontend and delivery

- Create `ml-platform/frontend/src/api/modelRegistry.ts` and `modelRegistry.test.ts`.
- Replace `ml-platform/frontend/src/pages/ModelLibraryPage.tsx`.
- Create `ml-platform/frontend/src/pages/ModelLibraryPage.test.tsx`.
- Modify `ml-platform/frontend/src/i18n/index.tsx`.
- Create `ml-platform/frontend/e2e/model-inference.spec.ts`.
- Create `docs/delivery/MODEL_REGISTRY_INFERENCE.md`.
- Modify `DEVELOPMENT_PLAN.md`, `PLATFORM_STATUS.md`, and shared development experience.

---

### Task 1: Pin ONNX dependencies and build the safe conversion boundary

**Files:**
- Modify: `ml-platform/backend/requirements.txt`
- Create: `ml-platform/backend/app/services/onnx_conversion.py`
- Create: `ml-platform/backend/app/services/onnx_worker.py`
- Create: `ml-platform/backend/tests/test_onnx_conversion.py`

- [x] **Step 1: Add RED conversion contract tests**

Test a platform-produced `LogisticRegression` package containing `model`, optional `scaler`, `feature_schema`, and `target_schema`. Assert conversion returns input/output names, opset, SHA-256, and a loadable `.onnx` file. Add explicit cases for unsupported estimator, malformed package, conversion timeout, invalid output, and synthetic smoke inference failure.

```python
def test_platform_joblib_converts_to_valid_onnx(self):
    result = convert_platform_joblib(
        self.source,
        self.destination,
        timeout_seconds=120,
    )
    self.assertEqual(result.input_names, ("features",))
    self.assertTrue(result.sha256)
    onnx.checker.check_model(str(self.destination))

def test_unknown_estimator_is_rejected(self):
    with self.assertRaisesRegex(ConversionError, "MODEL_CONVERSION_UNSUPPORTED"):
        convert_platform_joblib(self.unknown_source, self.destination)
```

- [x] **Step 2: Run tests and confirm missing-module RED**

```powershell
python -m unittest tests.test_onnx_conversion -v
```

Expected: import failure for `app.services.onnx_conversion`.

- [x] **Step 3: Configure the required pip source and install pinned dependencies**

```powershell
python -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
python -m pip install "onnx==1.18.*" "onnxruntime==1.22.*" "skl2onnx==1.19.*"
```

Add the same pins to `requirements.txt`. Do not replace the configured Aliyun source.

- [x] **Step 4: Implement parent conversion and validation API**

Expose a stable boundary:

```python
@dataclass(frozen=True)
class ConversionResult:
    input_names: tuple[str, ...]
    output_names: tuple[str, ...]
    opset: int
    sha256: str
    size: int
    converter: str

class ConversionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

```

Implement `convert_platform_joblib(source: Path, destination: Path, *, timeout_seconds: int = 120) -> ConversionResult` and `validate_onnx(path: Path, feature_schema: list[dict[str, str]], output_schema: dict[str, object]) -> ConversionResult` with the behavior below.

The parent launches `python -m app.services.onnx_worker` in a private temporary directory, sends only fixed JSON arguments, applies the timeout, and maps exit results to stable codes. Validation runs `onnx.checker`, creates an ONNX Runtime CPU session, checks manifest names/shapes, and executes one schema-derived synthetic record.

- [x] **Step 5: Implement the allowlisted worker**

The worker loads only a provenance-checked platform Artifact passed by the parent. Accept `LogisticRegression`, `LinearRegression`, `RandomForestClassifier`, `RandomForestRegressor`, `GradientBoostingClassifier`, and `GradientBoostingRegressor`, plus an optional fitted `StandardScaler`. Build a `Pipeline` when the scaler exists and call `skl2onnx.convert_sklearn` with a single `FloatTensorType([None, feature_count])` input named `features`. Reject all other types before conversion.

- [x] **Step 6: Verify RED-to-GREEN and dependency health**

```powershell
python -m unittest tests.test_onnx_conversion -v
python -m pip check
```

Expected: all conversion cases pass; `pip check` reports no broken requirements.

- [x] **Step 7: Commit conversion boundary**

```powershell
git add ml-platform/backend/requirements.txt ml-platform/backend/app/services/onnx_conversion.py ml-platform/backend/app/services/onnx_worker.py ml-platform/backend/tests/test_onnx_conversion.py
git commit -m "feat: add safe ONNX model conversion"
```

---

### Task 2: Add immutable registry and deployment persistence

**Files:**
- Create: `ml-platform/backend/app/models/model_registry.py`
- Modify: `ml-platform/backend/app/models/__init__.py`
- Create: `ml-platform/backend/alembic/versions/20260718_08_model_registry_inference.py`
- Create: `ml-platform/backend/tests/test_model_registry_models.py`
- Modify: `ml-platform/backend/tests/test_database_production.py`

- [x] **Step 1: Write RED ORM constraint and migration tests**

Cover project/name uniqueness, per-model version uniqueness, valid source/approval/deployment state checks, exact Artifact foreign keys, `SET NULL` actor history, cascade ownership, and immutable version fields at the service boundary. Update expected production head to `20260718_08` and business table count from 35 to 38.

Name the focused cases `test_registered_model_name_is_unique_per_project`, `test_version_number_is_unique_per_registered_model`, `test_deployment_requires_exact_model_version`, and `test_model_registry_revision_has_complete_downgrade`. Each must create real SQLAlchemy rows or execute the real Alembic revision rather than mock constraints.

- [x] **Step 2: Run model and migration tests for RED**

```powershell
python -m unittest tests.test_model_registry_models tests.test_database_production -v
```

Expected: missing model module, head mismatch, and table-count failures.

- [x] **Step 3: Implement ORM entities**

Create `RegisteredModel`, `ModelVersion`, and `InferenceDeployment` with named unique/check constraints and indexes. Use these frozen state values:

```python
MODEL_SOURCE_KINDS = ("platform_joblib", "onnx_artifact")
APPROVAL_STATES = ("pending", "approved", "rejected", "archived")
DESIRED_STATES = ("stopped", "running")
OBSERVED_STATES = ("stopped", "starting", "running", "stopping", "failed")
```

Store `feature_schema`, `output_schema`, `metrics`, and `conversion_metadata` as non-null JSON with empty defaults. Add relationships only where they clarify ownership; do not add mutable backrefs to immutable versions.

- [x] **Step 4: Add Alembic revision `20260718_08`**

Create all three tables, constraints, and query indexes. Downgrade removes indexes and tables in dependency order. Update `HEAD_REVISION` and exact table assertions.

- [x] **Step 5: Verify ORM and clean migration**

```powershell
$db = Join-Path $env:TEMP ("week8-models-" + [guid]::NewGuid().ToString("N") + ".db")
$env:DATABASE_URL = "sqlite:///" + ($db -replace '\\','/')
alembic upgrade head
alembic upgrade head
alembic current
alembic check
python -m unittest tests.test_model_registry_models tests.test_database_production -v
```

Expected: current revision `20260718_08`; no new upgrade operations; downgrade test passes.

- [x] **Step 6: Commit persistence**

```powershell
git add ml-platform/backend/app/models ml-platform/backend/alembic/versions/20260718_08_model_registry_inference.py ml-platform/backend/tests/test_model_registry_models.py ml-platform/backend/tests/test_database_production.py
git commit -m "feat: add model registry persistence"
```

---

### Task 3: Implement upload, registration, version allocation, and approval services

**Files:**
- Modify: `ml-platform/backend/app/services/artifact_service.py`
- Create: `ml-platform/backend/app/services/model_registry.py`
- Create: `ml-platform/backend/tests/test_model_registry_service.py`

- [x] **Step 1: Write RED service behavior tests**

Test streamed ONNX upload with SHA-256 and 256 MiB limit, upload compensation, trusted platform provenance, hidden cross-project source, monotonic concurrent version allocation, conversion compensation, immutable version snapshots, approve/reject/archive transitions, rejection comment requirement, and idempotent same-state approval.

Name the focused cases `test_registration_compensates_onnx_when_commit_fails`, `test_platform_source_requires_training_provenance`, `test_versions_allocate_monotonically_under_concurrency`, and `test_approved_version_snapshot_is_immutable`. Use real temporary storage and database transactions; only inject the converter or commit failure where the external failure is the behavior under test.

- [x] **Step 2: Confirm service RED**

```powershell
python -m unittest tests.test_model_registry_service -v
```

Expected: missing `ModelRegistryService` and stream upload API.

- [x] **Step 3: Add bounded stream persistence**

Add `ArtifactService.create_from_stream(project_id, stream, filename, artifact_type, metadata, max_bytes, commit=False)`. Copy in 1 MiB chunks to a private temporary file, reject once cumulative bytes exceed `max_bytes`, then delegate to `create_from_file`. Always delete the temporary file. Use the existing storage compensation path.

- [x] **Step 4: Implement registry domain service**

Expose explicit methods `create_registered_model(db, *, project_id, actor_id, name, description)`, `register_platform_version(db, *, model_id, source_model_library_id)`, `register_onnx_version(db, *, model_id, source_artifact_id, feature_schema, output_schema)`, `approve(db, version_id, actor_id, comment="")`, `reject(db, version_id, actor_id, comment)`, and `archive(db, version_id, actor_id, comment="")` on `ModelRegistryService`.

Lock the `RegisteredModel` row before calculating `max(version_number)+1`. Freeze source descriptors and metrics. Registration stores the ONNX Artifact before the registry transaction and deletes it on transaction failure. Domain exceptions expose only the stable codes from the design.

- [x] **Step 5: Verify service GREEN and Artifact regressions**

```powershell
python -m unittest tests.test_model_registry_service tests.test_artifact_service tests.test_storage -v
```

- [x] **Step 6: Commit registry service**

```powershell
git add ml-platform/backend/app/services/artifact_service.py ml-platform/backend/app/services/model_registry.py ml-platform/backend/tests/test_model_registry_service.py
git commit -m "feat: register immutable ONNX model versions"
```

---

### Task 4: Build the authenticated ONNX inference runtime

**Files:**
- Create: `ml-platform/backend/app/inference_runtime/__init__.py`
- Create: `ml-platform/backend/app/inference_runtime/runtime.py`
- Create: `ml-platform/backend/app/inference_runtime/app.py`
- Create: `ml-platform/backend/tests/test_inference_runtime.py`

- [x] **Step 1: Write RED runtime tests**

Cover missing/invalid internal token, ONNX load, repeated load idempotency, conflicting spec rejection, unload idempotency, exact feature validation, 1-100 record limits, 1 MiB request limit, NaN/infinity rejection, prediction output, optional probabilities, duration/version identity, and concurrent prediction during unload.

Name the focused cases `test_internal_routes_require_constant_time_token_auth`, `test_load_and_unload_are_idempotent`, `test_predict_orders_named_features_by_frozen_schema`, and `test_predict_rejects_unknown_missing_and_non_finite_values`. Generate a tiny real ONNX fixture and assert actual ONNX Runtime results rather than mocking the session.

- [x] **Step 2: Confirm missing-runtime RED**

```powershell
python -m unittest tests.test_inference_runtime -v
```

- [x] **Step 3: Implement session cache and tensor execution**

`RuntimeRegistry` owns a lock-protected mapping of deployment UUID to immutable `LoadedDeployment` records. Materialize only controlled Artifact URIs through `ArtifactStorage`, validate SHA-256/size before `onnxruntime.InferenceSession`, and use CPUExecutionProvider. Convert ordered records to NumPy tensors according to frozen schema. Acquire a loaded record reference before inference so unload cannot invalidate an active call.

- [x] **Step 4: Implement internal FastAPI routes**

```text
GET    /health
GET    /internal/deployments
PUT    /internal/deployments/{deployment_id}
DELETE /internal/deployments/{deployment_id}
POST   /internal/deployments/{deployment_id}/predict
```

Protect every `/internal` route with `X-Inference-Internal-Token` and `hmac.compare_digest`. Return stable codes without paths, tokens, URI credentials, record values, or exception text.

- [x] **Step 5: Verify runtime GREEN**

```powershell
python -m unittest tests.test_inference_runtime -v
python -m compileall -q app/inference_runtime
```

- [x] **Step 6: Commit runtime**

```powershell
git add ml-platform/backend/app/inference_runtime ml-platform/backend/tests/test_inference_runtime.py
git commit -m "feat: add authenticated ONNX inference runtime"
```

---

### Task 5: Add deployment saga, prediction boundary, reconciliation, and readiness

**Files:**
- Modify: `ml-platform/backend/app/config.py`
- Modify: `ml-platform/backend/app/services/project_access.py`
- Create: `ml-platform/backend/app/services/inference_runtime_client.py`
- Create: `ml-platform/backend/app/services/inference_deployment.py`
- Create: `ml-platform/backend/app/tasks/inference_tasks.py`
- Modify: `ml-platform/backend/app/tasks/celery_app.py`
- Modify: `ml-platform/backend/app/services/readiness_service.py`
- Modify: `ml-platform/backend/app/api/readiness.py`
- Create: `ml-platform/backend/tests/test_inference_deployment.py`
- Modify: `ml-platform/backend/tests/test_config.py`
- Modify: `ml-platform/backend/tests/test_readiness.py`
- Modify: `ml-platform/backend/tests/test_celery_workflows.py`

- [ ] **Step 1: Write RED configuration and deployment tests**

Require `INFERENCE_RUNTIME_URL` and an internal secret/direct-file pair in production; redact both from settings errors and summaries. Test owner/editor create permission, operator start/stop/predict permission, approved-only deployment, state saga success/failure, repeated command idempotency, 30-second predict timeout, safe error persistence, and reconciliation after an empty runtime restart.

- [ ] **Step 2: Confirm focused RED**

```powershell
python -m unittest tests.test_config tests.test_readiness tests.test_inference_deployment tests.test_celery_workflows -v
```

- [ ] **Step 3: Add settings and permissions**

Add:

```python
inference_runtime_url: str | None = None
inference_internal_secret: SecretStr | None = Field(default=None, exclude=True)
inference_internal_secret_file: str | None = Field(default=None, exclude=True)
inference_conversion_timeout_seconds: int = Field(default=120, ge=10, le=600)
inference_load_timeout_seconds: int = Field(default=60, ge=5, le=300)
inference_predict_timeout_seconds: int = Field(default=30, ge=1, le=120)
```

Resolve the secret pair like existing TensorBoard secrets. Add `model.register`, `model.approve`, `deployment.create`, and `inference.operate` to the frozen project permission matrix with the confirmed role assignments.

- [ ] **Step 4: Implement runtime client and deployment service**

The client sends the internal token, uses exact timeouts, and maps network/status failures to stable domain codes. `InferenceDeploymentService` exposes create/start/stop/predict/reconcile methods. Commit command acceptance and desired/starting state before the remote call; persist observed result afterward in a new transaction. Never persist raw records or predictions.

- [ ] **Step 5: Register periodic reconciliation**

Register `ml_platform.reconcile_inference_deployments` and add it to Beat at 60 seconds. Include `app.tasks.inference_tasks` in worker discovery without creating a Celery import cycle.

- [ ] **Step 6: Add readiness probe**

Include `inference_runtime` in `check_all`. Unconfigured local mode returns `LOCAL_MODE`; production failures return `INFERENCE_RUNTIME_UNAVAILABLE`. `build_readiness_service` shares the configured HTTP client behavior without logging the secret.

- [ ] **Step 7: Verify focused GREEN**

```powershell
python -m unittest tests.test_config tests.test_readiness tests.test_inference_deployment tests.test_celery_workflows -v
python -m compileall -q app
```

- [ ] **Step 8: Commit deployment control plane**

```powershell
git add ml-platform/backend/app/config.py ml-platform/backend/app/services/project_access.py ml-platform/backend/app/services/inference_runtime_client.py ml-platform/backend/app/services/inference_deployment.py ml-platform/backend/app/tasks ml-platform/backend/app/services/readiness_service.py ml-platform/backend/app/api/readiness.py ml-platform/backend/tests
git commit -m "feat: operate ONNX inference deployments"
```

---

### Task 6: Expose strict audited model registry APIs

**Files:**
- Create: `ml-platform/backend/app/schemas/model_registry.py`
- Create: `ml-platform/backend/app/api/model_registry.py`
- Modify: `ml-platform/backend/app/main.py`
- Create: `ml-platform/backend/tests/test_api_model_registry.py`
- Modify: `ml-platform/backend/tests/test_api_project_access.py`
- Modify: `ml-platform/backend/tests/test_module_imports.py`

- [ ] **Step 1: Write RED API and role tests**

Cover all routes in the design: lists/details, streamed upload, create logical model, platform/ONNX version registration, approve/reject/archive, deployment create/detail/list/start/stop/predict. Assert `extra="forbid"`, UUID parsing, request limits, hidden outsider 404, visible 403, role matrix, immutable fields, stable domain codes, and audit success/denied/failed redaction.

- [ ] **Step 2: Confirm route RED**

```powershell
python -m unittest tests.test_api_model_registry tests.test_api_project_access tests.test_module_imports -v
```

Expected: route 404 and missing action mappings.

- [ ] **Step 3: Implement strict schemas**

All write schemas inherit a strict base:

```python
class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

class PredictRequest(StrictSchema):
    records: list[dict[str, StrictStr | StrictInt | StrictFloat | StrictBool]] = Field(min_length=1, max_length=100)
```

Use separate schemas for model creation, platform registration, ONNX registration, approval, rejection, deployment creation, and response projections. Never expose internal tokens or storage credentials.

- [ ] **Step 4: Implement router and audit action inventory**

Declare `PROJECT_WRITE_ACTIONS` for every write route. Use new fine-grained permissions and `AuditService.project_action`; keep cross-service saga result events separate from command-acceptance events. Add safe 413 handling for upload/request byte limits. Register the router in `app/main.py`.

- [ ] **Step 5: Verify API GREEN and existing model compatibility**

```powershell
python -m unittest tests.test_api_model_registry tests.test_api_project_access tests.test_api_model_library tests.test_module_imports -v
```

- [ ] **Step 6: Commit APIs**

```powershell
git add ml-platform/backend/app/schemas/model_registry.py ml-platform/backend/app/api/model_registry.py ml-platform/backend/app/main.py ml-platform/backend/tests/test_api_model_registry.py ml-platform/backend/tests/test_api_project_access.py ml-platform/backend/tests/test_module_imports.py
git commit -m "feat: expose audited model registry APIs"
```

---

### Task 7: Deploy and verify the production inference service

**Files:**
- Create: `ml-platform/backend/Dockerfile.inference`
- Modify: `docker-compose.yml`
- Modify: `.github/workflows/ci.yml`
- Create: `ml-platform/backend/tests/test_inference_production_stack.py`
- Modify: `ml-platform/backend/tests/test_ci_workflow.py`

- [ ] **Step 1: Write RED Compose and production integration assertions**

Assert non-root runtime user, no public port, health check, MinIO dependency, internal secret requirement, backend/worker/scheduler environment parity where required, Beat task registration, runtime image build in CI, and production integration gate `RUN_INFERENCE_INTEGRATION=1`.

- [ ] **Step 2: Confirm composition RED**

```powershell
python -m unittest tests.test_ci_workflow tests.test_inference_production_stack -v
docker compose config --quiet
```

Expected: missing service/build/task assertions; production integration skips unless gated.

- [ ] **Step 3: Add non-root runtime image and Compose service**

`Dockerfile.inference` must configure the required Aliyun pip source before installing requirements, create `/var/lib/ml-platform/inference-cache`, grant it to UID/GID 1000, expose only container port 7000, and run one Uvicorn worker for the process-local session cache.

Compose adds `inference-runtime` with `expose: ["7000"]`, health check `/health`, no host port, production environment, cache volume, and MinIO initialization dependency. Backend depends on runtime health. Worker and scheduler receive the runtime URL/secret for reconciliation.

- [ ] **Step 4: Add real production lifecycle test**

The gated test uses PostgreSQL and MinIO to create a project training source, register/approve an ONNX version, start a deployment, predict deterministic named records, restart or clear runtime sessions, run reconciliation, predict again, stop, and verify `DEPLOYMENT_NOT_READY`. It asserts audit events contain no record values, paths, tokens, or exception messages.

- [ ] **Step 5: Extend CI production experiment job**

Build `inference-runtime` with the existing three-attempt cached Compose build loop. Start it with the production stack, set a 32+ character internal secret, run the gated integration test, include runtime logs in redacted failure evidence, and scan for the secret before artifact upload.

- [ ] **Step 6: Verify WSL production path without changing default stack**

Use a unique Compose project/network and cleanup trap. Before any install, run:

```bash
python -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
```

Then build the runtime image, migrate a clean PostgreSQL database to `20260718_08`, run the gated test, inspect health and logs, and remove only isolated resources.

- [ ] **Step 7: Commit production deployment**

```powershell
git add ml-platform/backend/Dockerfile.inference docker-compose.yml .github/workflows/ci.yml ml-platform/backend/tests/test_inference_production_stack.py ml-platform/backend/tests/test_ci_workflow.py
git commit -m "ci: deploy ONNX inference runtime"
```

---

### Task 8: Build typed frontend clients and the model operations page

**Files:**
- Create: `ml-platform/frontend/src/api/modelRegistry.ts`
- Create: `ml-platform/frontend/src/api/modelRegistry.test.ts`
- Replace: `ml-platform/frontend/src/pages/ModelLibraryPage.tsx`
- Create: `ml-platform/frontend/src/pages/ModelLibraryPage.test.tsx`
- Modify: `ml-platform/frontend/src/i18n/index.tsx`

- [ ] **Step 1: Write RED typed-client tests**

Assert exact URLs and payloads for model/version/deployment lists, platform registration, ONNX multipart upload, approval/rejection, create/start/stop, and predict. Normalize only array and `{items}` list responses.

- [ ] **Step 2: Write RED page interaction tests**

Mock typed clients and verify project selection, two tabs, registration flow, version Drawer, role-aware approval, deployment creation, operator start/stop, schema-generated input, direct JSON records, predictions/probabilities/version/duration, empty/loading/denied/runtime-failed states, and accessible icon names.

The main test must select the mocked project, register a mocked platform source, approve returned version 1, create and start the returned deployment, submit `{records: [{current: 1.2, voltage: 3.4}]}`, and assert prediction `1`, probability `0.92`, version `1`, and the typed client call payloads.

- [ ] **Step 3: Confirm frontend RED**

```powershell
npm test -- src/api/modelRegistry.test.ts src/pages/ModelLibraryPage.test.tsx
```

Expected: missing client and old page controls.

- [ ] **Step 4: Implement typed client**

Define exact discriminated unions for source kind, approval status, desired/observed state, feature schema, version, deployment, and prediction. Keep transport normalization inside `modelRegistry.ts`; pages receive typed domain objects.

- [ ] **Step 5: Replace model page**

Use a project filter and compact `Registered models`/`Deployments` tabs. Use tables for scan-heavy state, Drawers for version history and online test, Modal/Form for commands, status Tags, progress only while starting/stopping, and explicit accessible labels for icon buttons. Do not nest cards or preserve the old broken Artifact/list response assumptions.

- [ ] **Step 6: Add symmetric Chinese and English translations**

Add identical `modelRegistry` key trees for tabs, fields, actions, lifecycle states, empty states, stable error messages, validation, and confirmations. Avoid hardcoded visible Chinese/English strings in the new page.

- [ ] **Step 7: Verify frontend GREEN and build**

```powershell
npm test -- src/api/modelRegistry.test.ts src/pages/ModelLibraryPage.test.tsx
npm test
npm run build
```

- [ ] **Step 8: Commit frontend operations**

```powershell
git add ml-platform/frontend/src/api/modelRegistry.ts ml-platform/frontend/src/api/modelRegistry.test.ts ml-platform/frontend/src/pages/ModelLibraryPage.tsx ml-platform/frontend/src/pages/ModelLibraryPage.test.tsx ml-platform/frontend/src/i18n/index.tsx
git commit -m "feat: operate registered models and inference"
```

---

### Task 9: Add browser registration-to-inference acceptance

**Files:**
- Create: `ml-platform/frontend/e2e/model-inference.spec.ts`
- Modify: frontend/backend browser fixtures only when needed for deterministic seeded model data.

- [ ] **Step 1: Write browser RED path**

The test logs in, selects a project, opens Models, registers a seeded trusted platform model, approves version 1, creates and starts a deployment, submits named weld records, verifies prediction and actual version, stops the deployment, and verifies the stopped state. Use role/name selectors and no fixed sleeps.

- [ ] **Step 2: Run Chromium and confirm missing-flow RED**

```powershell
npm run test:e2e -- --project=chromium --grep "model registry inference"
```

- [ ] **Step 3: Add deterministic fixture setup**

Seed through public authenticated APIs or a test-only fixture script run before the browser. Do not add production test bypass routes. The fixture must create a real project-owned training Artifact with platform provenance and deterministic feature schema.

- [ ] **Step 4: Verify Chromium GREEN**

```powershell
npm run test:e2e -- --project=chromium --grep "model registry inference"
npm run test:e2e -- --project=chromium
```

- [ ] **Step 5: Commit browser acceptance**

```powershell
git add ml-platform/frontend/e2e/model-inference.spec.ts ml-platform/frontend/e2e/fixtures
git commit -m "test: cover model inference browser flow"
```

---

### Task 10: Register Week 8, document operations, and complete acceptance

**Files:**
- Modify: `ml-platform/backend/tests/week_manifest.py`
- Create: `docs/delivery/MODEL_REGISTRY_INFERENCE.md`
- Modify: `docs/delivery/PRODUCTION_INFRASTRUCTURE.md`
- Modify: `docs/delivery/USER_GUIDE.md`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `PLATFORM_STATUS.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Run manifest test before registration and observe RED**

```powershell
python -m unittest tests.test_suite_manifest -v
```

Expected: every new Week 8 test module is reported unowned.

- [ ] **Step 2: Register each new module exactly once under Week 8**

Add:

```python
8: [
    "test_model_registry_models",
    "test_onnx_conversion",
    "test_model_registry_service",
    "test_inference_runtime",
    "test_inference_deployment",
    "test_api_model_registry",
    "test_inference_production_stack",
],
```

Keep shared historical tests in their existing week only.

- [ ] **Step 3: Write delivery and operations documentation**

Document roles, version states, source restrictions, conversion errors, upload limits, approval, deployment lifecycle, online inference schema, runtime configuration, readiness, reconciliation, isolated production verification, and Week 9 exclusions. Update infrastructure and user guides without deleting historical content.

- [ ] **Step 4: Run focused and Week 8 suites**

```powershell
python -m unittest tests.test_model_registry_models tests.test_onnx_conversion tests.test_model_registry_service tests.test_inference_runtime tests.test_inference_deployment tests.test_api_model_registry tests.test_ci_workflow tests.test_suite_manifest -v
python run_suite.py --week 8
```

- [ ] **Step 5: Run full local verification**

```powershell
python run_suite.py
python -m compileall -q app
git diff --check
```

```powershell
cd ..\frontend
npm test
npm run build
npm audit
npm run test:e2e -- --project=chromium
```

- [ ] **Step 6: Run clean migration and production verification**

Run Alembic double upgrade/current/check and downgrade coverage against a clean database. In isolated WSL Compose, verify PostgreSQL, MinIO, Redis/Celery, inference-runtime health, conversion, approval, prediction, restart reconciliation, stop, and redacted evidence. Do not alter the user's default Compose stack.

- [ ] **Step 7: Update status and reusable experience**

Record exact test counts, migration head, runtime image evidence, production lifecycle result, remote Run URL, root causes, fixes, prevention measures, and remaining Week 9 work. Keep Week 8 `进行中` until every remote job is green.

- [ ] **Step 8: Commit and push final Week 8 delivery**

```powershell
git add ml-platform/backend/tests/week_manifest.py docs DEVELOPMENT_PLAN.md PLATFORM_STATUS.md
git commit -m "feat: complete week 8 model inference"
git push
```

- [ ] **Step 9: Monitor remote CI to completion**

Require Windows quality, Ubuntu quality, production integration, production experiment/inference integration, and Chromium acceptance to pass. Fix failures with RED/GREEN evidence, append corrections rather than rewriting history, then mark Week 8 complete.

---

## Final Verification Checklist

- [ ] Only validated ONNX versions can be deployed.
- [ ] Platform joblib conversion is provenance-restricted, allowlisted, timed out, and compensated.
- [ ] Registered model versions are immutable and monotonic.
- [ ] owner/editor/operator/viewer behavior matches the confirmed matrix.
- [ ] All writes and denied actions produce redacted Week 7 audit events.
- [ ] Runtime internal routes require the production secret and expose no public host port.
- [ ] Start/stop are idempotent; desired and observed states survive failures and runtime restart.
- [ ] JSON records enforce exact schema, 1 MiB body, 100-record batch, finite values, and 30-second deadline.
- [ ] Predictions identify the exact immutable version and never persist request content.
- [ ] Readiness includes inference runtime with `LOCAL_MODE` and stable production failure codes.
- [ ] Alembic head `20260718_08`, double upgrade/current/check, and downgrade pass.
- [ ] Week 8 manifest owns every new test module exactly once.
- [ ] Full backend, frontend, build, npm audit, Chromium, isolated WSL production, and remote CI are green.
