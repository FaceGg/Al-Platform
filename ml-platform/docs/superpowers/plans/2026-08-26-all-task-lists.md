# All Task Lists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AutoML, training, data annotation, and orchestration task lists show all accessible tasks by default and display project and creator columns.

**Architecture:** Standardize optional `project_id` filtering at each list API and return project/creator display fields from the backend. Preserve project authorization as the source of truth; add project and creator ownership to `AgentTask` because orchestration currently cannot reliably serialize those fields.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, React, TypeScript, Ant Design, Vitest, pytest.

---

### Task 1: Add orchestration task ownership fields

**Files:**
- Create: `backend/alembic/versions/20260826_13_agent_task_ownership.py`
- Modify: `backend/app/models/agent.py`
- Test: `backend/tests/test_models_misc.py`

- [ ] **Step 1: Add a failing model test**

Assert that `AgentTask` accepts `project_id` and `created_by_id`, and exposes `project` and `created_by_user` relationships.

- [ ] **Step 2: Run the model test**

Run: `python -m pytest tests/test_models_misc.py -q`

Expected before implementation: failure because the fields do not exist.

- [ ] **Step 3: Add nullable ownership columns and relationships**

Add UUID foreign keys to `projects.id` and `users.id`. Keep them nullable for existing rows. Create indexes in the Alembic migration and use `ondelete="CASCADE"` for project ownership and `ondelete="SET NULL"` for creator ownership.

- [ ] **Step 4: Verify model and migration syntax**

Run: `python -m py_compile app/models/agent.py alembic/versions/20260826_13_agent_task_ownership.py`

Expected: exit code 0.

### Task 2: Standardize backend task-list contracts

**Files:**
- Modify: `backend/app/api/training.py`
- Modify: `backend/app/api/spot_weld_quality.py`
- Modify: `backend/app/api/orchestration.py`
- Test: `backend/tests/test_training.py`
- Test: `backend/tests/test_api_spot_weld_quality.py`
- Test: `backend/tests/test_agents.py`

- [ ] **Step 1: Add failing training serialization tests**

Create jobs in two accessible projects and assert `/training/jobs` and `/training/automl/jobs` return both without `project_id`, return one with an explicit filter, and include `project_name`, `created_by_id`, and `created_by_name`.

- [ ] **Step 2: Add failing annotation list tests**

Create runs in two accessible projects and assert `/spot-weld/runs` returns both without a filter, filters by explicit `project_id`, excludes inaccessible projects, and includes project and creator display fields.

- [ ] **Step 3: Add failing orchestration list tests**

Assert new tasks persist the authenticated creator and selected project. Assert the unfiltered list includes tasks across accessible projects, an explicit filter narrows the list, and legacy workflow-backed tasks derive missing display fields from their workflow.

- [ ] **Step 4: Implement training serialization**

Return `created_by_id` from `TrainingJob.user_id` and `created_by_name` from `TrainingJob.user.username`. Remove the duplicate `error_details` key from `_job_to_dict`.

- [ ] **Step 5: Implement optional annotation filtering**

Make `project_id` optional. With a filter, call `require_project_access`; without it, query only IDs returned by `ProjectAccessService.accessible_project_query`. Preserve newest-first ordering and existing manual annotation counts.

- [ ] **Step 6: Implement orchestration ownership and filtering**

Require `project_id` when creating new standalone tasks, verify `execution.operate`, and save `created_by_id`. For workflow tasks, save the workflow project and current actor. Serialize direct ownership first, then workflow fallback. Apply accessible-project filtering when `workflow_id` and `project_id` are omitted.

- [ ] **Step 7: Run focused backend tests**

Run: `python -m pytest tests/test_training.py tests/test_api_spot_weld_quality.py tests/test_agents.py -q`

Expected: all selected tests pass. If pytest dependencies are unavailable, record the run as skipped and run `py_compile` instead; do not report it as passed.

### Task 3: Update AutoML and training task lists

