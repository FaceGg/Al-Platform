# Task 1 report: genericization migration boundary

Date: 2026-09-03
Worktree: `E:\codex_workspace\agent_spot_welding\.worktrees\general-automl-annotation-20260902`

## Scope

Implemented the minimum transition-safe boundary requested by Task 1:

- Generic annotation task persistence with UUID references and snapshots.
- `GET/POST /api/annotation-tasks` and `POST /api/automl-tasks`.
- Structured `410 GENERIC_API_REQUIRED` for the legacy spot-weld run creation path.
- One-way, idempotent `migrate_legacy_quality_run` adapter that preserves legacy rows and copies samples, revisions, and snapshots into an auditable JSON snapshot.
- Initial genericization inventory entries.
- Week manifest registration for the new contract test module.

## Files changed

- `ml-platform/backend/app/models/platform_models.py`
- `ml-platform/backend/app/models/__init__.py`
- `ml-platform/backend/app/services/annotation_tasks.py`
- `ml-platform/backend/app/api/generic_tasks.py`
- `ml-platform/backend/app/main.py`
- `ml-platform/backend/tests/test_genericization_contract.py`
- `ml-platform/backend/tests/week_manifest.py`
- `ml-platform/docs/migrations/2026-09-02-genericization-inventory.md`
- `DEVELOPMENT_PLAN.md`

`README.md` was not edited, staged, or committed.

## RED evidence

Command:

```text
Set-Location ml-platform/backend
py -3.14 -m unittest tests.test_genericization_contract -v
```

Result: failed during test-module import with `ModuleNotFoundError: No module named 'fastapi'`. This is the expected pre-implementation/environment failure; the prescribed Python environment does not currently contain backend dependencies. No production implementation existed when the first RED run was executed.

## Implementation

`GenericAnnotationTask` deliberately stores `dataset_version_id` and `label_schema_id` as UUID references rather than introducing formal data-version or label-schema tables ahead of Tasks 2 and 4. The migration adapter is idempotent through `source_legacy_id`, leaves legacy rows untouched, and retains sample values, labels, revisions, and snapshots for later checksum and row-count validation.

The generic routes enforce project ownership, validate UUID references and mode/scope values, and return a stable serialized contract. The legacy write route is registered before the old spot-weld router and raises a structured 410 response with `GENERIC_API_REQUIRED`.

## GREEN evidence

Passed:

```text
py -3.14 -m py_compile ml-platform/backend/app/models/platform_models.py ml-platform/backend/app/services/annotation_tasks.py ml-platform/backend/app/api/generic_tasks.py ml-platform/backend/app/main.py
git diff --check
```

Not passed because dependencies are unavailable:

```text
py -3.14 -m unittest tests.test_genericization_contract tests.test_suite_manifest -v
```

The focused contract import failed on missing `fastapi`; the manifest subprocess checks also failed on missing `fastapi` and `httpx`. The source scan could not be run from the backend working directory with repository-relative paths and must be rerun from the repository root in a dependency-ready environment.

## Concerns and remaining work

- Install the pinned backend dependencies before claiming Task 1 GREEN or running runtime API checks.
- Run the full genericization source scan and classify remaining industry references as explicitly marked adapters or downstream migration work.
- Add real dataset-version and label-schema foreign keys, row-count/sample-id/checksum validation, and revision tables in Tasks 2 and 4.
- Replace production frontend navigation and i18n in Task 12; this task intentionally leaves historical UI adapters intact.
- Review route-level authorization and migration ownership in an integration-enabled test environment.

Task status remains `in_progress`, not `passed`, until focused tests and manifest verification execute successfully.

## Scoped re-review of fix round (2026-09-03)

Compared fix commits `8bb8519` and `28c8adc` against the prior review findings and the Task 1 brief.

### Prior finding verdicts

