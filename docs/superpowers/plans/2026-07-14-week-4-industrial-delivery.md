# Week 4 Industrial Template and Dual-Platform Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver four executable resistance-spot-welding templates from the real `Fault` dataset, one browser E2E, and verified Windows/Ubuntu local deployment paths.

**Architecture:** A deterministic dataset-preparation service converts the external wide time-series files into one compact Artifact-ready feature table. Declarative template definitions are validated before atomic instantiation and execute only through the existing DAG contract. Windows is verified locally; Ubuntu is verified through a GitHub Actions matrix using the same tests and health checks.

**Tech Stack:** Python, pandas, scikit-learn, FastAPI, SQLAlchemy, unittest, React, TypeScript, Ant Design, Vitest, Playwright, PowerShell, Bash, GitHub Actions.

**Execution note:** The current branch contains extensive uncommitted Week 1-3 work. Do not create commits or a separate worktree unless the user explicitly requests it; preserve all unrelated changes.

---

### Task 1: Build deterministic welding data preparation

**Files:**
- Create: `ml-platform/backend/app/services/weld_demo_service.py`
- Create: `ml-platform/backend/tools/prepare_weld_demo.py`
- Create: `ml-platform/backend/tests/test_weld_demo_service.py`

- [ ] **Step 1: Write failing validation and feature tests**

Define tests for missing files, row-count mismatch, row-identity mismatch, invalid `Fault`, deterministic feature columns, source hashes, class distribution, and atomic output. The desired public API is:

```python
service = WeldDemoService()
result = service.prepare(source_dir, output_csv)
self.assertEqual(result.row_count, 1976)
self.assertEqual(result.class_distribution, {"0": 1897, "1": 79})
self.assertIn("current_mean", result.columns)
self.assertIn("Fault", result.columns)
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
cd ml-platform/backend
python -m unittest tests.test_weld_demo_service -v
```

Expected: import failure because `weld_demo_service` does not exist.

- [ ] **Step 3: Implement the preparation service**

Implement `WeldDemoPreparationError(code, message, details)`, `WeldDemoResult`, and `WeldDemoService.prepare(source_dir, output_csv)`. Read rows in the original order, compare identity columns row by row, extract mean/std/min/max/median/range/non-zero count/non-zero ratio/peak position/peak value/first non-zero/last non-zero/area for current, voltage, and force, then write through a temporary file and `Path.replace()`.

- [ ] **Step 4: Implement the CLI**

Expose:

```powershell
python tools/prepare_weld_demo.py `
  --source-dir "C:\Users\17723\Desktop\resistance_spot_welding_dataset-main" `
  --output data/demo/weld_fault_features.csv
```

The command prints JSON containing output path, row count, columns, class distribution, source hashes, and preparation version. It never embeds the desktop path in source code.

- [ ] **Step 5: Verify GREEN**

Run the module tests and the CLI against the real source directory. Confirm 1,976 output rows, both classes, deterministic hashes for unchanged sources, and no modification time changes on source files.

### Task 2: Define and validate the industrial template contract

**Files:**
- Create: `ml-platform/backend/app/templates/__init__.py`
- Create: `ml-platform/backend/app/templates/contract.py`
- Create: `ml-platform/backend/app/templates/industrial.py`
- Modify: `ml-platform/backend/app/api/templates.py`
- Create: `ml-platform/backend/tests/test_industrial_templates.py`

- [ ] **Step 1: Write failing contract tests**

Tests must reject an unknown operator, unknown parameter, unknown source/target port, missing required input, invalid node reference, duplicate parameter key, and missing terminal output. Assert four stable IDs:

```python
expected = {
    "weld_quality",
    "fault_parameter_analysis",
    "anomaly_detection",
    "full_ml_comparison",
}
self.assertEqual(set(INDUSTRIAL_TEMPLATES), expected)
```

- [ ] **Step 2: Verify RED**

Run `python -m unittest tests.test_industrial_templates -v` and confirm the package is missing.

- [ ] **Step 3: Implement typed definitions and validator**

Create dataclasses for `TemplateNode`, `TemplateEdge`, `TemplateParameter`, `TemplateExpectedOutput`, and `IndustrialTemplate`. `validate_template()` resolves every operator through `OperatorRegistry`, validates parameters with `validate_operator_params`, and validates all edge ports before any database write.

- [ ] **Step 4: Move only the four approved templates**

Define the four templates with target `Fault`. Replace the invalid `mlp_train` anomaly node with registered anomaly operators. Keep other historical templates in the legacy mapping until separately migrated.