**Files:**
- Modify: `frontend/src/api/training.ts`
- Modify: `frontend/src/pages/AutoMLPage.tsx`
- Modify: `frontend/src/pages/TrainingJobsPage.tsx`
- Modify: `frontend/src/i18n/index.tsx`
- Test: `frontend/src/pages/AutoMLPage.test.tsx`
- Test: `frontend/src/pages/TrainingJobsPage.test.tsx`
- Test: `frontend/src/api/training.test.ts`

- [ ] **Step 1: Add failing frontend tests**

Assert the initial task requests omit `project_id`, the project selector offers an all-projects option, selecting a project adds the filter, and both tables render project and creator names.

- [ ] **Step 2: Extend the training job type**

Add `project_name`, `created_by_id`, and `created_by_name` to `TrainingJob`.

- [ ] **Step 3: Separate training list scope from creation scope**

Keep the page-level task filter undefined by default. Do not select the first project after loading projects. Experiments and create forms continue to require a concrete project. Render project and creator columns before status/progress.

- [ ] **Step 4: Add AutoML creator display**

Map creator fields into `ModelingTask`, render the creator column, and retain the existing optional project request behavior.

- [ ] **Step 5: Run focused frontend tests**

Run: `npm test -- --run src/api/training.test.ts src/pages/AutoMLPage.test.tsx src/pages/TrainingJobsPage.test.tsx`

Expected: all non-skipped selected tests pass.

### Task 4: Update annotation and orchestration task lists

**Files:**
- Modify: `frontend/src/api/spotWeldQuality.ts`
- Modify: `frontend/src/pages/DataAnnotationPage.tsx`
- Modify: `frontend/src/pages/OrchestrationPage.tsx`
- Modify: `frontend/src/i18n/index.tsx`
- Test: `frontend/src/api/spotWeldQuality.test.ts`
- Test: `frontend/src/pages/DataAnnotationPage.test.tsx`
- Create: `frontend/src/pages/OrchestrationPage.test.tsx`

- [ ] **Step 1: Add failing annotation tests**

Assert `listQualityRuns()` omits project parameters, the task page initially shows runs from multiple projects, and selecting a project filters the request while preserving project/creator columns.

- [ ] **Step 2: Add failing orchestration tests**

Assert the page loads projects and unfiltered tasks, renders project and creator columns, filters by project, and submits a concrete `project_id` when creating a task.

- [ ] **Step 3: Make quality-run project filtering optional**

Change `listQualityRuns(projectId?: string)` to omit params when undefined. Update the task-page request race guard to support the all-project scope and ensure row actions use `run.project_id`.

- [ ] **Step 4: Add orchestration project state and columns**

Load accessible projects, add an `All projects` selector, include optional `project_id` in list requests, require a project in the create form, and render project/creator columns using names with ID fallbacks.

- [ ] **Step 5: Run focused frontend tests**

Run: `npm test -- --run src/api/spotWeldQuality.test.ts src/pages/DataAnnotationPage.test.tsx src/pages/OrchestrationPage.test.tsx`

Expected: all non-skipped selected tests pass.

### Task 5: Documentation and final verification

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Run the complete focused frontend suite**

Run: `npm test -- --run src/api/training.test.ts src/api/spotWeldQuality.test.ts src/pages/AutoMLPage.test.tsx src/pages/TrainingJobsPage.test.tsx src/pages/DataAnnotationPage.test.tsx src/pages/OrchestrationPage.test.tsx`

- [ ] **Step 2: Build the frontend**

Run: `npm run build`

Expected: TypeScript and Vite build pass; existing chunk-size warnings may remain.

- [ ] **Step 3: Run backend verification**

Run: `python -m pytest tests/test_training.py tests/test_api_spot_weld_quality.py tests/test_agents.py tests/test_models_misc.py -q`

Fallback when pytest is unavailable: `python -m py_compile app/models/agent.py app/api/training.py app/api/spot_weld_quality.py app/api/orchestration.py alembic/versions/20260826_13_agent_task_ownership.py`.

- [ ] **Step 4: Check the worktree diff**

Run: `git diff --check`

Expected: no whitespace errors. Preserve all unrelated dirty-worktree changes.

- [ ] **Step 5: Record verified results**

Append the observed behavior, root cause, implementation, exact verification results, skipped checks, and remaining remote verification to both development documents. Do not commit or push unless the user explicitly requests it.
