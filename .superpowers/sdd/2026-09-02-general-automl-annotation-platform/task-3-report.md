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