- [ ] **Step 5: Verify GREEN**

Run contract tests and `tests.test_operator_contract`. Confirm every industrial template validates against the live 79+ operator registry.

### Task 3: Add imbalanced classification and anomaly evaluation primitives

**Files:**
- Modify: `ml-platform/backend/app/operators/processing.py`
- Modify: `ml-platform/backend/app/operators/ml_operators.py`
- Modify: `ml-platform/backend/app/operators/evaluation.py`
- Modify: `ml-platform/backend/app/operators/__init__.py`
- Modify: `ml-platform/backend/tests/test_operators_extended.py`
- Modify: `ml-platform/backend/tests/test_operator_contract.py`

- [ ] **Step 1: Write failing stratification tests**

Add `target_column` and `stratify` parameters to the wished-for `train_test_split` contract. Test that both train and test contain `Fault=0` and `Fault=1` for imbalanced input and that the same seed produces the same rows.

- [ ] **Step 2: Write failing fault-metric tests**

Require `classification_eval_detailed` to expose class `1` recall/F1 and confusion-matrix values in structured outputs. Require `random_forest_train` to accept `class_weight="balanced"` and XGBoost to accept a finite `scale_pos_weight`.

- [ ] **Step 3: Write failing anomaly-evaluation tests**

Introduce a registered `anomaly_eval` operator with inputs `data`, output `metrics`, and parameters `target_column="Fault"`, `flag_column="outlier"`. Assert anomaly rate, fault recall, precision, F1, and a 2x2 confusion matrix.

- [ ] **Step 4: Verify RED**

Run the focused extended/operator contract tests and confirm missing parameters/operator failures.

- [ ] **Step 5: Implement minimal operator changes**

Use scikit-learn `train_test_split(..., stratify=df[target_column])` when enabled. Pass class weighting only to supported estimators. Implement `anomaly_eval` using finite numeric metrics and `zero_division=0`.

- [ ] **Step 6: Verify GREEN**

Run operator contract, extended, mechanism, and reliability tests. Recount runtime operator IDs and update documentation later if the total increases from 79 to 80.

### Task 4: Make template instantiation atomic and Artifact-based

**Files:**
- Modify: `ml-platform/backend/app/api/templates.py`
- Modify: `ml-platform/backend/app/services/artifact_service.py`
- Modify: `ml-platform/backend/tests/test_industrial_templates.py`
- Modify: `ml-platform/backend/tests/test_api_datasets.py`

- [ ] **Step 1: Write failing API tests**

Use a JSON body instead of query-path keys:

```json
{
  "project_id": "<uuid>",
  "dataset_artifact_id": "<uuid>",
  "parameters": {
    "n_estimators": 100,
    "contamination": 0.05
  }
}
```

Tests assert project ownership, dataset Artifact ownership/type, parameter coercion, successful node data binding, and no workflow/nodes/edges after validation failure.

- [ ] **Step 2: Verify RED**

Run the industrial template tests and confirm the current query-string endpoint cannot satisfy the JSON contract.

- [ ] **Step 3: Implement atomic instantiation**

Resolve the Artifact through `ArtifactService`, validate the template and all overrides first, create workflow/nodes/edges inside one transaction, bind the CSV import node to the resolved internal storage path, then commit once. Return `workflow_id`, `template_id`, and `dataset_artifact_id`.

- [ ] **Step 4: Keep an explicit compatibility boundary**

Legacy non-industrial templates may continue using the old endpoint behavior temporarily, but the four industrial templates use only the new JSON request. Document the deprecation and do not add dual runtime behavior inside the DAG.

- [ ] **Step 5: Verify GREEN**

Run template, dataset, workflow, and run API tests.

### Task 5: Execute all four templates end to end

**Files:**
- Create: `ml-platform/backend/tests/test_industrial_template_e2e.py`
- Modify: `ml-platform/backend/run_suite.py`
- Modify: `ml-platform/backend/app/templates/industrial.py`

- [ ] **Step 1: Write four failing E2E tests**

Prepare a bounded real-data subset that retains all 79 fault rows and a deterministic sample of normal rows. For each template: create isolated user/project, create dataset Artifact, instantiate, run through the production DAG/API path, and assert `completed` plus template-specific required outputs.

- [ ] **Step 2: Verify RED**

Run `python -m unittest tests.test_industrial_template_e2e -v`. Record the first invalid operator, edge, parameter, or output per template.

