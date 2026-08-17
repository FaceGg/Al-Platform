# Spot-Weld Optuna Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all fixed spot-weld and snapshot-training model candidates with the shared seven-family, five-method Optuna search contract.

**Architecture:** Extend the shared search service with an injectable estimator evaluator, then make spot-weld quality supply a macro ROC-AUC evaluator and family-result adapter. Persist one `optuna_v1` contract in the existing quality-run JSON fields and make snapshot training repeat that search on reviewed labels.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, scikit-learn, Optuna 4.9, React 18, TypeScript, Ant Design, Vitest, WSL2, Docker Compose, GitHub Actions.

---

## File Map

- `ml-platform/backend/app/services/automl_search.py`: evaluator injection and shared family-search lifecycle.
- `ml-platform/backend/app/services/spot_weld_quality.py`: point-weld evaluation, family search, result persistence, clustering input, report data, and snapshot retraining.
- `ml-platform/backend/app/api/spot_weld_quality.py`: strict seven-family search request and serialized response contract.
- `ml-platform/frontend/src/api/spotWeldQuality.ts`: new request/result TypeScript contract.
- `ml-platform/frontend/src/pages/AutoMLPage.tsx`: point-weld family/search controls and family result rendering.
- Existing backend and frontend test files: RED/GREEN coverage without adding duplicate manifest entries.
- `DEVELOPMENT_PLAN.md` and shared development experience: final evidence and reusable conclusions.

### Task 1: Add A Shared Evaluator Boundary To Family Search

**Files:**
- Modify: `ml-platform/backend/app/services/automl_search.py`
- Modify: `ml-platform/backend/tests/test_automl_search.py`

- [ ] **Step 1: Write a failing custom-evaluator test**

Add a test that passes a callable to `run_family_search`, records each estimator invocation, and returns a deterministic finite score:

```python
def test_family_search_uses_supplied_estimator_evaluator(self):
    family = get_algorithm_family("gbdt")
    calls = []

    def evaluator(estimator, *, task, features, target, evaluation):
        calls.append((type(estimator).__name__, task, evaluation["marker"]))
        return 0.8125

    result = run_family_search(
        family=family,
        task="classification",
        features=self.features,
        target=self.target,
        evaluation={"marker": "spot-weld"},
        config=SearchConfig(method="random", max_trials=5, timeout_seconds=30),
        catalog_index=3,
        estimator_evaluator=evaluator,
    )

    self.assertEqual(result.status, "completed")
    self.assertEqual(result.best_score, 0.8125)
    self.assertEqual(len(calls), 5)
```

- [ ] **Step 2: Verify RED**

Run from `ml-platform/backend`:

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_search.TestAutoMLSearch.test_family_search_uses_supplied_estimator_evaluator -v
```

Expected: `TypeError` because `estimator_evaluator` is not accepted.

- [ ] **Step 3: Implement the evaluator boundary**

Define:

```python
EstimatorEvaluator = Callable[..., float]
```

Add `estimator_evaluator: EstimatorEvaluator = _evaluate_estimator` to `run_family_search`. Replace both direct `_evaluate_estimator(...)` calls in the objective with `estimator_evaluator(...)`. Keep all sampler, pruner, timeout, callback, error, fitting, and winner behavior unchanged.

- [ ] **Step 4: Verify GREEN and generic compatibility**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_search tests.test_automl_tracking -v
```

Expected: all tests pass and the generic AutoML path still uses the default evaluator.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- ml-platform/backend/app/services/automl_search.py ml-platform/backend/tests/test_automl_search.py
git diff --cached --check
git commit -m "refactor(automl): support domain evaluators"
```

### Task 2: Replace Fixed Point-Weld Candidates With Family Search

**Files:**
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py`
- Modify: `ml-platform/backend/tests/test_spot_weld_quality_service.py`

- [ ] **Step 1: Replace fixed-candidate expectations with failing family-search tests**

Remove imports and tests for `AUTOML_CONFIGS` and `select_automl_configs`. Add tests that assert:

```python
results, winner = run_automl(
    features,
    labels,
    algorithm_ids=["gbdt", "random_forest"],
    search_method="bayesian",
    max_trials=5,
    time_budget=60,
    evaluation={"cross_validation_enabled": True, "cross_validation_folds": 3},
)

self.assertEqual([item.algorithm_id for item in results], ["gbdt", "random_forest"])
self.assertIn(winner.algorithm_id, {"gbdt", "random_forest"})
self.assertIsNotNone(winner.best_params)
self.assertIsNotNone(winner.auc)
self.assertIsNotNone(winner.f1)
```

