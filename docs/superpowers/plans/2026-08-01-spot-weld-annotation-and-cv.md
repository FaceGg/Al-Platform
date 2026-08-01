# Spot-Weld Annotation and Cross-Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make point-weld annotation tasks observable and reliable, and add user-controlled cross-validation and report delivery to both AutoML recipes.

**Architecture:** The existing project-scoped quality run remains the source of truth. Its serialized payload gains a derived annotation-progress object, local dispatch follows the generic enqueue-then-start protocol, and the frontend uses query-state views for task list, configuration, and workspace. Generic and quality AutoML persist one shared evaluation configuration shape, while the quality recipe keeps its report-specific feature extraction and results.

**Tech Stack:** React 18, TypeScript, Ant Design, FastAPI, SQLAlchemy, scikit-learn, unittest, Vitest.

---

### Task 1: Quality run progress and reliable local dispatch

**Files:**
- Modify: `ml-platform/backend/app/tasks/spot_weld_quality_tasks.py`
- Modify: `ml-platform/backend/app/api/spot_weld_quality.py`
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py`
- Test: `ml-platform/backend/tests/test_api_spot_weld_quality.py`

- [ ] Add a failing API assertion that a run returns `annotation_progress` with `{annotated_count, total_count, percent}` and manual runs count `current_label` rather than automatic labels.
- [ ] Add a failing dispatcher assertion that a local quality dispatcher is only started after `task_id` and `queued` status are committed.
- [ ] Implement aggregate progress serialization, batched progress persistence during automatic sample creation, and enqueue-then-start dispatch.
- [ ] Run `C:\\Users\\17723\\miniconda3\\python.exe run_suite.py --week 17` and verify the five quality modules pass.

### Task 2: Point-weld task list and correct manual workspace

**Files:**
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.ts`
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`
- Modify: `ml-platform/frontend/src/pages/DataManagePage.tsx`

- [ ] Add failing UI tests for the "点焊数据标注" catalog name, task list status/mode/progress, workspace progress, and manual-only workspace presentation.
- [ ] Add `view=tasks|setup|workspace` route state; open the task list from the catalog, direct data-management automatic labeling to setup, and keep existing `runId` links compatible.
- [ ] Render run rows with mode/status/progress, remove the workspace upload-report action, and suppress automatic rule evidence for manual runs.
- [ ] Run `pnpm exec vitest run src/pages/DataAnnotationPage.test.tsx src/pages/DataManagePage.test.tsx` and verify all affected tests pass.

### Task 3: Configurable evaluation for generic and quality AutoML

**Files:**
- Modify: `ml-platform/backend/app/api/training.py`
- Modify: `ml-platform/backend/app/services/automl_execution.py`
- Modify: `ml-platform/backend/app/api/spot_weld_quality.py`
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py`
- Modify: `ml-platform/backend/tests/test_automl_tracking.py`
- Modify: `ml-platform/backend/tests/test_api_spot_weld_quality.py`

- [ ] Add failing request and execution tests for disabled holdout evaluation, enabled 3/4/5-fold cross-validation, and invalid fold settings.
- [ ] Persist `cross_validation_enabled` and `cross_validation_folds`; use deterministic holdout scoring when disabled and `StratifiedKFold`/`KFold` when enabled.
- [ ] Preserve the quality recipe's 73-feature path, persist its selected target/input schema, and include evaluation configuration in its run/report data.
- [ ] Run quality and AutoML backend modules and verify all pass.

### Task 4: AutoML controls and quality report delivery

**Files:**
- Modify: `ml-platform/frontend/src/pages/AutoMLPage.tsx`
- Modify: `ml-platform/frontend/src/pages/AutoMLPage.test.tsx`
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.ts`

- [ ] Add failing UI tests that budget is absent, both recipes submit cross-validation fields, and the quality recipe submits selected target/input columns.
- [ ] Add a cross-validation toggle plus 3/4/5-fold selector to both recipes; remove the budget control and request field.
- [ ] Add target/input selectors to the quality recipe, a concise on-page report summary, and a report download action after quality completion.
- [ ] Run the full frontend suite and production build.

### Task 5: Final documentation and smoke validation

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\\Users\\17723\\.codex\\DEVELOPMENT_EXPERIENCE.md`

- [ ] Record root cause, state-contract changes, tests, and unverified production boundaries.
- [ ] Check `git diff --check`, start or refresh local backend/frontend services, and confirm HTTP 200 from the frontend and OpenAPI endpoints.
