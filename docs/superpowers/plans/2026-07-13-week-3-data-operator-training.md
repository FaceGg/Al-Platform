# Week 3 Data, Operator, and Training Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy operator protocol across all registered operators and deliver a traceable dataset-artifact-to-model-library training loop.

**Architecture:** Introduce strict operator contract and artifact service modules, then migrate operator categories in controlled batches while keeping one final protocol. Refactor training into a service that resolves project-owned dataset artifacts and atomically records model artifacts, schema, metrics, and model-library metadata.

**Tech Stack:** Python dataclasses, FastAPI, SQLAlchemy, pandas, scikit-learn, joblib, unittest, React, TypeScript, Vitest.

---

### Task 1: Define the strict operator contract

**Files:**
- Create: `ml-platform/backend/app/engine/operator_contract.py`
- Modify: `ml-platform/backend/app/engine/base_operator.py`
- Test: `ml-platform/backend/tests/test_operator_contract.py`

- [ ] Write failing tests for OperatorContext, OperatorResult, parameter validation, port validation, metric finiteness, and artifact drafts.
- [ ] Run `python -m unittest tests.test_operator_contract -v` and confirm missing-contract failures.
- [ ] Implement contract dataclasses and stable validation errors.
- [ ] Replace BaseOperator abstract signature with `execute(context, inputs, params) -> OperatorResult`.
- [ ] Rerun contract tests.

### Task 2: Migrate every registered operator

**Files:**
- Modify: `ml-platform/backend/app/operators/*.py`
- Test: `ml-platform/backend/tests/test_operator_contract.py`
- Test: `ml-platform/backend/tests/test_operators_extended.py`
- Test: `ml-platform/backend/tests/test_operators_mechanism.py`

- [ ] Add a failing registry test that checks every execute signature and rejects bare dict results.
- [ ] Migrate IO and utility operators; run their focused tests.
- [ ] Migrate processing and blending operators; run their focused tests.
- [ ] Migrate ML, DL, and optimization operators; run their focused tests.
- [ ] Migrate evaluation and visualization operators; run their focused tests.
- [ ] Migrate control and mechanism operators; run their focused tests.
- [ ] Verify all registered operators use only the new signature.

### Task 3: Integrate the contract into DAG execution

**Files:**
- Modify: `ml-platform/backend/app/engine/dag_executor.py`
- Modify: `ml-platform/backend/app/engine/run_control.py`
- Test: `ml-platform/backend/tests/test_dag.py`
- Test: `ml-platform/backend/tests/test_run_reliability.py`

- [ ] Write failing tests for context delivery, strict OperatorResult enforcement, metrics/log propagation, cancellation, timeout, and retry.
- [ ] Create a per-attempt OperatorContext and invoke only the new signature.
- [ ] Validate OperatorResult before accepting outputs or artifacts.
- [ ] Keep existing DataBus, preview, timeout, retry, and cancellation behavior green.

### Task 4: Create the artifact service

**Files:**
- Create: `ml-platform/backend/app/services/artifact_service.py`
- Modify: `ml-platform/backend/app/models/artifact.py`
- Modify: `ml-platform/backend/app/api/datasets.py`
- Test: `ml-platform/backend/tests/test_artifact_service.py`
- Test: `ml-platform/backend/tests/test_api_datasets.py`

- [ ] Write failing tests for project-scoped resolution, SHA-256, schema inference, and immutable creation.
- [ ] Implement local artifact creation and resolution without exposing arbitrary input paths.
- [ ] Create dataset artifacts for single, batch, and ZIP uploads.
- [ ] Return artifact IDs and dataset metadata from upload APIs.

### Task 5: Persist training lineage

**Files:**
- Modify: `ml-platform/backend/app/models/training.py`
- Modify: `ml-platform/backend/app/models/model_library.py`
- Modify: `ml-platform/backend/app/database_migrations.py`
- Test: `ml-platform/backend/tests/test_training_artifacts.py`

- [ ] Write failing model/migration tests for dataset, model artifact, model-library, schema, preprocessing, error, and log fields.
- [ ] Add nullable compatibility columns and foreign keys for new databases.
- [ ] Add idempotent SQLite compatibility migrations for existing databases.

### Task 6: Build the training service loop

**Files:**
- Create: `ml-platform/backend/app/services/training_service.py`
- Modify: `ml-platform/backend/app/api/training.py`
- Test: `ml-platform/backend/tests/test_training_artifacts.py`
- Test: `ml-platform/backend/tests/test_training.py`

- [ ] Write failing tests for artifact ownership, invalid target, successful training lineage, and failed-training cleanup.
- [ ] Resolve dataset artifacts and reject arbitrary paths in new requests.
- [ ] Train and evaluate with deterministic splitting.
- [ ] Save model plus schema/preprocessing metadata as a model artifact.
- [ ] Create ModelLibrary entry and update TrainingJob links in one completion transaction.
- [ ] Retain deprecated dataset_path only for existing stored jobs.

### Task 7: Update training UI contracts

**Files:**
- Create: `ml-platform/frontend/src/api/training.ts`
- Create: `ml-platform/frontend/src/api/training.test.ts`
- Modify: `ml-platform/frontend/src/pages/TrainingJobsPage.tsx`
- Modify: `ml-platform/frontend/src/i18n/index.tsx`

- [ ] Write failing API tests requiring dataset_artifact_id and lineage fields.
- [ ] Load project dataset artifacts instead of accepting server paths.
- [ ] Display source dataset, model artifact, metrics, schema, and model-library entry.
- [ ] Add complete Chinese and English labels.

### Task 8: Verify and close Week 3

**Files:**
- Modify: `ml-platform/backend/run_suite.py`
- Modify: `docs/baseline/INTERFACE_BASELINE.md`
- Modify: `docs/baseline/TECHNICAL_DEBT.md`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [ ] Add all new test modules to the isolated runner.
- [ ] Run the complete backend runner, frontend tests, and production build.
- [ ] Execute one deterministic welding-data training loop and verify both artifact records.
- [ ] Update Week 3 status, unresolved issues, interface baseline, technical debt, and reusable experience.
