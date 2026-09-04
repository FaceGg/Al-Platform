# Task 2 Report

Date: 2026-09-04
Status: passed locally; Task 3 and Task 4 remain planned.

## Scope

- Added safe flat-table parsing for CSV, Excel, Parquet, JSON and XML, including duplicate-key, unsafe XML/path, scalar, size, row, column, depth, field and elapsed-time boundaries.
- Added immutable data version, schema-column, sample and import records, deterministic sample IDs, hash/parse-contract persistence, original plus normalized artifacts, and failure compensation.
- Added dataset-version import/query endpoints and input-contract validation for missing columns, nulls, dtypes, finite floats, ranges and sample IDs.
- Added additive migration, SQLite compatibility support, dependency declarations and Week 3 test-manifest registration.

## TDD Evidence

- RED: `.\.venv\Scripts\python.exe -m pytest tests/test_dataset_import_contract.py -q` initially failed collection with `ModuleNotFoundError: app.models.data_version`.
- Additional boundary tests initially found missing original-artifact compensation on normalized-artifact failure; after the fix, `.\.venv\Scripts\python.exe -m pytest tests/test_dataset_import_contract.py -q` passed `19 passed`.
- GREEN: `.\.venv\Scripts\python.exe -m pytest tests/test_database_migrations.py tests/test_artifact_storage_integration.py -q` passed `4 passed`.
- Broader focused guard: `tests/test_dataset_import_contract.py tests/test_database_migrations.py tests/test_artifact_storage_integration.py tests/test_genericization_contract.py tests/test_suite_manifest.py -q` passed `46 passed`, with one existing Starlette deprecation warning and two subtests.
- `.\.venv\Scripts\python.exe -m alembic upgrade head`, `py_compile`, and `git diff --check` passed.

## Review And Commit

- Self-review checked parser fail-closed paths, artifact compensation ordering, immutable child rows, migration chain and manifest registration.
- Changed: Task 2 models, schemas, parser/input services, datasets API, Alembic/environment compatibility, requirements, focused tests, test manifest, plan/experience/SDD records.
- Commit history: `feat(data): add immutable dataset import versions`, followed by the final review-fix commit (`fix(data): close task2 import review gaps`). Verify the final SHA with `git rev-parse HEAD`.

## Concerns

- The focused API tests call the route handler with explicit dependencies and local storage; authenticated HTTP E2E/browser and remote CI were not run.
- Existing `README.md` remains excluded as unrelated local work.

## Review Fix Round 1

- Corrected the Alembic chain to `20260829_14 -> 20260902_15 -> 20260903_15 -> 20260904_16`; the Task 2 migration now creates the project index declared by the ORM, eliminating `alembic check` drift.
- Import API now uses `project_uuid` plus `require_project_access(..., "resource.create")`, records `dataset.import` through the project audit context, and maps malformed project IDs to controlled 404 responses.
- Parser validates content-derived format against the declared format and returns `DATA_FORMAT_MISMATCH` on disagreement.
- Dataset versions increment monotonically per project; parse contracts persist identity-preserving `field_mapping` and `row_locator` metadata.
- Added regressions for migration ordering, API permission/audit/error behavior, content-format mismatch, per-project version increments, and mapping/locator persistence.
- Verification: `pytest tests/test_dataset_import_contract.py tests/test_genericization_contract.py tests/test_data_version_migration_graph.py -q` -> 41 passed; `alembic upgrade head` -> passed; `alembic check` -> `No new upgrade operations detected`; `pytest tests/test_database_migrations.py tests/test_artifact_storage_integration.py tests/test_api_datasets.py -q` -> 18 passed; `py_compile` and `git diff --check` -> passed.
- Remaining concerns unchanged: no full backend suite, browser E2E, or remote CI evidence.