Add isolated tests for an unavailable first family followed by success, all families failed, total deadline exhaustion, and AUC-then-F1-then-catalog-order winner selection. Use injected `family_search` test doubles for timing/failure tests so they do not train third-party models.

- [ ] **Step 2: Verify RED**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_spot_weld_quality_service.TestSpotWeldQualityAlgorithms -v
```

Expected: the current `run_automl` rejects `algorithm_ids`, `search_method`, `max_trials`, and `time_budget`.

- [ ] **Step 3: Introduce the point-weld family result**

Replace the legacy candidate structure with:

```python
@dataclass
class CandidateResult:
    algorithm_id: str
    name: str
    status: str
    config_index: int
    best_score: float | None = None
    auc: float | None = None
    f1: float | None = None
    auc_std: float = 0.0
    f1_std: float = 0.0
    completed_trials: int = 0
    pruned_trials: int = 0
    failed_trials: int = 0
    training_time_seconds: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    feature_importance: list[float] = field(default_factory=list)
    best_params: dict[str, Any] = field(default_factory=dict)
```

`to_dict()` must serialize these exact keys. Remove `model_type` and legacy `params`.

- [ ] **Step 4: Implement the point-weld evaluator and result enrichment**

Add `_evaluate_quality_estimator` that uses the existing normalized evaluation config, stratified splits, stable feature-name DataFrames, macro ROC-AUC, and macro F1. During Optuna trials it returns mean AUC. After one family search succeeds, rebuild the estimator with `family.build("classification", result.best_params)`, run the same splits once to calculate AUC/F1 means and standard deviations, average feature importance, and fit the final full-data estimator only through the existing downstream fitting boundary.

- [ ] **Step 5: Rewrite `run_automl` orchestration**

Resolve `algorithm_ids` with `resolve_algorithm_families`. Construct `SearchConfig` for each family using its remaining deadline slice. Call `run_family_search(..., estimator_evaluator=_evaluate_quality_estimator)`, preserve family order, translate every `FamilySearchResult` into `CandidateResult`, and choose the winner with:

```python
return max(
    successful,
    key=lambda item: (
        float(item.auc),
        float(item.f1),
        -item.config_index,
    ),
)
```

Progress callbacks receive completed trials, planned trials, the current family, and terminal-trial state. Do not retain a fixed-candidate branch.

- [ ] **Step 6: Update best-model fitting**

Rewrite `_fit_candidate_model` to resolve `candidate.algorithm_id`, build the selected family with `candidate.best_params`, fit it on the existing scaled stable matrix, and return the scaler and estimator. Delete the old model-type estimator builder if no remaining caller uses it.

- [ ] **Step 7: Verify GREEN**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_spot_weld_quality_service tests.test_automl_search -v
```

- [ ] **Step 8: Commit Task 2**

```powershell
git add -- ml-platform/backend/app/services/spot_weld_quality.py ml-platform/backend/tests/test_spot_weld_quality_service.py
git diff --cached --check
git commit -m "feat(spot-weld): search algorithm families"
```

### Task 3: Replace The Point-Weld API Contract

**Files:**
- Modify: `ml-platform/backend/app/api/spot_weld_quality.py`
- Modify: `ml-platform/backend/tests/test_api_spot_weld_quality.py`

- [ ] **Step 1: Write failing request-contract tests**

Post a quality request containing:

```python
{
    "dataset_artifact_id": str(self.artifact.id),
    "field_mapping": {},
    "algorithm_ids": ["gbdt", "random_forest"],
    "search_method": "bayesian",
    "max_trials": 20,
    "time_budget": 600,
}
```

Assert `202`, then assert `input_fingerprint.search_contract == "optuna_v1"` and the four resolved fields. Add 422/400 coverage for unknown or duplicate family IDs, unsupported methods, trial limits, time limits, and any supplied `candidate_ids`. Assert the serialized response exposes `selected_algorithm_ids` and `search`, never `selected_candidate_ids`.

- [ ] **Step 2: Verify RED**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_api_spot_weld_quality -v
```

Expected: the strict request model rejects the new fields or still accepts `candidate_ids`.

- [ ] **Step 3: Implement the strict request schema**

Replace `candidate_ids` with:

```python
algorithm_ids: list[str] = Field(default_factory=list)
search_method: str = "bayesian"
max_trials: int = Field(default=20, ge=5, le=200)
time_budget: int = Field(default=600, ge=60, le=3600)
```

Resolve families and validate the method before creating or validating a run. Always persist `search_contract="optuna_v1"`. Remove candidate serialization and API branches.

- [ ] **Step 4: Verify GREEN**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_api_spot_weld_quality tests.test_spot_weld_quality_service -v
```

