# General Platform Conformance Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development. Follow the original technical proposal, not historical completion claims.

**Goal:** Implement and verify every requirement of the approved general AutoML and annotation proposal.

**Architecture:** Preserve compatible services and immutable artifacts. Complete contracts before dependent workflows, integrate real production routes, then run isolated runtime acceptance.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Celery, React, TypeScript, scikit-learn, pytest, Vitest, Playwright, WSL Docker.

**Spec:** ../../technical-proposals/2026-09-01-general-automl-annotation-platform.md

**Existing task-level implementation steps:** 2026-09-02-general-automl-annotation-platform.md

**Status:** in_progress; user approved full scope and delivery order on 2026-09-15.

## Global Constraints

- Original specification sections 1-17 remain binding. Do not redefine acceptance IDs.
- Preserve the pre-existing DEVELOPMENT_PLAN.md and docker-compose.yml changes.
- No push, production deployment, destructive data migration, or user-data deletion.
- A local unit-test result is not browser, worker, recovery, capacity, or release evidence.
- Keep immutable data contents separate from mutable import and review lifecycle records.
- New tests must first demonstrate the missing behavior, then pass with implementation.
- Each task remains open until implementation, integration, tests, and required runtime evidence exist.
- Capacity and recovery targets remain 1,000,000 samples, 200 input columns, 20 labels, 100 annotators, RPO <= 1 hour, RTO <= 4 hours.

## Coverage and Delivery Order

| Task | Spec sections | Deliverable and required checks | Status |
|---|---|---|---|
| C01 | 1, 2, 16, 17 | Trace requirements to implementation and real acceptance without reusing historical passed claims | in_progress |
| C02 | 3, 4.1, 5.1, 12 | Durable import, bounded parsing, schema/sample identity confirmation, immutable original/normalized artifacts, rejection before publication | in_progress |
| C03 | 4.2, 4.3, 6 | Multi-column schemas, frozen scope/visible fields/instructions, initialization, typed writes and revisions | planned |
| C04 | 4.4, 7 | Discovery/configuration/preview/execution chain, all strategies, frozen clustering and per-label provenance | planned |
| C05 | 3.2, 8, 12.2, 13 | Independent portal identity, grants, queue, typed editor, autosave, pagination, bulk writes, comments, confirmation and return lock | in_progress |
| C06 | 4.3, 5.2, 9 | Frozen pending return version, same-type column replacement, conflict-safe serial acceptance, superseding and global completion | planned |
| C07 | 4.5, 10 | Four tasks, frozen preprocessing, CV, actual search algorithms, independent testing, metrics, importance and manual registration | planned |
| C08 | 11.1, 14.1 | Registry lifecycle/default invalidation and project-role enforcement | in_progress |
| C09 | 11.2, 11.3 | Independent package, exact dependencies, full manifest/signature/checksums, real predict/annotate and rejection reports | in_progress |
| C10 | 12, 13 | Common write keys/revisions/errors, all list pagination, production navigation and API integration | planned |
| C11 | 14 | Role boundaries, session/security protections, parser isolation, audit and non-destructive archive | planned |
| C12 | 3.3, 15 | Durable claims/retries, restart recovery, resource preflight, capacity, artifact cleanup and consistent backup restoration | planned |
| C13 | 16, 17 | Full affected suites, migrations, real authenticated browser, isolated WSL stack, capacity/recovery and current-source evidence | planned |

## Current Bounded Work

### C08a: Draft Creation Permission

Files: backend/app/api/generic_tasks.py and backend/tests/test_annotation_task_state_api.py (relative to ml-platform).

- [x] Add real API tests for editor creation, viewer denial and outsider hiding.
- [x] Observe RED: editor/viewer both incorrectly receive 404.
- [x] Use centralized resource.create permission only at draft creation.
- [x] Run task API and project-access suites: 30 passed, 24 subtests, 2 dependency warnings.
- [ ] Verify the member's complete draft/configuration workflow and admin-only publish/accept/export boundaries.

### C02a: Import Confirmation

Files: backend import models/schemas/services/routes, migration and focused tests.

- [ ] Test upload -> durable operation -> inferred schema without a usable version.
- [ ] Test confirmation with frozen column order/types and valid or generated sample IDs.
- [ ] Test invalid confirmation, duplicate keys, retries, project isolation and no partial version.
- [ ] Implement production API and worker using stable artifact IDs and immutable final versions.
- [ ] Update main-platform consumer and execute a real upload/confirmation workflow.
- [ ] Run focused suites and fresh-database migration checks.

### C05a: Portal Editor

Files: annotator/frontend/src/pages/TaskWorkspacePage.tsx, its tests, api/tasks.ts, backend/app/api/annotator_internal.py and its focused tests.

- [ ] Test schema fields with initially empty labels and non-string value preservation.
- [ ] Test debounced serialized autosave, conflict handling and dirty-state navigation.
- [ ] Test bounded cursor navigation and source visible-column enforcement.
- [ ] Implement schema delivery/editor and require a fresh confirmation after editing.
- [ ] Run backend/frontend suites, build and authenticated browser checks.

### C09a: Standalone Export

Files: backend/app/services/model_export.py, offline runtime support and focused tests.

- [ ] Test extracted package imports and CLI execution outside the repository.
- [ ] Test required runtime files, complete annotation artifacts and checksum coverage.
- [ ] Implement the generated independent runtime without requiring platform modules.
- [ ] Verify signed export, tampered/missing files and malformed input.
- [ ] Verify real annotate equals the frozen online strategy on deterministic fixture data.

## Shared Boundaries and Rulings

| Producers / consumers | Boundary | Ruling |
|---|---|---|
| C02 / C03,C07 | DatasetVersion | Confirmation belongs to import lifecycle; no weakening immutable version protection |
| C03,C04 / C05,C06 | Frozen label schema and revisions | UI edits final values; it must not redefine schema or overwrite model provenance |
| C04,C07 / C09 | Model and strategy artifacts | Export receives actual frozen artifacts, not descriptions or placeholder metadata |
| C05 / C06 | Assignment return lock | Reopening alone does not confirm or create a new successful label revision |
| C08 / C11 | Project roles | Retain existing editor/operator/viewer granularity; do not give viewers write permissions |
| C01 / C13 | Acceptance IDs | Restore original semantics; previous differently-scoped receipts remain historical only |

## Evidence Log

- Starting source HEAD: ca2b04651e4d31f56b66ca26d81116da864c9fba, with pre-existing WSL build-network changes.
- C08a RED: `.venv311/Scripts/python.exe -m pytest tests/test_annotation_task_state_api.py -k draft_creation_uses_project_permission -q`: 2 failed, 1 passed.
- C08a GREEN: `.venv311/Scripts/python.exe -m pytest tests/test_annotation_task_state_api.py tests/test_api_project_access.py -q`: 30 passed, 24 subtests, 2 warnings.
- These runs concern an uncommitted working tree, not final-SHA release evidence.
- Browser, real broker, complete suites, capacity and restoration evidence for this plan: not_run.
