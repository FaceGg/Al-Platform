# SDD ledger — plan: ml-platform/docs/superpowers/plans/2026-09-02-general-automl-annotation-platform.md

## Context

- Worktree: `E:\codex_workspace\agent_spot_welding\.worktrees\general-automl-annotation-20260902`
- Branch: `general-automl-annotation-20260902`
- Base before Task 1: `671b815a9fe0b91bdc03f64b13ea12beb76c3039`
- User-local `README.md` is intentionally dirty and excluded from all commits/pushes.
- The technical proposal and implementation plan are the binding approved scope. Week 1-12 is historical; Week 13-16 and Tasks 1-14 are not complete until fresh evidence exists.

## Rulings

1. Task 1 may introduce only a transition-safe generic task boundary. Formal immutable dataset-version and label-schema tables remain Task 2 and Task 4 responsibilities; Task 1 stores auditable UUID references and migration snapshots without pretending those later contracts are complete.
2. Legacy spot-weld write routes are closed with a structured deprecation response. Legacy reads and migration adapters remain explicitly marked and must not become dependencies of new generic code.
3. Existing historical tests and documents are preserved. The week manifest may classify the new contract test under the current planned generic-platform work without deleting or rewriting historical ownership records.

## Pre-flight conflict table

| Scope | Shared producer/consumer | Finding | Ruling |
|---|---|---|---|
| Task 1 / Task 2 | Task 1 migration references dataset versions; Task 2 owns immutable data-version contract | A full data-version implementation in Task 1 would duplicate or preempt Task 2 | Task 1 uses stable UUID references plus migration snapshot JSON; Task 2 upgrades storage and constraints |
| Task 1 / Task 4 | Task 1 migrates legacy labels; Task 4 owns typed multi-column schema/revisions | Legacy single-label data cannot be validated by the future schema yet | Preserve raw legacy values and revision metadata in the transition snapshot; Task 4 performs typed backfill |
| Task 1 / Task 5 | Task 1 exposes generic annotation-task routes; Task 5 owns full task state machine | Route shape must exist before the complete state machine | Task 1 provides minimal create/list/read-compatible boundary and leaves lifecycle guards to Task 5 |
| Task 1 / Task 3 | Task 1 exposes `POST /api/automl-tasks`; Task 3 owns four task types and worker contract | A stub cannot claim AutoML implementation | Task 1 only establishes a generic, explicit boundary or returns a clear planned/deferred response; Task 3 implements execution |
| Task 1 / Task 10 | Task 1 must prevent legacy model coupling; Task 10 owns model-library lifecycle | Removing legacy imports too early could break historical reads | Keep adapters isolated; new generic modules do not import industry feature builders |
| Task 1 / Task 12 | Backend route/menu names and frontend navigation are shared | Renaming all historical UI in Task 1 risks unrelated regressions | Change production entry/navigation surface only; preserve historical evidence and compatibility reads |
| Task 1 / Task 13 | Migration and route writes need idempotency/audit; Task 13 owns durable worker gates | Full async reliability is downstream | Add request-level validation and deterministic migration behavior now; defer lease/retry machinery |
| Task 1 / Task 14 | Task 1 creates inventory and evidence inputs; Task 14 owns final acceptance | Early scans are not final acceptance evidence | Record current-SHA inventory and focused tests only; keep Task 14 planned |

## Per-task self-consistency table

| Task | Files/interfaces vs. tests | Result |
|---|---|---|
| 1 | Generic routes, legacy adapter, inventory and contract test are all named; downstream formal schemas are explicitly later | Consistent after ruling above |
| 2 | Parser, freeze, input contract and migration tests cover listed formats/security limits | Consistent |
| 3 | Four task types, search/ranking and non-registration tests match listed AutoML services | Consistent |
| 4 | Typed schema, revision persistence and editor tests match listed models/services | Consistent |
| 5 | Task state, preview and pagination tests match generic task APIs | Consistent |
| 6 | Strategy, clustering and rule DSL tests match listed services | Consistent |
| 7 | Annotator identity/auth and portal boundary tests match separate service files | Consistent |
| 8 | Assignment/return/concurrency tests match listed APIs and components | Consistent |
| 9 | Audit/notifications/idempotency tests match shared operation contracts | Consistent |
| 10 | Candidate registration and model-library lifecycle tests match registry services | Consistent |
| 11 | Export/offline inference tests match package and runtime interfaces | Consistent |
| 12 | Main/annotator frontend and browser tests match portal workflows | Consistent |
| 13 | Worker/recovery/cleanup tests match async task and acceptance harness files | Consistent |
| 14 | Matrix, evidence manifest and release checks match all prior task outputs | Consistent |