- [ ] **Step 5: Commit Task 3**

```powershell
git add -- ml-platform/backend/app/api/spot_weld_quality.py ml-platform/backend/tests/test_api_spot_weld_quality.py
git diff --cached --check
git commit -m "feat(spot-weld): expose optuna search contract"
```

### Task 4: Persist Search Progress And Use The Family Winner

**Files:**
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py`
- Modify: `ml-platform/backend/tests/test_spot_weld_quality_service.py`
- Modify: `ml-platform/backend/tests/test_spot_weld_quality_tasks.py`

- [ ] **Step 1: Write failing execution tests**

Create a queued run with `search_contract=optuna_v1`, two family IDs, and a five-trial budget. Execute with an injected family search and assert:

```python
self.assertEqual(run.statistics["search"]["method"], "bayesian")
self.assertEqual(run.statistics["modeling_progress"]["total"], 10)
self.assertEqual([row["algorithm_id"] for row in run.automl_results], ["gbdt", "random_forest"])
self.assertEqual(run.output_artifacts["model"], str(model_artifact.id))
```

Also assert the final model metadata contains `algorithm_id`, `best_params`, `search_method`, `algorithm_ids`, and `quality_run_id`.

- [ ] **Step 2: Verify RED**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_spot_weld_quality_tasks tests.test_spot_weld_quality_service -v
```

- [ ] **Step 3: Update run creation and execution**

`create_quality_run_record` accepts and persists the four search values. `execute_quality_run` reads only the new contract, initializes `statistics.search`, persists terminal-trial progress, calls the new `run_automl`, and passes the winner's feature importance into clustering. Remove reads of `selected_candidate_ids`.

- [ ] **Step 4: Update reports and model metadata**

Report overview rows use the family display name, AUC, F1, and sorted best parameters. Candidate sheets use `algorithm_id`, status, trials, and best parameters. Model-library `backbone` uses `algorithm_id`; params and tags include search provenance.

- [ ] **Step 5: Verify GREEN**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_spot_weld_quality_service tests.test_spot_weld_quality_tasks tests.test_api_spot_weld_quality -v
```

- [ ] **Step 6: Commit Task 4**

```powershell
git add -- ml-platform/backend/app/services/spot_weld_quality.py ml-platform/backend/tests/test_spot_weld_quality_service.py ml-platform/backend/tests/test_spot_weld_quality_tasks.py
git diff --cached --check
git commit -m "feat(spot-weld): persist search progress"
```

### Task 5: Convert Snapshot Training To The Same Search Contract

**Files:**
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py`
- Modify: `ml-platform/backend/app/api/spot_weld_quality.py`
- Modify: `ml-platform/backend/tests/test_spot_weld_quality_service.py`
- Modify: `ml-platform/backend/tests/test_api_spot_weld_quality.py`

- [ ] **Step 1: Write failing snapshot tests**

Create a quality run selecting `extra_trees` and `hist_gradient_boosting`, create a reviewed-label snapshot, train it, and assert that snapshot training calls family search with exactly those family IDs and the originating search method/budget. Assert no result name begins with `AutoML(` or `MLP_`, and the registered model's backbone is a stable family ID.

- [ ] **Step 2: Verify RED**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_spot_weld_quality_service tests.test_api_spot_weld_quality -v
```

Expected: snapshot training still uses `SNAPSHOT_TRAINING_CONFIGS`.

- [ ] **Step 3: Replace snapshot search and fitting**

Delete `SNAPSHOT_TRAINING_CONFIGS`, the MLP-only branches, and fixed candidate lookup. `run_snapshot_training` calls the same `run_automl` with the originating run's search configuration and snapshot labels. `_fit_snapshot_model` resolves the winning family and best parameters, fits the existing scaler and stable matrix, and preserves class encoding and model artifact behavior.

- [ ] **Step 4: Update snapshot report output**

Keep the existing workbook sheet names where external consumers depend on them. Replace fixed-candidate rows with family search rows and include algorithm ID, AUC/F1, best parameters, trial counts, and search method.

- [ ] **Step 5: Verify GREEN**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_spot_weld_quality_service tests.test_api_spot_weld_quality -v
```

- [ ] **Step 6: Commit Task 5**

```powershell
git add -- ml-platform/backend/app/services/spot_weld_quality.py ml-platform/backend/app/api/spot_weld_quality.py ml-platform/backend/tests/test_spot_weld_quality_service.py ml-platform/backend/tests/test_api_spot_weld_quality.py
git diff --cached --check
git commit -m "feat(spot-weld): search snapshot models"
```