- [ ] **Step 3: Correct definitions, not the executor**

Iterate template nodes/ports/parameters until all four use registered operators correctly. Do not add template-specific cases to `DAGExecutor`.

- [ ] **Step 4: Add the module to the isolated runner**

Append `test_weld_demo_service`, `test_industrial_templates`, and `test_industrial_template_e2e` in dependency order to `backend/run_suite.py`.

- [ ] **Step 5: Verify GREEN**

Run all four E2E tests twice to prove determinism, then run the backend standard suite.

### Task 6: Rebuild the template wizard around dataset Artifacts

**Files:**
- Create: `ml-platform/frontend/src/api/templates.ts`
- Create: `ml-platform/frontend/src/api/templates.test.ts`
- Modify: `ml-platform/frontend/src/pages/TemplateWizardPage.tsx`
- Create: `ml-platform/frontend/src/pages/TemplateWizardPage.test.tsx`
- Modify: `ml-platform/frontend/src/i18n/index.tsx`

- [ ] **Step 1: Write failing API adapter tests**

Assert template detail loading and JSON instantiation with `project_id`, `dataset_artifact_id`, and semantic parameter names. Reject path-based payload types at compile time.

- [ ] **Step 2: Write failing component tests**

Test project selection/creation, project-scoped dataset loading, required Artifact selection, template scenario/target/required columns display, parameter controls, submit, error rendering, and navigation to the created workflow.

- [ ] **Step 3: Verify RED**

Run the two focused Vitest files and confirm the adapter/UI behavior is absent.

- [ ] **Step 4: Implement the adapter and page**

Use Ant Design `Select` for projects and datasets, descriptions for template metadata, and inputs only for declared semantic parameters. Remove server-path input and numeric node-path form keys. Add complete Chinese/English labels.

- [ ] **Step 5: Verify GREEN**

Run focused tests, all frontend tests, and `npm run build`. Check controls fit at desktop and mobile widths.

### Task 7: Add Playwright browser acceptance

**Files:**
- Modify: `ml-platform/frontend/package.json`
- Modify: `ml-platform/frontend/package-lock.json`
- Create: `ml-platform/frontend/playwright.config.ts`
- Create: `ml-platform/frontend/e2e/weld-quality.spec.ts`
- Create: `ml-platform/frontend/e2e/fixtures/weld_fault_features.csv`

- [ ] **Step 1: Add Playwright and a failing main-flow test**

The test logs in, creates a project, uploads the bounded prepared fixture, opens `weld_quality`, selects the Artifact, instantiates, runs, and waits for completed status and metrics.

- [ ] **Step 2: Verify RED**

Run `npx playwright test e2e/weld-quality.spec.ts --project=chromium`; confirm failure at the first missing stable selector or behavior.

- [ ] **Step 3: Add stable accessible selectors**

Prefer role/name locators. Add `data-testid` only where status or canvas internals have no stable accessible role. Do not couple tests to generated Ant Design class names.

- [ ] **Step 4: Configure traces and screenshots**

Use trace on first retry and screenshot on failure. Start backend/frontend through Playwright `webServer` commands with isolated database and storage environment variables.

- [ ] **Step 5: Verify GREEN**

Run Chromium E2E twice. Confirm no blank page, no overlapping primary controls, and completed workflow evidence.

### Task 8: Deliver Windows and Ubuntu startup paths

**Files:**
- Modify: `ml-platform/start.bat`
- Create: `ml-platform/scripts/start.ps1`
- Create: `ml-platform/scripts/stop.ps1`
- Create: `ml-platform/scripts/health-check.ps1`
- Create: `ml-platform/scripts/start.sh`
- Create: `ml-platform/scripts/stop.sh`
- Create: `ml-platform/scripts/health-check.sh`
- Modify: `.env.example`

- [ ] **Step 1: Define script acceptance checks**

Scripts validate Python 3.10+, Node 18+, npm, dependency directories, writable data paths, and free ports 8000/5173. They write PID files under a configurable runtime directory and fail with actionable messages.

- [ ] **Step 2: Implement Windows scripts**

Use PowerShell process APIs, quoted resolved paths, environment variables, and hidden background windows where appropriate. `start.bat` delegates to `scripts/start.ps1`.

- [ ] **Step 3: Implement Ubuntu scripts**

Use Bash with `set -euo pipefail`, project-relative path resolution, PID files, `trap`, and `curl --fail` health checks. Do not use platform-specific absolute paths.

- [ ] **Step 4: Verify Windows locally**

