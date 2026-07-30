# Experiment and Training Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe delete actions for Experiments and terminal Training Jobs in the model-training page.

**Architecture:** The API deletes only the platform Experiment record, retaining linked Training Jobs by clearing their nullable `experiment_id`. Frontend clients wrap that route and the existing batch-delete route, while the page exposes confirmed icon actions and refreshes the affected table.

**Tech Stack:** FastAPI, SQLAlchemy, project audit service, React, TypeScript, Ant Design, Vitest, Python unittest.

---

## File Structure

- `ml-platform/backend/app/api/experiments.py`: audited Experiment delete route and declared action.
- `ml-platform/backend/tests/test_api_experiments.py`: deletion, authorization, audit, and job-unlink regression.
- `ml-platform/backend/tests/test_api_project_access.py`: audit declaration completeness.
- `ml-platform/frontend/src/api/experiments.ts`: typed Experiment deletion client.
- `ml-platform/frontend/src/api/experiments.test.ts`: Experiment deletion route contract.
- `ml-platform/frontend/src/api/training.ts`: single-job wrapper over batch delete.
- `ml-platform/frontend/src/api/training.test.ts`: training deletion payload contract.
- `ml-platform/frontend/src/pages/TrainingJobsPage.tsx`: confirmed icon actions and refresh behavior.
- `ml-platform/frontend/src/pages/TrainingJobsPage.test.tsx`: visible/hidden delete control behavior.
- `DEVELOPMENT_PLAN.md` and `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`: completion records.

### Task 1: Experiment Delete API and Audit

**Files:**
- Modify: `ml-platform/backend/tests/test_api_experiments.py`
- Modify: `ml-platform/backend/tests/test_api_project_access.py`
- Modify: `ml-platform/backend/app/api/experiments.py`

- [x] **Step 1: Write the failing deletion and audit tests**

Import `TrainingJob` in `test_api_experiments.py`, then add this method to `TestExperimentAPI`:

```python
def test_delete_retains_training_job_and_audits_permissions(self):
    created = self._create_experiment()
    with self.Session() as db:
        job = TrainingJob(
            project_id=self.project_id,
            user_id=self.owner_id,
            experiment_id=uuid.UUID(created["id"]),
            name="retained-job",
            status="completed",
        )
        db.add(job)
        db.commit()
        job_id = job.id

    denied = self.client.delete(
        f"/api/experiments/{created['id']}", headers=self.operator_headers,
    )
    self.assertEqual(denied.status_code, 403, denied.text)
    deleted = self.client.delete(
        f"/api/experiments/{created['id']}", headers=self.editor_headers,
    )
    self.assertEqual(deleted.status_code, 204, deleted.text)

    with self.Session() as db:
        self.assertIsNone(db.get(Experiment, uuid.UUID(created["id"])))
        self.assertIsNone(db.get(TrainingJob, job_id).experiment_id)
        actions = {
            (event.action, event.result)
            for event in db.query(AuditEvent).filter(AuditEvent.project_id == self.project_id)
        }
    self.assertIn(("experiment.delete", "denied"), actions)
    self.assertIn(("experiment.delete", "success"), actions)
```

Change the audit completeness expectation to:

```python
"experiments": {"experiment.create", "experiment.delete"},
```

- [x] **Step 2: Verify RED**

Run:

```powershell
Set-Location ml-platform/backend
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_api_experiments.TestExperimentAPI.test_delete_retains_training_job_and_audits_permissions tests.test_api_project_access.TestProjectWriteAuditCompleteness.test_every_project_write_module_declares_audited_actions -v
```

Expected: the API test gets `405` because only the same-path GET route exists; completeness reports a missing `experiment.delete` declaration.

- [x] **Step 3: Implement the smallest authorized route**

Import `Response`, declare the route action, and add this route before `get_experiment`:

```python
PROJECT_WRITE_ACTIONS = {
    "POST /api/experiments": "experiment.create",
    "DELETE /api/experiments/{experiment_id}": "experiment.delete",
}


@router.delete("/{experiment_id}", status_code=204)
def delete_experiment(
    experiment_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    experiment = _visible_experiment(db, experiment_id, current_user.id)
    if experiment is None:
        raise HTTPException(404, _error("EXPERIMENT_NOT_FOUND", "Experiment not found"))
    access = resolve_project_access(db, experiment.project_id, current_user.id)
    with audit_service(db).project_action(
        db, request=request, actor=current_user, access=access,
        permission="resource.delete",
        intent=AuditIntent(
            project_id=experiment.project_id,
            action="experiment.delete",
            resource_type="experiment",
            resource_id=str(experiment.id),
        ),
        allowed_changes=set(),
    ):
        db.delete(experiment)
    return Response(status_code=204)
```

Do not delete MLflow state: its adapter has no transaction-safe delete operation.

- [x] **Step 4: Verify GREEN**

Re-run the Step 2 command. Expected: both tests pass and the retained job has `experiment_id is None`.

### Task 2: Frontend API Clients

**Files:**
- Modify: `ml-platform/frontend/src/api/experiments.test.ts`
- Modify: `ml-platform/frontend/src/api/training.test.ts`
- Modify: `ml-platform/frontend/src/api/experiments.ts`
- Modify: `ml-platform/frontend/src/api/training.ts`

- [x] **Step 1: Write failing route-contract tests**

Add imports for the new functions and these tests:

