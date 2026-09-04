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

## Review Fix Round 2

- Dataset-import uploads now stream bounded chunks to staging and remove partial staging files on size failure; the request-specific `ParseOptions.max_file_bytes` is applied before parsing. The original upload filename is preserved on the immutable original artifact.
- The parser now uses content sniffing when `source_format` is omitted, rejects only explicit format/content conflicts, checks compressed container expanded size, supports controlled CSV encoding/delimiter/header and Excel worksheet options, and rejects incompatible JSON scalar types across records with `DATA_PARSE_INCOMPATIBLE_COLUMN_TYPE`.
- Every structured canonical entry (`dataset-imports`, legacy upload/batch, batch-upload, ZIP members) now freezes a DatasetVersion; non-structured legacy artifacts remain artifact-only by compatibility boundary. The report does not claim an isolated parsing worker: that process/isolation boundary remains Task 13 work.
- Added a unique `(project_id, version)` index and `DATA_VERSION_CONFLICT` retry/fail-closed allocation behavior. Existing database upgrades use the additive `20260905_17` migration.
- Cleanup deletion failures now raise `DATA_CLEANUP_FAILED` rather than being silently discarded. Malformed dataset-version IDs return controlled 404.
- RED/GREEN coverage added for JSON cross-record type conflict, content sniffing without an extension, bounded staging, cleanup failures, version-pair uniqueness, malformed version ID, and legacy upload version freezing.
- Verification: `pytest tests/test_dataset_import_contract.py tests/test_genericization_contract.py tests/test_data_version_migration_graph.py -q` -> 47 passed; `pytest tests/test_database_migrations.py tests/test_artifact_storage_integration.py tests/test_api_datasets.py -q` -> 18 passed; `alembic upgrade head` and `alembic check` passed; `py_compile` and `git diff --check` passed. Existing Starlette/JWT key-length warnings remain test-environment warnings.

## Review Fix Round 3

- API rollback cleanup is now fail-closed: storage deletion failures raise `DATA_CLEANUP_FAILED` while preserving the triggering exception as the cause/context. Regression coverage exercises the batch-upload API rollback path.
- `DELETE /api/datasets/{dataset_id}` refuses artifacts referenced by `DatasetVersion.original_artifact_id` or `normalized_artifact_id` with HTTP 409 and `DATA_IMMUTABLE_ARTIFACT`; unreferenced legacy artifacts remain deletable. Authenticated TestClient coverage verifies both behavior and preservation of referenced rows/content.
- ZIP import validates all member names and declared expanded sizes before extraction, then applies streaming per-member and cumulative byte guards. Unsafe paths return `DATA_PARSE_UNSAFE_PATH`; member/cumulative overages return `DATA_LIMIT_FILE_BYTES` or `DATA_LIMIT_DECOMPRESSED_BYTES`; rejected imports leave no artifact/version rows.
- RED/GREEN evidence: focused Round 3 tests initially failed 3 cases; after implementation, `pytest tests/test_dataset_import_contract.py -k "rollback_cleanup_failure or zip_handler" -q` -> 3 passed; `pytest tests/test_api_datasets.py -q` -> 15 passed; Task 2 focused suites -> 51 passed and 19 passed respectively. `compileall` and `git diff --check` passed. Existing Starlette/JWT warnings remain.

## Review Fix Round 4

- Corrected partial-success compensation for `batch-upload` and ZIP imports: structured entries are committed immutable versions, so their artifact URIs are no longer added to outer rollback cleanup. Only unversioned legacy artifacts are eligible for outer storage compensation; committed versions and both referenced artifacts remain durable and consistent when a later entry fails.
- Added regressions that freeze the first structured entry, force the second entry to fail, and assert the committed `DatasetVersion` plus original/normalized artifacts and storage objects remain present for both batch and ZIP handlers.
- RED/GREEN evidence: `pytest tests/test_dataset_import_contract.py -k "committed_version_artifacts" -q` initially failed 2 cases; after implementation it passed `2 passed`. Full focused suites passed `53 passed` and `19 passed` respectively; `compileall` and `git diff --check` passed.
