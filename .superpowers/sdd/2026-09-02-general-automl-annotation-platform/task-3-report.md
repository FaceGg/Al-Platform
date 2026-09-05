# Task 3 Report

## RED
`& .venv\\Scripts\\python.exe -m pytest tests/test_automl_multioutput.py tests/test_automl_catalog.py -q` failed during collection: `ImportError: cannot import name AutoMLContract`.

## Implementation
- Added four persisted task types and request aliases with strict normalization.
- Added AutoMLContract, target validation, multi-output per-target reports, iterative-stratified strategy marker, candidate ranking, and feature-importance aggregation.
- Added TrainingJob `automl_contract` JSON snapshot and Alembic migration `20260904_18`.
- Updated AutoML API request parsing for target_columns and 2-5 folds.
- Removed automatic ModelLibrary writes from AutoML execution; candidate artifacts remain available.

## Verification
- `& .venv\\Scripts\\python.exe -m pytest tests/test_automl_multioutput.py -q` -> 6 passed.
- `& .venv\\Scripts\\python.exe -m py_compile app/services/automl_catalog.py app/services/automl_search.py app/services/automl_execution.py app/api/training.py` -> passed.
- `& .venv\\Scripts\\python.exe -m alembic upgrade head` -> passed.
- `git diff --check` -> passed.

## Known limitations
- Existing `tests/test_automl_catalog.py` requires optional LightGBM in this environment and fails when unavailable.
- Commits: `3c5dbd83df5938177d5f409fadb7e50a242fb465`, `e3aec221a4407407ecddd6e06265c116347c28b1`, `ae801656ce4e7b065c9618bec6336c7e4bc32b21`, `47ed285b25ef51f8ca0f2795270df70f22cb66c2`, `d6bea08957574d0bdac6244d3814c29b7bda576e`.
- Durable worker wiring, complete frontend controls, and full API regression remain for follow-up Task 13/Task 12 integration.

## Fix round 1 (2026-09-04)

- Added 2-fold evaluation support to the shared AutoML evaluation contract.
- Added deterministic joint-label frequency validation for multi-output classification before fold execution.
- Connected the production execution entrypoint to the multi-output search contract so queued `multioutput_*` jobs are no longer rejected at dispatch.
- Updated registry result validation to accept completed candidate `model_artifact_id` values in addition to legacy `model_library_id` values. Artifact-backed candidates are checked for project ownership, `source=automl`, completed training-job lineage, joblib format, and candidate identity; a completed `ModelLibrary` lineage row is created only when registration needs the existing `ModelVersion` foreign-key contract.

### Verification

- `pytest tests/test_automl_multioutput.py -q` -> **8 passed**.
- `pytest tests/test_model_registry_service.py tests/test_api_model_registry.py -q` -> **27 passed, 1 warning, 2 subtests passed**.
- `py_compile app/services/model_registry.py app/services/automl_search.py app/services/automl_execution.py` -> passed.
- `git diff --check` -> passed.

### Remaining limitations

- Full Task 3 compliance is still not established: real iterative-stratified fold assignments, fold-local preprocessing, per-target artifact/prediction persistence, search strength/time-budget/class-weight controls, durable idempotency/cancellation/recovery, and complete AUC ranking tiers remain open for later fix rounds.
- The worker multi-output branch currently records contract reports but does not yet persist a trained multi-output candidate artifact; this remains a release blocker and Task 3 stays `in_progress`.
- Follow-up regression: the existing AutoML trust predicate also required `model_library_id` in job metrics after artifact-only persistence. It now accepts the candidate `model_artifact_id` when it matches the validated source artifact.
- `pytest tests/test_model_registry_service.py -k artifact_only -q` -> **1 passed**; combined AutoML/registry/API suite -> **36 passed, 1 warning, 2 subtests passed**.

## Pause checkpoint (2026-09-04)

- Task 3 remains `in_progress`; the current round is published as a partial implementation checkpoint, not a completion claim.
- User requested to pause development after documentation and GitHub publication. Do not begin Task 4. On resume, start with a scoped re-review and RED/GREEN coverage for the remaining limitations above, then update the plan only after production-path evidence is available.

## Fix round 2 (2026-09-05)

### Changed files