```typescript
it("deletes a platform Experiment without constructing tracking URLs", async () => {
  const remove = vi.spyOn(apiClient, "delete").mockResolvedValue({ data: undefined });
  await deleteExperiment("experiment-1");
  expect(remove).toHaveBeenCalledWith("/experiments/experiment-1");
});

it("wraps a single Training Job deletion in the batch-delete contract", async () => {
  const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { deleted: 1 } });
  await deleteTrainingJob("job-1");
  expect(post).toHaveBeenCalledWith("/training/batch-delete", { ids: ["job-1"] });
});
```

- [x] **Step 2: Verify RED**

Run:

```powershell
Set-Location ml-platform/frontend
npm test -- --run src/api/experiments.test.ts src/api/training.test.ts
```

Expected: Vitest reports missing client exports.

- [x] **Step 3: Implement the typed clients**

Add these functions:

```typescript
export async function deleteExperiment(experimentId: string): Promise<void> {
  await apiClient.delete(`/experiments/${experimentId}`);
}

export async function deleteTrainingJob(jobId: string): Promise<{ deleted: number }> {
  const response = await apiClient.post("/training/batch-delete", { ids: [jobId] });
  return response.data as { deleted: number };
}
```

- [x] **Step 4: Verify GREEN**

Re-run the Step 2 command. Expected: exact endpoint and payload assertions pass.

### Task 3: Training Page Delete Controls

**Files:**
- Modify: `ml-platform/frontend/src/pages/TrainingJobsPage.test.tsx`
- Modify: `ml-platform/frontend/src/pages/TrainingJobsPage.tsx`

- [x] **Step 1: Write the failing interaction test**

Add `deleteExperiment` and `deleteTrainingJob` to hoisted/module mocks. Add `delete`, `cancel`, and `success` to mocked `t.common`. Then add:

```typescript
it("deletes Experiments and terminal Training Jobs, but not running jobs", async () => {
  mocks.deleteExperiment.mockResolvedValue(undefined);
  mocks.deleteTrainingJob.mockResolvedValue({ deleted: 1 });
  render(<TrainingJobsPage />);

  fireEvent.click(await screen.findByRole("button", { name: "Delete Weld baseline" }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
  await waitFor(() => expect(mocks.deleteExperiment).toHaveBeenCalledWith("e1"));

  fireEvent.click(screen.getByRole("tab", { name: "Training jobs" }));
  expect(screen.queryByRole("button", { name: "Delete running-job" })).not.toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Delete completed-job" }));
  fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
  await waitFor(() => expect(mocks.deleteTrainingJob).toHaveBeenCalledWith("job-2"));
});
```

- [x] **Step 2: Verify RED**

Run:

```powershell
Set-Location ml-platform/frontend
npm test -- --run src/pages/TrainingJobsPage.test.tsx
```

Expected: the Experiment delete button is absent.

- [x] **Step 3: Implement confirmed icon actions**

Import `Tooltip`, `DeleteOutlined`, and the two clients. Add handlers:

```typescript
const removeExperiment = async (experiment: Experiment) => {
  try {
    await deleteExperiment(experiment.id);
    message.success(t.common.success);
    await loadExperiments(projectId);
  } catch (error) {
    message.error(formatApiError(error, t.common.error));
  }
};

const removeTrainingJob = async (job: TrainingJob) => {
  try {
    const result = await deleteTrainingJob(job.id);
    if (result.deleted !== 1) message.error(t.common.error);
    else message.success(t.common.success);
    await loadJobs(projectId);
  } catch (error) {
    message.error(formatApiError(error, t.common.error));
  }
};

const canDeleteTrainingJob = (job: TrainingJob) => ![
  "running", "queued", "cancel_requested",
].includes(job.status || "pending");
```

Add destructive icon buttons inside `Tooltip` and `Popconfirm` with resource-specific `aria-label`, `okText={t.common.delete}`, and `cancelText={t.common.cancel}`. Set both action columns to `fixed: "right" as const`, use non-wrapping `Space`, and render the Training Job delete button only when `canDeleteTrainingJob(job)` is true.

- [x] **Step 4: Verify GREEN**

Re-run the Step 2 command. Expected: confirmed Experiment and completed Job deletion invoke their clients; the running-job control remains absent.

### Task 4: Verification and Required Records

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [x] **Step 1: Run backend regressions**

```powershell
Set-Location ml-platform/backend
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_api_experiments tests.test_api_project_access tests.test_training -v
```

Expected: Experiment deletion, project audit, and existing training deletion behavior pass.

- [x] **Step 2: Run frontend regressions and build**

```powershell
Set-Location ml-platform/frontend
npm test -- --run src/api/experiments.test.ts src/api/training.test.ts src/pages/TrainingJobsPage.test.tsx
npm run build
```

Expected: client/page tests pass and TypeScript/Vite exits 0.

- [x] **Step 3: Run full relevant suites and diff check**

```powershell
Set-Location ml-platform/backend
C:\Users\17723\miniconda3\python.exe run_suite.py
Set-Location ../frontend
npm test -- --run
Set-Location ../..
git diff --check
```

Expected: suites pass and no whitespace errors appear.

- [x] **Step 4: Append documentation records without touching historical entries**

Append observed behavior, relationship root cause, solution, verification counts, `experiment.delete` audit decision, MLflow retention decision, and active-job deletion restriction to `DEVELOPMENT_PLAN.md`. Append the reusable lifecycle rule to the project category in `DEVELOPMENT_EXPERIENCE.md`.

- [x] **Step 5: Preserve dirty-worktree boundaries**

Run:

```powershell
git status --short
git diff --check
```

Expected: scoped deletion files and pre-existing user changes remain. Do not stage, commit, revert, or overwrite unrelated work.