- **Production Alembic schema: ADDRESSED.** `20260903_15_generic_annotation_tasks.py` adds the table, constraints and indexes, and the revision is chained from `20260829_14` ([migration](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/alembic/versions/20260903_15_generic_annotation_tasks.py:1-52)). Runtime migration execution was not verified because backend dependencies remain unavailable.
- **Pre-write authorization / no side effect: ADDRESSED at the HTTP endpoint.** The migration endpoint loads the legacy run and checks creator and project ownership before calling the mutating adapter ([generic_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/api/generic_tasks.py:158-176)). The service itself still accepts only `run_id` and has no authorization parameter ([annotation_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/services/annotation_tasks.py:21-37)); direct internal callers must remain trusted.
- **Migration metadata / integrity checks: NOT ADDRESSED.** Metadata coverage and deterministic checksum were added ([annotation_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/services/annotation_tasks.py:49-121), but the count and ID checks compare the source query result with the list built directly from that same result ([annotation_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/services/annotation_tasks.py:122-125)). There is no independent source-vs-target row/sample/revision/snapshot validation, no persisted generic dataset-version or label-schema records, and no source checksum comparison before migration completion.
- **Concurrent idempotency: ADDRESSED for the current unique-key races.** Both generic creation and legacy migration roll back on `IntegrityError` and reload the winner ([generic_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/api/generic_tasks.py:117-127), [annotation_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/services/annotation_tasks.py:137-147)). This remains unverified at runtime because the focused suite cannot import FastAPI.
- **Typed request / header / error contracts: PARTIALLY ADDRESSED; overall NOT ADDRESSED.** Generic create endpoints now use `GenericTaskCreate` and require the two headers ([generic_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/api/generic_tasks.py:23-30,79-115)). However, `sample_scope` and `label_snapshot` remain unconstrained arbitrary dictionaries, the deprecated write route has no auth/correlation-header handling and emits a legacy-shaped error without `request_id` ([generic_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/api/generic_tasks.py:145-155), and idempotency keys are not bound to a migration operation/result.
- **Exact 410 / missing-run behavior: ADDRESSED at the HTTP endpoint.** The deprecated route now returns exactly 410 with `GENERIC_API_REQUIRED` ([generic_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/api/generic_tasks.py:145-155)); missing migration runs return structured 404s ([generic_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/api/generic_tasks.py:169-173)). The direct adapter still raises `ValueError` for a missing run ([annotation_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/services/annotation_tasks.py:35-37).
- **Plan-mandated file-boundary / de-industry changes: NOT ADDRESSED.** The fix diff still does not modify the listed spot-weld service/features/tasks/models or frontend `App.tsx`, annotation pages, API client and i18n. The inventory explicitly records these as remaining work ([2026-09-02-genericization-inventory.md](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/docs/migrations/2026-09-02-genericization-inventory.md:29-31)).

### New Critical/Important issues in the fix diff

**Critical**

- None newly introduced by the fix round. The production table migration and endpoint authorization ordering remove the prior deployment and side-effect blockers, subject to runtime migration/test verification.

**Important**

- The legacy 410 handler is a write route that bypasses the global write contract: it has no `get_current_user`, `X-Request-ID`, or `Idempotency-Key` dependencies and returns no request ID in its detail ([generic_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/api/generic_tasks.py:145-155)). Preserve the exact 410/code while applying the common request/error envelope and write-header policy, or explicitly exempt this terminal deprecation route in the contract.
- The migration remains a snapshot-only compatibility record: `dataset_version_id` still points at the legacy artifact UUID and `label_schema_id` is a deterministic synthetic UUID, with no target tables or foreign keys ([annotation_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/services/annotation_tasks.py:126-136); [platform_models.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/models/platform_models.py:67-79)). This does not satisfy the Task 1 migration step's generic dataset-version/schema/revision boundary and must remain blocked until the formal records or an explicitly accepted transitional contract are implemented.

### Re-review quality verdict

**Needs fixes.** The fix round addresses the production migration, endpoint authorization ordering, exact 410 response, and current idempotency race handling. It does not establish independent migration integrity checks or the formal generic data/schema boundary, leaves the required production frontend and adapter file changes undone, and still has a write-contract inconsistency on the deprecated route. Focused tests and manifest verification remain unexecuted due missing backend dependencies, so no GREEN or approval claim is justified.

### Additional fix-round risk

- **Important:** The new Alembic upgrade is only additive when the table is absent. If `generic_annotation_tasks` already exists (for example from a development `Base.metadata.create_all()` run using the earlier model), the `if` branch skips all column/constraint additions and the migration then only creates indexes ([20260903_15_generic_annotation_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/alembic/versions/20260903_15_generic_annotation_tasks.py:13-42)). That pre-existing table can lack `idempotency_key` and the named unique constraints required by the current ORM/API. Inspect and alter existing columns/constraints idempotently, and add a legacy-table upgrade test.

### Test execution follow-up (2026-09-03)

After dependencies became available, the focused suite reached runtime. The failure in `test_legacy_migration_authorization_and_missing_run` is a **test-isolation defect**, not evidence of an unauthorized production write: the test uses one class-scoped database, while earlier tests intentionally create `GenericAnnotationTask` rows; its global `count() == 0` assertion therefore fails at [test_genericization_contract.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/tests/test_genericization_contract.py:171-186) even though the endpoint rejects the other user before invoking the mutating adapter at [generic_tasks.py](E:/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/ml-platform/backend/app/api/generic_tasks.py:169-175). The test should capture the count before the request or assert absence of a task with `source_legacy_id == str(run.id)`; production behavior remains covered by the pre-write authorization ordering.

## Fix round 2 (2026-09-03)

- Corrected migration authorization isolation, added partial-table Alembic upgrade coverage, unified the deprecated 410 request/error contract, and added independent source-versus-snapshot integrity metadata with deterministic checksum.
- Marked legacy spot-weld model/service/feature/task modules as `LEGACY_ADAPTER_ONLY`; frontend production navigation/API replacement remains scoped to Task 12 and is explicitly documented as unfinished.
- RED command before fixes: `py -3.14 -m unittest tests.test_genericization_contract -v` failed at import because `fastapi` is unavailable.
- Post-fix `py_compile` and `git diff --check` passed. Runtime focused tests and Alembic execution remain pending until backend dependencies are installed.