Run start, health check, login request, and stop. Confirm both PIDs terminate and no stale ports remain.

- [ ] **Step 5: Validate shell syntax**

Run Bash syntax checks through Git Bash locally and full execution in Ubuntu CI.

### Task 9: Replace CI with the real cross-platform gates

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Remove invalid gates**

Remove unconfigured pytest, pytest-cov, Codecov, ESLint, and mandatory Docker jobs. The repository's supported gates are `python run_suite.py`, `npm test`, `npm run build`, Playwright Chromium, and health checks.

- [ ] **Step 2: Add Windows/Ubuntu matrix**

Use `windows-latest` and `ubuntu-22.04`, Python 3.11, and Node 20. Cache pip/npm, install locked dependencies, run backend and frontend gates, start services with platform scripts, and verify `/api/health`.

- [ ] **Step 3: Add Ubuntu Playwright job**

Install Chromium with dependencies, run the main E2E, and upload traces/screenshots only on failure.

- [ ] **Step 4: Validate workflow syntax locally**

Parse YAML, inspect commands for PowerShell/Bash shell correctness, and ensure secrets are not required for core tests.

- [ ] **Step 5: Record external verification state**

If the branch is not pushed, mark Ubuntu CI as pending in acceptance documentation. Do not mark Week 4 complete until a real workflow run succeeds.

### Task 10: Complete delivery documentation and final verification

**Files:**
- Create: `docs/delivery/WINDOWS_DEPLOYMENT.md`
- Create: `docs/delivery/UBUNTU_DEPLOYMENT.md`
- Create: `docs/delivery/USER_GUIDE.md`
- Create: `docs/delivery/DEMO_GUIDE.md`
- Create: `docs/delivery/WEEK4_ACCEPTANCE.md`
- Modify: `ml-platform/USAGE.md`
- Modify: `docs/baseline/FEATURE_INVENTORY.md`
- Modify: `docs/baseline/BUILD_AND_TEST.md`
- Modify: `docs/baseline/INTERFACE_BASELINE.md`
- Modify: `docs/baseline/TECHNICAL_DEBT.md`
- Modify: `PLATFORM_STATUS.md`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Write platform-specific deployment guides**

Document prerequisites, environment configuration, dependency install, start, stop, health check, database reset, path permissions, port conflicts, and troubleshooting with tested commands.

- [ ] **Step 2: Write the user and demo guides**

Document login, project creation, data preparation from the approved source directory, dataset upload, each template's business meaning, run status, metrics, errors, and repeatable demonstration sequence.

- [ ] **Step 3: Run fresh complete verification**

Run:

```powershell
cd ml-platform/backend
python run_suite.py
cd ../frontend
npm test
npm run build
npx playwright test --project=chromium
```

Then run Windows startup/health/stop verification. Record exact module/test counts, duration, warnings, and package size.

- [ ] **Step 4: Verify Ubuntu CI evidence**

Record the workflow URL and job results if available. If unavailable, set Week 4 to `进行中` and list Ubuntu CI as the only external acceptance gap.

- [ ] **Step 5: Update project and shared experience records**

Append observed behavior, root causes, solutions, verification methods, prevention measures, and remaining risks. Preserve all historical entries and add corrections instead of deleting them.

## 2026-07-14 Execution Checkpoint

- Completed: Tasks 1-5, including two deterministic four-template backend E2E runs.
- Completed: Task 6 Artifact-based template adapter/page and focused frontend tests.
- Completed: Task 7 Chromium main flow; one full run passed with persisted metrics evidence.
- In progress: Task 8 scripts are implemented; Windows stages passed and Bash syntax passed, but Ubuntu execution remains CI-only.
- In progress: Task 9 workflow is implemented and parses locally; no real GitHub Actions run exists yet.
- Pending: Task 10 delivery documents and fresh complete verification.
- Paused: `python run_suite.py` was intentionally terminated when the user requested a progress save and pause.

## 2026-07-14 Local Acceptance Resume

- Fresh backend suite: 31/31 isolated modules passed; latest run took about 199.1 seconds.
- Fresh frontend suite: 9/9 files and 26/26 tests passed; production build passed.
- Chromium acceptance passed again, including completed run and persisted metrics.
- Fresh Windows start, health, login, stop, PID cleanup, and port release passed.
- All five delivery documents and baseline/status updates are present.
- Remaining gate: a real Ubuntu GitHub Actions `quality` and `browser-acceptance` run after the branch is committed and pushed.