- `ml-platform/backend/app/services/automl_execution.py`: added a real multi-output execution path that validates all targets, excludes every target from default features, trains a deterministic `MultiOutputClassifier`/`MultiOutputRegressor`, persists a joblib candidate artifact, and stores per-target predictions/reports, aggregate metrics, input contract, preprocessing, feature/target schemas, and artifact identity. Candidate metadata writes both `best_candidate` and `best_algorithm`.
- `ml-platform/backend/app/services/automl_search.py`: tightened regression/classification target dtype checks and added four search-strength/four time-budget contract normalization with class-weight validation.
- `ml-platform/backend/app/services/model_registry.py`: accepts either canonical candidate metadata key while still requiring artifact/job/algorithm identity to match.
- `ml-platform/backend/app/api/training.py`: accepts multi-output target exclusion and persists search strength/class-weight controls; allows route-level business validation for fold errors.
- `ml-platform/backend/tests/test_automl_multioutput.py`: added RED/GREEN coverage for target dtype, all-target feature exclusion, decision-function AUC fallback, and search controls.
- `ml-platform/backend/tests/test_automl_tracking.py`: added a real `execute_automl_job` multi-output regression and aligned artifact-only expectations.

### RED

- `& .venv\\Scripts\\python.exe -m pytest tests/test_automl_tracking.py -k multioutput_execution_persists_candidate_artifact_and_reports -q` -> **1 failed** because the worker marked the multi-output job complete with `model_artifact_id=None`.
- `& .venv\\Scripts\\python.exe -m pytest tests/test_automl_multioutput.py -q` -> **2 failed** for missing all-target feature exclusion and strict dtype contracts.

### GREEN

- `& .venv\\Scripts\\python.exe -m pytest tests/test_automl_multioutput.py tests/test_automl_tracking.py -q` -> **46 passed, 41 warnings, 10 subtests passed**.
- `& .venv\\Scripts\\python.exe -m py_compile app/services/automl_search.py app/services/automl_execution.py app/services/model_registry.py app/api/training.py` -> passed.
- `git diff --check` -> passed.

### Remaining concerns

- Durable request replay/idempotency, cancellation polling, lease/recovery wiring, and complete frontend controls remain outside this round.
- Multi-output search still uses the deterministic random-forest candidate rather than the full family search catalog; downstream durable worker and richer search orchestration remain open.
- Existing historical tests that assert pre-fix ModelLibrary rows or reject 2-fold CV were updated to the current artifact-only/2-fold contract; optional LightGBM and browser/remote CI gates remain environment-dependent.

## Fix round 3 (2026-09-05)

### Scoped re-review

- Current SHA: `7b4797d`. Focused AutoML/registry/API suites: **78 passed**, 41 warnings, 12 subtests; `py_compile` and `git diff --check` passed.
- Remaining Important gaps: production AUC aggregation/tiering is not fully robust (first usable fold, binary score indexing and report fallback); multi-output execution does not enforce the time budget or full search method/trial controls; request idempotency replay, cancellation polling and durable lease/recovery are not connected. Joint-label `StratifiedKFold` is deterministic shared splitting but not a true iterative-stratification implementation.
- Task 3 remains `in_progress`; Task 4 remains `planned`.

### Changed behavior

- Added deterministic joint-label fold assignment helper for multi-output classification and wired it into the search evaluator so all targets share one fold plan.
- Added explicit complete/incomplete AUC tiering and actual `decision_function` fallback in the multi-output worker path.
- Multi-output evaluation now persists cross-validated predictions and per-target reports; search strength controls estimator size (`light`/`balanced`/`thorough`/`maximum`) and class-weight is passed to the classifier.
- API validation now normalizes search strength, one of four supported time budgets, and the class-weight boolean before queueing.

### RED/GREEN evidence

- RED: new fold/tier imports failed before implementation; regression worker test exposed missing `prediction_source`.
- GREEN: `pytest tests/test_automl_multioutput.py tests/test_automl_tracking.py tests/test_model_registry_service.py tests/test_api_model_registry.py -q` -> **78 passed, 41 warnings, 12 subtests passed**.
- `py_compile` and `git diff --check` passed after the round.

### Remaining concerns

- Request replay/idempotency headers, cancellation polling, durable lease/recovery and full frontend wiring remain open Task 3/Task 13 integration work.
- Optional LightGBM and browser/remote CI gates were not run in this environment.
