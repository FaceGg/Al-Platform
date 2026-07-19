# Week 8 Model Registry and Basic Inference Design

## 1. Goal

Week 8 delivers a project-scoped model registry and a basic ONNX inference service. Users can convert trusted platform training outputs into immutable ONNX model versions, approve versions, create and operate deployments, inspect health, and test predictions with schema-validated JSON records.

The design extends Week 7 project roles and audit boundaries. It deliberately stops before Week 9 production inference features such as multi-replica routing, rolling upgrades, rollback automation, public API keys, rate limits, traffic splitting, and production telemetry.

## 2. Confirmed Decisions

- ONNX is the only deployable model format.
- Trusted platform-generated joblib artifacts are converted during registration.
- Users may also register an already converted ONNX artifact with an explicit schema manifest.
- A conversion or ONNX validation failure rejects registration and leaves no model version.
- `owner` and `editor` may register, approve, reject, and create deployments.
- `operator` may start, stop, and invoke deployments.
- `viewer` has read-only access.
- Inference accepts named JSON records, not positional arrays or CSV uploads.
- The platform database is the registry control-plane source of truth.
- A dedicated ONNX Runtime service is the inference data plane.

## 3. System Boundaries

### 3.1 Existing ModelLibrary

`ModelLibrary` remains the training-result catalog. Training and AutoML jobs continue to create joblib model artifacts and ModelLibrary rows. Those rows are source candidates, not deployable registry versions.

This avoids changing checkpoint and resume behavior in Week 8. It also prevents mutable training status fields from becoming registry lifecycle fields.

### 3.2 Registry Control Plane

The backend owns:

- project authorization and hidden-resource behavior;
- registered model and immutable version metadata;
- approval and archive state;
- deployment desired and observed state;
- audit events;
- conversion orchestration and storage compensation;
- runtime health and reconciliation;
- the public authenticated API.

### 3.3 Inference Data Plane

The `inference-runtime` service owns:

- loading validated ONNX artifacts;
- maintaining the in-process deployment cache;
- unloading models;
- executing schema-validated tensors with ONNX Runtime;
- reporting internal deployment health.

The runtime has no public host port in production composition. Internal endpoints require a production-only shared secret in `X-Inference-Internal-Token`, compared in constant time. It receives only deployment IDs, controlled Artifact URIs, model schemas, and output metadata produced by the backend.

## 4. Persistence Model

### 4.1 RegisteredModel

One row identifies a logical model within a project.

- `id`: UUID primary key.
- `project_id`: required project foreign key with cascade delete.
- `name`: normalized display name; unique with `project_id`.
- `description`: optional text.
- `created_by_id`: nullable historical actor reference using `SET NULL`.
- `created_at`, `updated_at`: timestamps.

Deleting a registered model is excluded from Week 8. A model is archived so version and audit history remain queryable.

### 4.2 ModelVersion

Each row is immutable after registration, except for lifecycle timestamps and approval state.

- `id`: UUID primary key.
- `registered_model_id`: required model foreign key.
- `version_number`: monotonically increasing integer, unique per registered model.
- `source_kind`: `platform_joblib` or `onnx_artifact`.
- `source_model_library_id`: required for platform joblib sources.
- `source_artifact_id`: required source Artifact.
- `onnx_artifact_id`: required generated or uploaded ONNX Artifact.
- `framework`, `algorithm`: frozen source descriptors.
- `feature_schema`, `output_schema`: validated JSON schemas.
- `metrics`: frozen registration snapshot.
- `conversion_metadata`: converter name/version, ONNX opset, input/output names, SHA-256.
- `approval_status`: `pending`, `approved`, `rejected`, or `archived`.
- `approval_comment`: bounded plain text.
- `approved_by_id`, `approved_at`, `created_by_id`, `created_at`.

Metrics, schemas, Artifact references, and version identity cannot be updated through public APIs. Approval changes are explicit audited actions. An archived version cannot return to an active state.

### 4.3 InferenceDeployment

One deployment binds a stable project-local name to one exact approved version.

- `id`: UUID primary key.
- `project_id`: required project foreign key.
- `name`: unique with `project_id`.
- `model_version_id`: immutable exact version reference.
- `desired_state`: `stopped` or `running`.
- `observed_state`: `stopped`, `starting`, `running`, `stopping`, or `failed`.
- `last_error_code`: stable code only.
- `last_checked_at`, `started_at`, `stopped_at`, `created_at`, `updated_at`.
- `created_by_id`: nullable historical actor reference.

Changing a deployment to another version is excluded from Week 8. Users create another deployment; Week 9 will add controlled version rollout and rollback.

## 5. Registration and Conversion

