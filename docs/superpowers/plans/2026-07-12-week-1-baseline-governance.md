# Week 1 Baseline Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a reproducible, buildable project baseline with a verified feature inventory, technical-debt register, and frozen interface contracts.

**Architecture:** Treat the current repository as the source of truth and distinguish implemented, prototype, blocked, and planned capabilities using executable evidence. Run backend modules with isolated databases and frontend checks from the declared package scripts; only repair failures that block the Week 1 baseline, using regression tests before behavior changes.

**Tech Stack:** FastAPI, SQLAlchemy, pandas, NetworkX, unittest, React 18, TypeScript, Vite, Vitest, Docker Compose.

---

### Task 1: Capture the executable baseline

**Files:**
- Inspect: `ml-platform/backend/app/main.py`
- Inspect: `ml-platform/backend/run_suite.py`
- Inspect: `ml-platform/frontend/package.json`
- Inspect: `docker-compose.yml`

- [ ] Run `python run_suite.py` from `ml-platform/backend` with module-isolated SQLite databases and record passed and failed modules.
- [ ] Run `npm test -- --run` from `ml-platform/frontend` and record test count and failures.
- [ ] Run `npm run build` from `ml-platform/frontend` and record TypeScript/Vite failures.
- [ ] Run `docker compose config` from the repository root and record configuration failures.

### Task 2: Inventory the implemented surface

**Files:**
- Create: `docs/baseline/FEATURE_INVENTORY.md`
- Inspect: `ml-platform/frontend/src/App.tsx`
- Inspect: `ml-platform/backend/app/api/*.py`
- Inspect: `ml-platform/backend/app/models/*.py`
- Inspect: `ml-platform/backend/app/operators/*.py`
- Inspect: `ml-platform/backend/tests/test_*.py`

- [ ] Count and classify navigable pages, API routers/endpoints, persisted models, registered operators, and automated test modules.
- [ ] Assign each feature one evidence-based state: production-ready, functional, prototype, blocked, or planned.
- [ ] Link each functional claim to its implementation and test evidence without inferring completion from file existence.

### Task 3: Freeze interface contracts

**Files:**
- Create: `docs/baseline/INTERFACE_BASELINE.md`
- Inspect: `ml-platform/backend/app/models/run.py`
- Inspect: `ml-platform/backend/app/engine/dag_executor.py`
- Inspect: `ml-platform/backend/app/engine/data_bus.py`
- Inspect: `ml-platform/backend/app/operators/base.py`
- Inspect: `ml-platform/frontend/src/api/client.ts`
- Inspect: `ml-platform/frontend/src/stores/workflowStore.ts`

- [ ] Document workflow, node, edge, run, and node-run status values used by backend and frontend.
- [ ] Document API error payloads and identify endpoints that diverge from the baseline.
- [ ] Document DataBus value categories, operator input/output contract, and executor callback events.
- [ ] Mark contract conflicts as technical debt rather than silently choosing a new runtime behavior.

### Task 4: Repair baseline blockers with TDD

**Files:**
- Test: exact adjacent test module for each confirmed blocker
- Modify: only the implementation file responsible for each confirmed blocker

- [ ] Add the smallest regression test that reproduces each confirmed build or runtime blocker.
- [ ] Run the focused test and verify it fails for the expected reason.
- [ ] Apply the minimal root-cause fix and rerun the focused test.
- [ ] Refactor only after the regression test passes.

### Task 5: Register technical debt and build commands

**Files:**
- Create: `docs/baseline/TECHNICAL_DEBT.md`
- Create: `docs/baseline/BUILD_AND_TEST.md`
- Modify: `.gitignore`

- [ ] Classify debt by severity, evidence, impact, mitigation, and target week.
- [ ] Separate source, generated output, local runtime data, logs, and temporary repair scripts.
- [ ] Document clean backend, frontend, Docker, and focused-test commands with prerequisites.
- [ ] Ignore verified runtime artifacts without deleting user files.

### Task 6: Verify and close Week 1

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [ ] Rerun the complete backend suite, frontend tests, frontend build, and Docker configuration check.
- [ ] Update Week 1 status, completed items, unfinished items, verification evidence, and carry-over risks.
- [ ] Append encountered and potential problems to the end of `DEVELOPMENT_PLAN.md` without deleting history.
- [ ] Append reusable solutions under this project in the shared development experience document.