### Task 6: Replace Point-Weld Frontend Candidate Controls

**Files:**
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.ts`
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.test.ts`
- Modify: `ml-platform/frontend/src/pages/AutoMLPage.tsx`
- Modify: `ml-platform/frontend/src/pages/AutoMLPage.test.tsx`

- [ ] **Step 1: Write failing API and page tests**

Assert the point-weld tab exposes all seven family labels and five search labels, has point-weld-specific trial/time inputs, and does not render “报告候选算法”, `LGB_v1`, or `RF_v1`. Submit and assert:

```typescript
expect(quality.createQualityRun).toHaveBeenCalledWith("project-1", expect.objectContaining({
  algorithm_ids: ["random_forest"],
  search_method: "multi_fidelity",
  max_trials: 20,
  time_budget: 600,
}));
expect(quality.createQualityRun.mock.calls[0][1]).not.toHaveProperty("candidate_ids");
```

Add a historical-result action test using new `automl_results` rows with `algorithm_id`, `best_params`, trial counts, AUC, and F1.

- [ ] **Step 2: Verify RED**

```powershell
npm test -- --run src/api/spotWeldQuality.test.ts src/pages/AutoMLPage.test.tsx
```

- [ ] **Step 3: Replace TypeScript contracts**

Remove `selected_candidate_ids` and `candidate_ids`. Add reusable `AutoMLSearchMethod`, `AutoMLAlgorithmId`, `QualitySearchConfig`, and `QualityAlgorithmResult` types. `createQualityRun` and validation payloads carry the four new fields.

- [ ] **Step 4: Replace the point-weld controls**

Reuse the seven family and five method option arrays. Keep separate point-weld state:

```typescript
const [qualityAlgorithmIds, setQualityAlgorithmIds] = useState<string[]>([]);
const [qualitySearchMethod, setQualitySearchMethod] = useState("bayesian");
const [qualityMaxTrials, setQualityMaxTrials] = useState(20);
const [qualityTimeBudget, setQualityTimeBudget] = useState(600);
```

Use accessible `Select` and `InputNumber` controls with the same bounds as the API. Remove `REPORT_CANDIDATE_OPTIONS` and `qualityCandidateIds`.

- [ ] **Step 5: Render family search results**

The point-weld result table displays family name, status, AUC, F1, sorted best parameters, completed/pruned/failed trials, and training time. Ensure long parameter text wraps and task action buttons remain aligned at desktop and mobile widths.

- [ ] **Step 6: Verify GREEN**

```powershell
npm test -- --run src/api/spotWeldQuality.test.ts src/pages/AutoMLPage.test.tsx src/weekAcceptance.test.ts
npm run build
```

- [ ] **Step 7: Commit Task 6**

```powershell
git add -- ml-platform/frontend/src/api/spotWeldQuality.ts ml-platform/frontend/src/api/spotWeldQuality.test.ts ml-platform/frontend/src/pages/AutoMLPage.tsx ml-platform/frontend/src/pages/AutoMLPage.test.tsx
git diff --cached --check
git commit -m "feat(spot-weld): add family search controls"
```

### Task 7: Complete Local, WSL, Compose, Documentation, And GitHub Delivery

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`
- Verify: all files changed in Tasks 1-6

- [ ] **Step 1: Run focused local backend verification**

From `ml-platform/backend`, use unique temporary SQLite and artifact paths:

```powershell
$suffix = [guid]::NewGuid().ToString('N')
$dbPath = Join-Path $env:TEMP ("spot-weld-optuna-$suffix.db")
$env:DATABASE_URL = "sqlite:///$($dbPath.Replace('\\','/'))"
$env:ARTIFACT_STORAGE_DIR = Join-Path $env:TEMP ("spot-weld-optuna-artifacts-$suffix")
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_catalog tests.test_automl_search tests.test_automl_tracking tests.test_spot_weld_quality_service tests.test_api_spot_weld_quality tests.test_spot_weld_quality_tasks tests.test_suite_manifest -v
```

- [ ] **Step 2: Run full local verification**

```powershell
cd ml-platform/backend
C:\Users\17723\miniconda3\python.exe -m compileall -q app tests
C:\Users\17723\miniconda3\python.exe run_suite.py
cd ..\frontend
npm test -- --run
npm run build
cd ..\..
git diff --check
```

- [ ] **Step 3: Create the release branch on latest remote main**

Run from the original Windows worktree after all feature commits are complete:

```powershell
git fetch --prune origin
$releasePath = "E:\codex_workspace\agent_spot_welding\.worktrees\spot-weld-optuna-release"
git worktree add -b codex/spot-weld-optuna-unification $releasePath origin/main
$commits = @(git rev-list --reverse origin/main..main)
git -C $releasePath cherry-pick $commits
git -C $releasePath diff --check origin/main...HEAD
git -C $releasePath diff --stat origin/main...HEAD
git status --short --branch
```

Expected: the release worktree contains the reviewed AutoML and point-weld commits on top of current `origin/main`; the original worktree still shows only `OPTIMIZATION_PLAN.md`, `ml-platform/frontend/pnpm-lock.yaml`, and `tmp/report-media-20260730/` as preserved untracked paths.

- [ ] **Step 4: Clone the exact release branch into WSL Linux storage**

```bash
rm -rf ~/codex-validation/spot-weld-optuna
mkdir -p ~/codex-validation
git clone --branch codex/spot-weld-optuna-unification --single-branch \
  /mnt/e/codex_workspace/agent_spot_welding ~/codex-validation/spot-weld-optuna