### 5.1 Platform Joblib Source

The backend accepts only a ModelLibrary row that:

- belongs to the requested project;
- references a project-owned model Artifact;
- was produced by a platform training or AutoML job;
- contains a supported allowlisted estimator package;
- includes a complete ordered feature schema and target/output schema.

The backend materializes the Artifact and invokes a dedicated conversion subprocess. The subprocess has a 120-second wall timeout, a bounded memory limit where supported, a private temporary directory, and no caller-controlled import path. Initial converters cover platform-generated scikit-learn estimators supported by `skl2onnx`. Unsupported estimators fail with `MODEL_CONVERSION_UNSUPPORTED`.

### 5.2 Existing ONNX Source

An owner or editor may stream-upload an ONNX file of at most 256 MiB into a project-owned model Artifact, then register that Artifact. Upload computes size and SHA-256 while streaming and removes storage content if metadata persistence fails. The registration request must supply feature and output schemas. The backend does not infer business feature names from arbitrary ONNX input tensors.

### 5.3 Validation and Compensation

Every converted or supplied ONNX model passes:

1. `.onnx` extension and 256 MiB size validation;
2. `onnx.checker.check_model`;
3. ONNX Runtime session creation;
4. input/output name and shape agreement with the manifest;
5. a synthetic one-record smoke inference using schema-compatible values.

The backend stores a separate ONNX Artifact. Artifact storage succeeds before the registry transaction commits. If the version transaction fails, the stored object is deleted. If conversion or validation fails, temporary files are deleted and no version row is created.

Concurrent registration uses a database uniqueness constraint and locked next-version allocation so each registered model receives one monotonic version number.

## 6. Approval and Permissions

| Operation | owner | editor | operator | viewer |
|---|---:|---:|---:|---:|
| Read model/version/deployment | yes | yes | yes | yes |
| Register model version | yes | yes | no | no |
| Approve/reject/archive version | yes | yes | no | no |
| Create deployment | yes | yes | no | no |
| Start/stop deployment | yes | yes | yes | no |
| Invoke online inference | yes | yes | yes | no |

Only an `approved` version can be used to create a deployment. Rejection requires a comment. Approval and rejection are idempotent only when the requested state already matches; conflicting terminal changes return a stable lifecycle error.

All project writes use the Week 7 audited transaction boundary. Registration, approval, rejection, archive, deployment creation, start, stop, and reconciliation failures use frozen audit action names. Audit changes include IDs, state, version number, and stable error codes. They exclude model bytes, raw records, predictions, credentials, storage paths, and exception text.

## 7. Deployment Lifecycle

Creating a deployment writes `desired_state=stopped` and `observed_state=stopped`.

Starting a deployment is a small saga:

1. authorize and audit command acceptance;
2. persist `desired_state=running`, `observed_state=starting`;
3. send the controlled load specification to the runtime;
4. persist `observed_state=running` on success;
5. persist `observed_state=failed` and a stable error code on failure.

Stopping mirrors the flow and is idempotent. Runtime unload of an already absent deployment succeeds.

A periodic Celery reconciliation task compares runtime state with database desired state. It reloads desired-running deployments after runtime restart, unloads undesired runtime entries, refreshes `last_checked_at`, and records stable failures. It does not change the desired state without a user action.

## 8. Inference Contract

The public request is:

```json
{
  "records": [
    {"feature_a": 1.2, "feature_b": 3.4}
  ]
}
```

Validation rules:

- request body is at most 1 MiB;
- one request contains 1 to 100 records;
- every record contains exactly the required named features;
- numeric, boolean, and string values follow the frozen feature schema;
- null, NaN, infinity, unknown fields, and unsafe coercions are rejected;
- values are ordered according to the frozen schema before tensor creation.

The response is:

```json
{
  "deployment_id": "uuid",
  "model_version_id": "uuid",
  "version_number": 1,
  "predictions": [1],
  "probabilities": [[0.08, 0.92]],
  "duration_ms": 4.6
}
```

`probabilities` is omitted when the ONNX model has no probability output. Runtime prediction has a 30-second deadline. The API does not persist input records or prediction values in Week 8.

## 9. API Surface

Public backend routes use strict Pydantic schemas with unknown fields rejected.