## Task status

- Task 1: passed (focused implementation, migration, source-gate and manifest evidence recorded below)
- Task 2: in_progress (RED tests being added; implementation not yet complete)
- Task 3: planned
- Task 4: planned
- Task 5: planned
- Task 6: planned
- Task 7: planned
- Task 8: planned
- Task 9: planned
- Task 10: planned
- Task 11: planned
- Task 12: planned
- Task 13: planned
- Task 14: planned

## Evidence log

- 2026-09-03: branch fast-forwarded with `git merge --ff-only origin/main`; HEAD is `671b815a9fe0b91bdc03f64b13ea12beb76c3039`.
- 2026-09-03: baseline dependency execution is not yet available; `py -3.14` exists but backend dependencies were previously missing, and frontend `node_modules` was absent. Install and record a fresh baseline before relying on test results.

## Task 1 review round 1

- Reviewer verdict: partial spec compliance; task quality needs fixes.
- Critical findings: no Alembic migration for `generic_annotation_tasks`; migration endpoint mutates before ownership authorization.
- Important findings: adapter aliases legacy artifact/snapshot UUIDs instead of formal generic contracts and omits integrity checks/metadata; check-then-insert idempotency races; generic writes omit typed schemas, required request/idempotency headers and unified errors; plan-listed production adapter/frontend files remain untouched; tests are too weak and mask migration gaps; missing-run errors escape as 500.
- Decision: do not mark Task 1 complete or dispatch Task 2. Fix the two critical findings first, then add focused regression tests for authorization, migration integrity, idempotency, headers, exact 410, and schema migration. Keep formal DatasetVersion/LabelSchema ownership with Tasks 2/4, but make the transition records and checks explicit enough to be safe in production.

## Task 1 review-fix round 1 (2026-09-03)

- Added `20260903_15` Alembic migration for `generic_annotation_tasks`, including project/user foreign keys, source/idempotency uniqueness and lookup indexes.
- Added strict Pydantic request contracts and required caller `X-Request-ID` plus `Idempotency-Key`; duplicate keys return the original task.
- Added pre-write run/project/actor authorization and structured missing/unauthorized 404 responses.
- Expanded migration snapshots with deterministic transition schema IDs, source run/snapshot IDs, sample IDs, full revision metadata, run metadata, row/sample checks and canonical SHA-256 checksum; concurrent uniqueness races rollback and reload.
- Added focused regression tests for exact 410 payload, owner isolation, header/idempotency contracts, authorization/no-side-effect, missing runs, metadata/checksum and migration revision presence.
- Syntax and diff checks pass; focused runtime tests remain blocked by missing `fastapi`/`httpx` dependencies. Task 1 remains `in_progress`; frontend navigation and full legacy adapter replacement remain explicitly unfinished.

## Task 1 review-fix round 2 (2026-09-03)

- Fixed test isolation for unauthorized migration no-side-effect assertion.
- Made Alembic `20260903_15` upgrade partial existing tables idempotently by adding missing columns, constraints and indexes; added a double-run regression test.
- Applied the common auth/request/idempotency/error envelope to the deprecated 410 route while preserving `GENERIC_API_REQUIRED`.
- Added independent source-versus-snapshot integrity metadata and deterministic transition boundary markers; legacy modules now expose `LEGACY_ADAPTER_ONLY`.
- Clarified that frontend production navigation/API replacement is Task 12 scope, with unfinished status retained in inventory and report.
- Verification: py_compile and git diff --check passed; focused unittest remains blocked by missing `fastapi`.

## Task 1 final verification (2026-09-04)

- Project `.venv` focused suite: `python -m unittest tests.test_genericization_contract tests.test_suite_manifest -v` -> **23/23 OK**.
- Backend-root source gate: `scan_production_sources(Path('.').resolve())` -> `[]`.
- Alembic: `check` reported no new operations; `upgrade head` completed with local revision `20260904_16`.
- Changed genericization modules compiled with `py_compile`; `git diff --check` returned exit code 0.
- Task 1 is `passed` for its scoped backend transition boundary. Formal `DatasetVersion`, parser and input-contract work remains Task 2; the platform overall remains `in_progress`.