cd ~/codex-validation/spot-weld-optuna
git status --short --branch
```

Expected: a clean Linux checkout, avoiding Windows mount line-ending noise.

- [ ] **Step 5: Run WSL Linux tests and build**

Use isolated WSL dependencies:

```bash
cd ~/codex-validation/spot-weld-optuna
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ml-platform/backend/requirements.txt
cd ml-platform/backend
export DATABASE_URL="sqlite:////tmp/spot-weld-optuna-wsl.db"
export ARTIFACT_STORAGE_DIR="/tmp/spot-weld-optuna-artifacts"
python -m unittest tests.test_automl_catalog tests.test_automl_search tests.test_automl_tracking tests.test_spot_weld_quality_service tests.test_api_spot_weld_quality tests.test_spot_weld_quality_tasks tests.test_suite_manifest -v
python -m compileall -q app tests
python run_suite.py
cd ../frontend
npm ci
npm test -- --run
npm run build
```

Record exact pass/fail counts. If the host Python 3.14 dependency resolver rejects a pinned package, treat that as an environment compatibility result and run the same commands inside the repository's pinned backend Docker image before deciding whether application code or the host runtime is at fault.

- [ ] **Step 6: Run WSL Docker Compose acceptance**

Generate an isolated `.env` from the committed template without printing secrets. Run:

```bash
docker compose --env-file .env config
docker compose --env-file .env up -d --build --remove-orphans
docker compose ps
curl --fail http://127.0.0.1/api/ready
```

Verify PostgreSQL, Redis, MinIO, MLflow, backend, worker, inference runtime, frontend, and Nginx reach their configured healthy/running states. Create an authenticated test user/project/dataset through APIs, submit a point-weld request containing the new search fields, and verify the persisted run exposes `search_contract=optuna_v1`, family progress, and no legacy candidate fields. Tear down containers without `-v` so named volumes are not destructively removed.

- [ ] **Step 7: Update project and shared experience records**

Append a dated completion entry with RED/GREEN evidence, local counts, WSL counts, Compose service/API evidence, limitations, and remote status. Add reusable experience covering shared evaluator boundaries, breaking JSON-contract migrations, point-weld family winner metrics, and WSL clean-checkout validation.

- [ ] **Step 8: Run final verification after documentation edits**

Repeat focused backend tests, focused frontend tests, production build, `git diff --check`, `git diff --cached --check`, and release-branch status. Commit only the documentation updates.

- [ ] **Step 9: Push, create PR, wait for CI, and merge**

```powershell
git push -u origin codex/spot-weld-optuna-unification
$body = @'
## Summary
- unify generic and spot-weld AutoML on seven algorithm families and five Optuna search methods
- replace fixed point-weld and snapshot candidates with persisted family search results
- add point-weld search controls, progress, result reopening, and model provenance

## Verification
- [x] focused and full backend tests
- [x] focused and full frontend tests
- [x] TypeScript and Vite production build
- [x] WSL Linux verification
- [x] WSL Docker Compose readiness and point-weld API contract
'@
gh pr create --base main --head codex/spot-weld-optuna-unification --title "feat: unify spot weld optuna search" --body $body
```

Wait for all required GitHub Actions checks. If a check fails, inspect logs and fix the verified cause; do not bypass required checks. Merge only after all required checks pass.

- [ ] **Step 10: Verify remote main**

Fetch again and verify the merged PR state, merge commit, `origin/main` ref, feature ancestry, and tree equality. Confirm the original worktree still contains only the preserved user-owned untracked paths and report any intentionally retained local branch divergence.