- `GET /api/projects/{project_id}/registered-models`
- `POST /api/projects/{project_id}/registered-models`
- `POST /api/projects/{project_id}/model-artifacts` for streamed ONNX upload
- `GET /api/registered-models/{model_id}`
- `POST /api/registered-models/{model_id}/versions`
- `GET /api/registered-models/{model_id}/versions`
- `GET /api/model-versions/{version_id}`
- `POST /api/model-versions/{version_id}/approve`
- `POST /api/model-versions/{version_id}/reject`
- `POST /api/model-versions/{version_id}/archive`
- `GET /api/projects/{project_id}/inference-deployments`
- `POST /api/projects/{project_id}/inference-deployments`
- `GET /api/inference-deployments/{deployment_id}`
- `POST /api/inference-deployments/{deployment_id}/start`
- `POST /api/inference-deployments/{deployment_id}/stop`
- `POST /api/inference-deployments/{deployment_id}/predict`

Indirect ID routes resolve project membership before returning resource details. Outsiders receive hidden 404 responses; visible members without permission receive the existing project permission 403 response.

## 10. Error Handling

Stable domain codes include:

- `MODEL_CONVERSION_UNSUPPORTED`
- `MODEL_CONVERSION_FAILED`
- `MODEL_CONVERSION_TIMEOUT`
- `ONNX_INVALID`
- `MODEL_SCHEMA_INVALID`
- `MODEL_VERSION_IMMUTABLE`
- `MODEL_NOT_APPROVED`
- `MODEL_VERSION_STATE_CONFLICT`
- `DEPLOYMENT_NOT_READY`
- `INFERENCE_RUNTIME_UNAVAILABLE`
- `INFERENCE_SCHEMA_MISMATCH`
- `INFERENCE_LIMIT_EXCEEDED`
- `INFERENCE_TIMEOUT`

API responses contain a stable code and safe message. Runtime and converter exception text remains in redacted structured server logs, never in API responses, deployment rows, or audit changes.

## 11. Runtime and Readiness

The backend image gains pinned `onnx`, `onnxruntime`, and `skl2onnx` dependencies. Dependency installation continues to configure `https://mirrors.aliyun.com/pypi/simple/` first.

Compose adds a non-root `inference-runtime` service with a health check and controlled temporary/model-cache volumes. Backend, worker, and scheduler receive the internal runtime URL and shared secret. Production configuration requires both values. The runtime does not mount the Docker socket.

`/api/ready` adds an `inference_runtime` probe. Local mode without a configured runtime returns `LOCAL_MODE`. Production unavailability returns `INFERENCE_RUNTIME_UNAVAILABLE` without exposing URLs or credentials.

## 12. Frontend

`/models` becomes a project-scoped operations page with two tabs:

- `Registered models`: model name, latest version, approval state, metrics, deployment summary, registration action, and a detail Drawer with immutable version history.
- `Deployments`: desired/observed state, exact version, health, last stable error, last check time, start/stop actions, and online testing.

The online test Drawer generates fields from the feature schema and also permits direct JSON records editing. Results show predictions, optional probabilities, duration, and the actual version used.

Typed frontend API modules replace page-local untyped calls. All actions expose loading, empty, success, denied, validation, runtime-unavailable, and failed states. Icon buttons have explicit accessible names. Chinese and English translation trees stay structurally identical.

## 13. Verification

### 13.1 Automated Coverage

- converter allowlist, timeout, invalid ONNX, schema mismatch, and storage compensation;
- ORM constraints, monotonic versions, immutable fields, lifecycle transitions, and migration downgrade;
- owner/editor/operator/viewer permissions, hidden outsiders, and redacted audit events;
- runtime load/unload idempotency, prediction types, request limits, timeouts, and restart reconciliation;
- API success and stable error contracts;
- readiness local/production behavior;
- typed frontend clients and operations-page interactions;
- Week 8 manifest ownership.

### 13.2 Production Acceptance

An isolated WSL/CI production composition uses PostgreSQL, MinIO, Redis/Celery, and the inference runtime to:

1. train or seed a trusted platform model;
2. convert and validate an ONNX version;
3. approve it;
4. create and start a deployment;
5. submit named JSON records;
6. verify deterministic predictions and version identity;
7. restart the runtime and verify reconciliation reload;
8. stop the deployment and verify inference rejection.

Final gates are the Week 8 suite, full backend runner, frontend tests and build, Alembic double upgrade/current/check and downgrade, Chromium registration-to-inference acceptance, npm audit, Docker production integration, and all remote CI jobs.

## 14. Out of Scope

- public inference API keys and anonymous inference;
- multi-replica deployments and load balancing;
- rolling or canary upgrades, traffic splitting, and rollback automation;
- autoscaling, rate limiting, quotas, batching queues, and GPU execution;
- prediction logging, drift monitoring, latency dashboards, and service log UI;
- arbitrary pickle conversion, caller-controlled Python imports, or custom conversion code;
- changing training checkpoints from joblib to ONNX.

These belong to Week 9 or later production inference work.
