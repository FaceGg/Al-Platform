# Week 2 Workflow Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add published workflow snapshots and a tested in-process run state machine with cooperative cancellation, node timeout/retry, attempt history, logs, and complete frontend status handling.

**Architecture:** Persist immutable workflow versions and run control metadata in SQLAlchemy. Keep the background-thread adapter, but move transition rules and execution policies into focused engine/service modules so a future Celery adapter can preserve the same API and states.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, NetworkX, Python threads, unittest, React 18, Zustand, Vitest, TypeScript.

---

### Task 1: Freeze state transitions and policies

**Files:**
- Create: `ml-platform/backend/app/engine/run_state.py`
- Test: `ml-platform/backend/tests/test_run_reliability.py`

- [ ] Write failing tests for legal transitions, terminal-state protection, default policy values, node overrides, and invalid negative values.
- [ ] Run `python -m unittest tests.test_run_reliability.TestRunState -v` and verify failures are caused by missing state helpers.
- [ ] Implement frozen run/node status constants, transition validation, and `ExecutionPolicy.from_params`.
- [ ] Rerun focused tests and verify they pass.

### Task 2: Persist versions and run attempts

**Files:**
- Create: `ml-platform/backend/app/models/workflow_version.py`
- Modify: `ml-platform/backend/app/models/workflow.py`
- Modify: `ml-platform/backend/app/models/run.py`
- Modify: `ml-platform/backend/app/models/__init__.py`
- Test: `ml-platform/backend/tests/test_workflow_versions.py`

- [ ] Write failing model/API tests for incrementing immutable snapshots and restoring a version to the draft.
- [ ] Add `WorkflowVersion`, run cancellation/snapshot/error/log fields, and node attempt/error/duration/log fields.
- [ ] Add API schemas and relationship wiring.
- [ ] Rerun version tests against an isolated SQLite database.

### Task 3: Add workflow version APIs

**Files:**
- Create: `ml-platform/backend/app/api/workflow_versions.py`
- Modify: `ml-platform/backend/app/main.py`
- Test: `ml-platform/backend/tests/test_workflow_versions.py`

- [ ] Verify publish/list/detail/restore tests fail with 404 before router registration.
- [ ] Implement authenticated publish, list, detail, and restore endpoints.
- [ ] Serialize nodes and edges through the existing workflow payload shape.
- [ ] Verify snapshots remain unchanged after later draft edits.

### Task 4: Add executor cancellation, timeout, and retry

**Files:**
- Create: `ml-platform/backend/app/engine/run_control.py`
- Modify: `ml-platform/backend/app/engine/dag_executor.py`
- Test: `ml-platform/backend/tests/test_run_reliability.py`

- [ ] Write failing tests using deterministic test operators for failure-then-success, timeout, cancellation before a node, and cancellation during retry delay.
- [ ] Add a database-independent control interface and cancellation exception.
- [ ] Execute each attempt in a daemon worker with bounded result acceptance; ignore late timeout results.
- [ ] Emit attempt-aware callback events and stop scheduling on cancellation or exhausted failure.
- [ ] Rerun focused executor tests.

### Task 5: Add reliable run APIs and details

**Files:**
- Modify: `ml-platform/backend/app/api/runs.py`
- Modify: `ml-platform/backend/app/schemas/run.py`
- Test: `ml-platform/backend/tests/test_api_runs.py`

- [ ] Write failing API tests for preflight rejection, idempotent cancel, attempt history, stable errors, and run logs.
- [ ] Reject empty/invalid workflows before starting a thread.
- [ ] Persist cancel requests and expose a database-backed cancellation callback.
- [ ] Persist attempt history, error codes/details, duration, and bounded structured logs.
- [ ] Expand run details while preserving current response fields and completion events.

### Task 6: Complete frontend run-state behavior

**Files:**
- Modify: `ml-platform/frontend/src/stores/workflowStore.ts`
- Modify: `ml-platform/frontend/src/stores/workflowStore.test.ts`
- Modify: `ml-platform/frontend/src/pages/WorkspacePage.tsx`
- Modify: `ml-platform/frontend/src/components/workspace/ExecutionProgress.tsx`
- Modify: `ml-platform/frontend/src/components/workspace/CustomNode.tsx`
- Test: `ml-platform/frontend/src/stores/workflowStore.test.ts`

- [ ] Write failing store tests for workflow status, run ID, complete node states, and execution reset.
- [ ] Add typed run/node status sets and store actions.
- [ ] Replace local stop behavior with cancel API and `cancel_requested` UI.
- [ ] Reconcile final state through GET run details after WebSocket close.
- [ ] Display skipped, timed-out, cancelled, and cancel-requested states without progress overlap.

### Task 7: Add publish and restore UI

**Files:**
- Modify: `ml-platform/frontend/src/pages/WorkspacePage.tsx`
- Modify: `ml-platform/frontend/src/i18n/index.tsx`
- Test: `ml-platform/frontend/src/pages/WorkspacePage.test.tsx`

- [ ] Write failing component tests for publish and version restore API calls.
- [ ] Add publish command and version-history drawer with restore confirmation.
- [ ] Reload the draft after restore and preserve immutable version history.
- [ ] Add complete Chinese and English keys.

### Task 8: Verify and close Week 2

**Files:**
- Modify: `docs/baseline/INTERFACE_BASELINE.md`
- Modify: `docs/baseline/TECHNICAL_DEBT.md`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [ ] Run focused backend and frontend regression tests.
- [ ] Run `python run_suite.py`, `npm test`, and `npm run build` fresh.
- [ ] Record browser E2E availability and any warnings honestly.
- [ ] Update Week 2 status, unfinished work, problems, risks, interfaces, and reusable experience.
