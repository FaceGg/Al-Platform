# AutoML Hyperparameter Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic AutoML versioned-candidate selector with seven algorithm families, add five real Optuna search methods with bounded progress and compatibility, and let users reopen persisted modeling results from the task table.

**Architecture:** Keep the existing finite candidate path unchanged for historical `candidate_ids` jobs. Add an immutable algorithm catalog and a standalone Optuna search service, then branch the existing AutoML worker on a persisted `search_contract=optuna_v1` marker. The frontend sends the new contract, renders family-level results, and reloads generic or spot-weld result details into the existing page sections.

**Tech Stack:** Python 3, FastAPI, Pydantic 2, scikit-learn, Optuna 4.9, MLflow adapter, SQLAlchemy JSON fields, React 18, TypeScript, Ant Design, Vitest.

---

## File Structure

- Create `ml-platform/backend/app/services/automl_catalog.py`: seven immutable family definitions, search spaces, dependency checks, estimator construction, and multi-fidelity resources.
- Create `ml-platform/backend/app/services/automl_search.py`: Optuna sampler/pruner selection, evaluation, trial progress, family summaries, deadlines, and deterministic winner selection.
- Create `ml-platform/backend/tests/test_automl_catalog.py`: catalog identity, factories, search-space validation, and no-fallback regression tests.
- Create `ml-platform/backend/tests/test_automl_search.py`: five search modes, pruning, progress, deadlines, and deterministic selection tests.
- Modify `ml-platform/backend/app/services/automl_execution.py`: preserve legacy execution and orchestrate the new family-search path, MLflow children, artifacts, metrics, and ModelLibrary registration.
- Modify `ml-platform/backend/app/api/training.py`: strict new/legacy request discrimination, validation, and frozen search configuration.
- Modify `ml-platform/backend/tests/test_automl_tracking.py`: API compatibility, persisted configuration, execution lineage, partial failure, and artifact integration.
- Modify `ml-platform/backend/requirements.txt`: pin Optuna.
- Modify `ml-platform/backend/tests/week_manifest.py`: register both new backend test modules exactly once under Week 6.
- Modify `ml-platform/frontend/src/pages/AutoMLPage.tsx`: seven-family controls, five search controls, family results, progress, and task result actions.
- Modify `ml-platform/frontend/src/pages/AutoMLPage.test.tsx`: UI contract, payload, result rendering, and historical result reopening tests.
- Modify `DEVELOPMENT_PLAN.md`: append implementation status, evidence, known risks, and remaining external acceptance.
- Modify `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`: append reusable lessons after implementation verification.

---

### Task 1: Pin Optuna and Add the Seven-Family Catalog

**Files:**
- Modify: `ml-platform/backend/requirements.txt`
- Create: `ml-platform/backend/app/services/automl_catalog.py`
- Create: `ml-platform/backend/tests/test_automl_catalog.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [ ] **Step 1: Write the failing catalog tests**

```python
import unittest
from unittest.mock import patch

from sklearn.base import ClassifierMixin, RegressorMixin

from app.services.automl_catalog import (
    AUTOML_FAMILY_IDS,
    AlgorithmUnavailable,
    get_algorithm_family,
    list_algorithm_families,
)


class TestAutoMLCatalog(unittest.TestCase):
    def test_catalog_contains_exactly_seven_unique_families(self):
        self.assertEqual(AUTOML_FAMILY_IDS, (
            "lightgbm", "xgboost", "catboost", "gbdt",
            "random_forest", "extra_trees", "hist_gradient_boosting",
        ))
        self.assertEqual(len(list_algorithm_families()), 7)

    def test_every_family_defines_both_tasks_and_resource(self):
        for family in list_algorithm_families():
            self.assertTrue(family.grid)
            self.assertTrue(family.search_space)
            self.assertIn(family.resource_parameter, family.search_space)
            self.assertIsInstance(family.build("classification", family.default_params), ClassifierMixin)
            self.assertIsInstance(family.build("regression", family.default_params), RegressorMixin)

    def test_optional_family_never_falls_back(self):
        family = get_algorithm_family("lightgbm")
        with patch("app.services.automl_catalog.import_module", side_effect=ImportError):
            with self.assertRaises(AlgorithmUnavailable) as raised:
                family.build("classification", family.default_params)
        self.assertEqual(raised.exception.code, "AUTOML_ALGORITHM_UNAVAILABLE")
```

Register `test_automl_catalog` once in Week 6 of `tests/week_manifest.py`.

- [ ] **Step 2: Run the test and verify RED**

From `ml-platform/backend`:

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_catalog -v
```

Expected: import failure because `app.services.automl_catalog` does not exist.

- [ ] **Step 3: Pin and install Optuna**

Add after `scikit-learn==1.7.*`:

```text
optuna==4.9.0
```

```powershell
C:\Users\17723\miniconda3\python.exe -m pip install optuna==4.9.0
```

- [ ] **Step 4: Implement the immutable catalog**

Use these public types and functions:

```python
from dataclasses import dataclass
from importlib import import_module
from types import MappingProxyType
from typing import Callable, Literal, Mapping

TaskType = Literal["classification", "regression"]


class AlgorithmUnavailable(RuntimeError):
    code = "AUTOML_ALGORITHM_UNAVAILABLE"


@dataclass(frozen=True)
class ParameterSpec:
    kind: Literal["categorical", "int", "float"]
    low: int | float | None = None
    high: int | float | None = None
    choices: tuple[object, ...] = ()
    log: bool = False
    step: int | float | None = None


@dataclass(frozen=True)
class AlgorithmFamily:
    id: str
    display_name: str
    default_params: Mapping[str, object]
    grid: Mapping[str, tuple[object, ...]]
    search_space: Mapping[str, ParameterSpec]
    resource_parameter: str
    min_resource: int
    max_resource: int
    builder: Callable[[TaskType, Mapping[str, object]], object]

    def build(self, task: TaskType, params: Mapping[str, object]):
        if task not in {"classification", "regression"}:
            raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
        return self.builder(task, MappingProxyType(dict(params)))


_FAMILIES: tuple[AlgorithmFamily, ...] = (
    LIGHTGBM_FAMILY, XGBOOST_FAMILY, CATBOOST_FAMILY, GBDT_FAMILY,
    RANDOM_FOREST_FAMILY, EXTRA_TREES_FAMILY, HIST_GRADIENT_BOOSTING_FAMILY,
)
AUTOML_FAMILY_IDS = tuple(family.id for family in _FAMILIES)
_FAMILY_BY_ID = MappingProxyType({family.id: family for family in _FAMILIES})


def list_algorithm_families() -> tuple[AlgorithmFamily, ...]:
    return _FAMILIES


def resolve_algorithm_families(ids: list[str] | tuple[str, ...] | None) -> tuple[AlgorithmFamily, ...]:
    requested = tuple(ids or AUTOML_FAMILY_IDS)
    if len(requested) != len(set(requested)) or any(item not in _FAMILY_BY_ID for item in requested):
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
    return tuple(_FAMILY_BY_ID[item] for item in requested)


def get_algorithm_family(family_id: str) -> AlgorithmFamily:
    try:
        return _FAMILY_BY_ID[family_id]
    except KeyError as error:
        raise ValueError("AUTOML_SEARCH_CONFIG_INVALID") from error
```

Define all seven confirmed families in order. Every builder constructs the exact selected family, uses seed `42`, and uses `n_jobs=1` where supported. Optional builders use `import_module` and raise `AlgorithmUnavailable` on `ImportError`. `resolve_algorithm_families` treats an empty sequence as all families and rejects duplicates before lookup.

- [ ] **Step 5: Run catalog and manifest tests and verify GREEN**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_catalog tests.test_suite_manifest -v
```

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- ml-platform/backend/requirements.txt ml-platform/backend/app/services/automl_catalog.py ml-platform/backend/tests/test_automl_catalog.py ml-platform/backend/tests/week_manifest.py
git commit -m "feat(automl): add algorithm family catalog"
```

---

### Task 2: Add the Unified Optuna Search Service

**Files:**
- Create: `ml-platform/backend/app/services/automl_search.py`
- Create: `ml-platform/backend/tests/test_automl_search.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [ ] **Step 1: Write failing sampler and result tests**

```python
import unittest

import numpy as np
from optuna.pruners import HyperbandPruner, NopPruner
from optuna.samplers import GridSampler, NSGAIISampler, RandomSampler, TPESampler

from app.services.automl_search import (
    SearchConfig,
    build_optuna_components,
    choose_family_winner,
    run_family_search,
)
from app.services.automl_catalog import get_algorithm_family


class TestAutoMLSearch(unittest.TestCase):
    def test_five_methods_map_to_expected_components(self):
        cases = {
            "grid": (GridSampler, NopPruner),
            "random": (RandomSampler, NopPruner),
            "bayesian": (TPESampler, NopPruner),
            "evolutionary": (NSGAIISampler, NopPruner),
            "multi_fidelity": (TPESampler, HyperbandPruner),
        }
        for method, expected in cases.items():
            sampler, pruner = build_optuna_components(method, {"max_depth": (2, 3)}, 10, 100, 5)
            self.assertIsInstance(sampler, expected[0])
            self.assertIsInstance(pruner, expected[1])

    def test_family_search_reports_every_terminal_trial(self):
        progress = []
        result = run_family_search(
            family=get_algorithm_family("random_forest"),
            task="classification",
            features=np.asarray([[i, i % 3] for i in range(40)]),
            target=np.asarray([i % 2 for i in range(40)]),
            evaluation={"cross_validation_enabled": False, "cross_validation_folds": None},
            config=SearchConfig(method="random", max_trials=5, timeout_seconds=30),
            progress_callback=progress.append,
        )
        self.assertEqual(result.completed_trials + result.pruned_trials + result.failed_trials, 5)
        self.assertEqual(len(progress), 5)
        self.assertIsNotNone(result.best_estimator)
```

Add tests for seeded grid caps, multi-fidelity pruning, failed trials, unavailable families, passed deadlines, finite-score validation, and score-then-catalog-order tie breaking. Register `test_automl_search` once under Week 6.

- [ ] **Step 2: Run the test and verify RED**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_search -v
```

Expected: import failure because `automl_search.py` does not exist.

- [ ] **Step 3: Implement search configuration and result types**

```python
@dataclass(frozen=True)
class SearchConfig:
    method: str
    max_trials: int
    timeout_seconds: float


@dataclass(frozen=True)
class TrialProgress:
    algorithm_id: str
    trial_number: int
    state: str
    score: float | None


@dataclass
class FamilySearchResult:
    algorithm_id: str
    display_name: str
    catalog_index: int
    status: str
    best_score: float | None = None
    best_params: dict[str, object] = field(default_factory=dict)
    best_estimator: object | None = None
    feature_importance: list[float] = field(default_factory=list)
    completed_trials: int = 0
    pruned_trials: int = 0
    failed_trials: int = 0
    training_time_seconds: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
```

Validate method IDs, trial counts, positive timeouts, and finite scores at the service boundary.

- [ ] **Step 4: Implement sampler/pruner mapping**

```python
def build_optuna_components(method, grid, min_resource, max_resource, max_trials):
    startup = min(5, max_trials)
    if method == "grid":
        return GridSampler({key: list(values) for key, values in grid.items()}, seed=42), NopPruner()
    if method == "random":
        return RandomSampler(seed=42), NopPruner()
    if method == "bayesian":
        return TPESampler(seed=42, n_startup_trials=startup), NopPruner()
    if method == "evolutionary":
        return NSGAIISampler(seed=42), NopPruner()
    if method == "multi_fidelity":
        return TPESampler(seed=42, n_startup_trials=startup), HyperbandPruner(
            min_resource=min_resource,
            max_resource=max_resource,
            reduction_factor=2,
        )
    raise ValueError("AUTOML_SEARCH_CONFIG_INVALID")
```

For grid search, calculate the finite combination count and pass `min(max_trials, combinations)` to `study.optimize`.

- [ ] **Step 5: Implement evaluation, pruning, and final fitting**

Use one parameter-suggestion function driven by `ParameterSpec`. Standard methods evaluate once with the existing deterministic CV/holdout behavior. Multi-fidelity evaluates unique integer rungs at approximately 25%, 50%, and 100% of the resource maximum, calls `trial.report`, and raises `TrialPruned` when requested. Rebuild and fit the family winner on all prepared data after the study. Extract matching-width `feature_importances_` or absolute `coef_`; otherwise return an empty list.

- [ ] **Step 6: Run search tests and verify GREEN**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_catalog tests.test_automl_search tests.test_suite_manifest -v
```

- [ ] **Step 7: Commit Task 2**

```powershell
git add -- ml-platform/backend/app/services/automl_search.py ml-platform/backend/tests/test_automl_search.py ml-platform/backend/tests/week_manifest.py
git commit -m "feat(automl): add optuna search strategies"
```

---

### Task 3: Integrate Family Search into AutoML Execution and MLflow

**Files:**
- Modify: `ml-platform/backend/app/services/automl_execution.py`
- Modify: `ml-platform/backend/tests/test_automl_tracking.py`

- [ ] **Step 1: Write failing execution tests**

Create a job using the new persisted marker and assert family summaries and the true winner:

```python
def test_optuna_job_searches_each_family_and_persists_results(self):
    job_id = self.create_job(params={
        "search_contract": "optuna_v1",
        "target_column": "quality",
        "input_columns": ["current", "force"],
        "task": "classification",
        "algorithm_ids": ["gbdt", "random_forest"],
        "search_method": "bayesian",
        "max_trials": 5,
        "time_budget": 60,
        "cross_validation_enabled": False,
        "cross_validation_folds": None,
    })

    result = self.execute(job_id)

    self.assertEqual(result.status, "completed")
    with self.Session() as db:
        job = db.query(TrainingJob).filter(TrainingJob.id == job_id).one()
        self.assertEqual(job.metrics["search"]["method"], "bayesian")
        self.assertEqual(
            [item["algorithm_id"] for item in job.metrics["algorithm_results"]],
            ["gbdt", "random_forest"],
        )
        self.assertIn(job.metrics["best_model"]["algorithm_id"], {"gbdt", "random_forest"})
```

Add tests for one unavailable family followed by success, all families failed, deadline exhaustion after a success, MLflow trial tags, ModelLibrary provenance, and an unchanged legacy `candidate_ids` job.

- [ ] **Step 2: Run focused execution tests and verify RED**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_tracking.TestAutoMLTracking -v
```

Expected: new assertions fail because the worker still resolves finite candidates.

- [ ] **Step 3: Extend execution dependency injection**

Add a `family_search` callable and monotonic clock to `AutoMLDependencies`, with production defaults. Keep the existing `candidates` override for legacy tests. Initialize the new metrics shape before starting the first family:

```python
job.metrics = {
    "evaluation": evaluation,
    "search": {
        "method": search_method,
        "max_trials": max_trials,
        "time_budget": time_budget,
        "budget_exhausted": False,
    },
    "progress": {
        "completed": 0,
        "total": planned_trial_count,
        "percent": 0,
        "current_algorithm": None,
        "current_trial": None,
        "search_method": search_method,
        "budget_exhausted": False,
    },
    "algorithm_results": [],
    "all_results": [],
}
```

- [ ] **Step 4: Add the explicit `optuna_v1` worker branch**

Branch only on `params.get("search_contract") == "optuna_v1"`. The new branch resolves frozen family IDs, computes a monotonic task deadline, assigns `remaining_seconds / remaining_families`, persists progress after every terminal trial, appends one bounded family summary, and chooses the deterministic winner. Start one MLflow child per Optuna trial with these tags:

```python
{
    "platform.algorithm_family": family.id,
    "platform.search_method": search_method,
    "platform.trial_number": trial.number,
    "platform.trial_state": state,
    "platform.run_type": "automl_trial",
}
```

Serialize only the freshly fitted overall winner. Preserve existing artifact compensation and ModelLibrary transaction behavior. Do not rewrite the legacy candidate loop; extract shared finalization only after both paths pass.

- [ ] **Step 5: Run execution tests and verify GREEN**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_tracking tests.test_automl_search -v
```

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- ml-platform/backend/app/services/automl_execution.py ml-platform/backend/tests/test_automl_tracking.py
git commit -m "feat(automl): execute family hyperparameter search"
```

---

### Task 4: Add the Strict New API Contract and Preserve Legacy Requests

**Files:**
- Modify: `ml-platform/backend/app/api/training.py`
- Modify: `ml-platform/backend/tests/test_automl_tracking.py`

- [ ] **Step 1: Write failing API contract tests**

```python
def test_new_search_request_persists_resolved_contract(self):
    response = self.client.post("/api/training/automl/run", json={
        **self.valid_payload,
        "algorithm_ids": ["gbdt", "random_forest"],
        "search_method": "bayesian",
        "max_trials": 20,
        "time_budget": 600,
    })
    self.assertEqual(response.status_code, 202)
    with self.Session() as db:
        job = db.query(TrainingJob).filter(
            TrainingJob.id == uuid.UUID(response.json()["job_id"])
        ).one()
        self.assertEqual(job.params["search_contract"], "optuna_v1")
        self.assertEqual(job.params["algorithm_ids"], ["gbdt", "random_forest"])

def test_new_and_legacy_algorithm_fields_are_mutually_exclusive(self):
    response = self.client.post("/api/training/automl/run", json={
        **self.valid_payload,
        "algorithm_ids": ["gbdt"],
        "candidate_ids": ["GBDT_v1"],
        "search_method": "grid",
        "max_trials": 5,
        "time_budget": 60,
    })
    self.assertEqual(response.status_code, 400)
    self.assertEqual(response.json()["detail"]["code"], "AUTOML_SEARCH_CONFIG_INVALID")
```

Add tests for invalid methods, duplicate/unknown families, trial bounds, the new 60-second minimum, empty families resolving to all seven, and an unchanged legacy request.

- [ ] **Step 2: Run API tests and verify RED**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_tracking.TestAutoMLAPI -v
```

Expected: the strict request model rejects the new fields.

- [ ] **Step 3: Extend `AutoMLRunRequest` and discriminate by explicit fields**

Add:

```python
algorithm_ids: list[str] = Field(default_factory=list)
search_method: str | None = None
max_trials: int | None = Field(default=None, ge=5, le=200)
```

Keep the existing broad Pydantic range for `time_budget`. Detect the new contract with:

```python
new_fields = {"algorithm_ids", "search_method", "max_trials"}
uses_new_contract = bool(data.model_fields_set & new_fields)
```

When new fields are used, require all three fields explicitly, reject explicitly supplied `candidate_ids`, require `time_budget >= 60`, resolve empty families to all seven, and persist `search_contract="optuna_v1"`. When none are used, call `resolve_candidates` exactly as before and do not add the marker. Use `AUTOML_SEARCH_CONFIG_INVALID` for new-contract errors and retain `AUTOML_CONFIG_INVALID` for legacy errors.

- [ ] **Step 4: Run API and execution tests and verify GREEN**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_tracking tests.test_training -v
```

- [ ] **Step 5: Commit Task 4**

```powershell
git add -- ml-platform/backend/app/api/training.py ml-platform/backend/tests/test_automl_tracking.py
git commit -m "feat(automl): expose search request contract"
```

---

### Task 5: Replace the Generic Selector and Submit Search Configuration

**Files:**
- Modify: `ml-platform/frontend/src/pages/AutoMLPage.tsx`
- Modify: `ml-platform/frontend/src/pages/AutoMLPage.test.tsx`

- [ ] **Step 1: Replace the old UI expectation with failing tests**

```typescript
it("exposes seven algorithm families and five search methods", async () => {
  render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);

  fireEvent.mouseDown(await screen.findByRole("combobox", { name: "算法家族" }));
  for (const label of [
    "LightGBM", "XGBoost", "CatBoost", "GBDT",
    "Random Forest", "Extra Trees", "HistGradientBoosting",
  ]) {
    expect(await screen.findByText(label, { selector: ".ant-select-item-option-content" })).toBeInTheDocument();
  }
  expect(screen.queryByText("LGB_v1 · LightGBM")).not.toBeInTheDocument();

  fireEvent.mouseDown(screen.getByRole("combobox", { name: "搜索方法" }));
  for (const label of ["网格搜索", "随机搜索", "贝叶斯优化", "进化算法", "多保真搜索"]) {
    expect(await screen.findByText(label, { selector: ".ant-select-item-option-content" })).toBeInTheDocument();
  }
});
```

Add a payload assertion:

```typescript
expect(api.post).toHaveBeenCalledWith("/training/automl/run", expect.objectContaining({
  algorithm_ids: ["random_forest"],
  search_method: "bayesian",
  max_trials: 20,
  time_budget: 600,
}));
expect(api.post.mock.calls[0][1]).not.toHaveProperty("candidate_ids");
```

Also test numeric defaults/ranges and classification/regression switching.

- [ ] **Step 2: Run the frontend test and verify RED**

From `ml-platform/frontend`:

```powershell
npm test -- --run src/pages/AutoMLPage.test.tsx
```

Expected: the page still exposes ten candidate versions and no search controls.

- [ ] **Step 3: Implement the controls and state**

```typescript
const AUTOML_ALGORITHM_OPTIONS = [
  { value: "lightgbm", label: "LightGBM" },
  { value: "xgboost", label: "XGBoost" },
  { value: "catboost", label: "CatBoost" },
  { value: "gbdt", label: "GBDT" },
  { value: "random_forest", label: "Random Forest" },
  { value: "extra_trees", label: "Extra Trees" },
  { value: "hist_gradient_boosting", label: "HistGradientBoosting" },
] as const;

const AUTOML_SEARCH_OPTIONS = [
  { value: "grid", label: "网格搜索" },
  { value: "random", label: "随机搜索" },
  { value: "bayesian", label: "贝叶斯优化" },
  { value: "evolutionary", label: "进化算法" },
  { value: "multi_fidelity", label: "多保真搜索" },
] as const;

const [algorithmIds, setAlgorithmIds] = useState<string[]>([]);
const [searchMethod, setSearchMethod] = useState("bayesian");
const [maxTrials, setMaxTrials] = useState(20);
const [timeBudget, setTimeBudget] = useState(600);
```

Use Ant Design `Select` and `InputNumber` with accessible labels, responsive stable widths, and the confirmed bounds. Submit the new fields and remove generic `candidate_ids`.

- [ ] **Step 4: Run frontend tests and verify GREEN**

```powershell
npm test -- --run src/pages/AutoMLPage.test.tsx
```

- [ ] **Step 5: Commit Task 5**

```powershell
git add -- ml-platform/frontend/src/pages/AutoMLPage.tsx ml-platform/frontend/src/pages/AutoMLPage.test.tsx
git commit -m "feat(automl): add family search controls"
```

---

### Task 6: Render Search Results and Reopen Modeling Task Results

**Files:**
- Modify: `ml-platform/frontend/src/pages/AutoMLPage.tsx`
- Modify: `ml-platform/frontend/src/pages/AutoMLPage.test.tsx`

- [ ] **Step 1: Write failing result-action tests**

Add a completed generic task test:

```typescript
it("reopens a completed generic AutoML result from the task table", async () => {
  const defaultGet = api.get.getMockImplementation();
  api.get.mockImplementation((url: string) => {
    if (url === "/training/jobs/automl-1") return Promise.resolve({ data: {
      id: "automl-1",
      status: "completed",
      metrics: {
        search: { method: "bayesian", max_trials: 20, time_budget: 600 },
        best_model: {
          algorithm_id: "random_forest",
          name: "Random Forest",
          score: 0.93,
          params: { n_estimators: 420 },
        },
        algorithm_results: [{
          algorithm_id: "random_forest",
          status: "completed",
          best_score: 0.93,
          best_params: { n_estimators: 420 },
        }],
        all_results: [{ name: "Random Forest", score: 0.93 }],
      },
    } });
    if (!defaultGet) throw new Error(`Unexpected GET ${url}`);
    return defaultGet(url);
  });

  render(<MemoryRouter><AntApp><AutoMLPage /></AntApp></MemoryRouter>);
  const projectSelect = (await screen.findAllByRole("combobox"))[0];
  fireEvent.mouseDown(projectSelect);
  fireEvent.click(await screen.findByText("Weld line"));
  fireEvent.click(await screen.findByRole("button", { name: "查看建模结果 automl-1" }));

  expect(await screen.findByText("Random Forest")).toBeInTheDocument();
  expect(screen.getByText("bayesian")).toBeInTheDocument();
});
```

Add a spot-weld test that asserts `getQualityRun("project-1", "quality-1")`, switches to the spot-weld tab, and restores report/chart state. Add tests for row-specific loading, active-task progress refresh, failed/cancelled rows without result actions, and detail-load failure preserving a previously displayed result.

- [ ] **Step 2: Run the frontend test and verify RED**

```powershell
npm test -- --run src/pages/AutoMLPage.test.tsx
```

Expected: result-action queries fail because the operation column only contains delete.

- [ ] **Step 3: Implement bounded search-result normalization and rendering**

Add helpers that accept `unknown` and return safe structures for `search`, `algorithm_results`, `best_model.params`, and legacy `all_results`. Render the search configuration and best model in an unframed summary band, followed by one compact family-results table. Do not place cards inside cards. Preserve existing legacy result and chart tabs.

Family columns are:

```typescript
const algorithmResultColumns = [
  { title: "算法", dataIndex: "algorithm_id", key: "algorithm" },
  { title: "状态", dataIndex: "status", key: "status" },
  { title: "最佳分数", dataIndex: "best_score", key: "score" },
  { title: "最佳参数", dataIndex: "best_params", key: "params" },
  { title: "完成", dataIndex: "completed_trials", key: "completed" },
  { title: "剪枝", dataIndex: "pruned_trials", key: "pruned" },
  { title: "失败", dataIndex: "failed_trials", key: "failed" },
];
```

Render parameter dictionaries as sorted `key=value` text with wrapping and an accessible full-value tooltip.

- [ ] **Step 4: Implement task-table result actions**

Import `EyeOutlined`, add a result-region ref, and track row loading:

```typescript
const [viewingTaskKey, setViewingTaskKey] = useState<string | null>(null);
const resultRegionRef = useRef<HTMLDivElement>(null);
```

Implement:

```typescript
const viewModelingTask = async (task: ModelingTask) => {
  const key = `${task.kind}-${task.id}`;
  setViewingTaskKey(key);
  try {
    if (task.kind === "spot-weld") {
      if (!selectedProject) return;
      const detail = await getQualityRun(selectedProject, task.id);
      setQualityRun(detail);
      setRecipeTab("spot-weld-quality");
    } else {
      const response = await apiClient.get(`/training/jobs/${task.id}`);
      setResults(response.data?.metrics || null);
      setRecipeTab("general");
      setActiveTab("results");
    }
    requestAnimationFrame(() => resultRegionRef.current?.scrollIntoView({ block: "start" }));
  } catch (error) {
    message.error(formatApiError(error, "建模结果加载失败"));
  } finally {
    setViewingTaskKey(null);
  }
};
```

Completed rows show `查看建模结果`. Active rows show `查看进度` and refresh persisted detail without presenting it as final. Failed and cancelled rows retain error and delete behavior only. Disable only the row currently loading.

- [ ] **Step 5: Run frontend tests and verify GREEN**

```powershell
npm test -- --run src/pages/AutoMLPage.test.tsx src/api/spotWeldQuality.test.ts
```

- [ ] **Step 6: Commit Task 6**

```powershell
git add -- ml-platform/frontend/src/pages/AutoMLPage.tsx ml-platform/frontend/src/pages/AutoMLPage.test.tsx
git commit -m "feat(automl): reopen modeling results"
```

---

### Task 7: Complete Regression Coverage, Documentation, and Verification

**Files:**
- Verify and repair only when a regression fails: `ml-platform/backend/app/services/automl_catalog.py`
- Verify and repair only when a regression fails: `ml-platform/backend/app/services/automl_search.py`
- Verify and repair only when a regression fails: `ml-platform/backend/app/services/automl_execution.py`
- Verify and repair only when a regression fails: `ml-platform/backend/app/api/training.py`
- Verify and repair only when a regression fails: `ml-platform/frontend/src/pages/AutoMLPage.tsx`
- Verify and repair only when a regression fails: the focused test files created or modified in Tasks 1-6
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Run focused backend verification**

From `ml-platform/backend`, isolate writable paths:

```powershell
$env:DATABASE_URL = "sqlite:///$((Join-Path $env:TEMP 'automl-search-focused.db') -replace '\\','/')"
$env:ARTIFACT_STORAGE_DIR = Join-Path $env:TEMP 'automl-search-artifacts'
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_catalog tests.test_automl_search tests.test_automl_tracking tests.test_training tests.test_suite_manifest -v
```

Expected: zero failures; record exact test and skip counts.

- [ ] **Step 2: Run focused frontend verification**

From `ml-platform/frontend`:

```powershell
npm test -- --run src/pages/AutoMLPage.test.tsx src/api/spotWeldQuality.test.ts src/weekAcceptance.test.ts
```

Expected: zero failures and no duplicate manifest registration.

- [ ] **Step 3: Run full local verification**

Backend:

```powershell
C:\Users\17723\miniconda3\python.exe -m compileall -q app tests
C:\Users\17723\miniconda3\python.exe run_suite.py
```

Frontend:

```powershell
npm test -- --run
npm run build
```

Repository:

```powershell
git diff --check
git status --short
```

Keep local evidence separate from Compose, real Celery/Redis/MLflow, Ubuntu, and remote CI evidence.

- [ ] **Step 4: Perform browser verification**

Start the existing backend and frontend development services on free ports. Verify desktop and mobile-width views for exactly seven generic families, all five methods, numeric bounds, dispatch and progress, family results, generic historical-result reopening, spot-weld historical-result reopening, and operation-column alignment without overlap. Record URLs and screenshot or browser-assertion evidence.

- [ ] **Step 5: Update project and shared experience records**

Append a dated `2026-08-17` entry to `DEVELOPMENT_PLAN.md` with current week, exact scope, red-green evidence, focused/full verification, affected files, known limitations, and remaining external acceptance.

Append one reusable entry under the project section of `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md` containing observed behavior, verified root cause, solution, verification, and prevention. Cover these conclusions:

- algorithm family identity is separate from parameter-version identity;
- backward-compatible JSON request migrations use explicitly supplied Pydantic fields and a persisted contract marker;
- historical result actions rehydrate from server persistence rather than browser memory;
- optional algorithm dependencies fail explicitly rather than silently changing model identity.

- [ ] **Step 6: Run final fresh verification after documentation edits**

Backend from `ml-platform/backend`:

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_catalog tests.test_automl_search tests.test_automl_tracking tests.test_suite_manifest -v
```

Frontend from `ml-platform/frontend`:

```powershell
npm test -- --run src/pages/AutoMLPage.test.tsx src/weekAcceptance.test.ts
npm run build
```

Repository root:

```powershell
git diff --check
```

Read the complete outputs before making any completion claim.

- [ ] **Step 7: Commit the verified final scope**

Confirm unrelated `OPTIMIZATION_PLAN.md`, `ml-platform/frontend/pnpm-lock.yaml`, and `tmp/report-media-20260730/` remain unstaged. Stage only reviewed AutoML, test, dependency, and project-document files:

```powershell
git status --short
git add -- DEVELOPMENT_PLAN.md ml-platform/backend/requirements.txt ml-platform/backend/app/services/automl_catalog.py ml-platform/backend/app/services/automl_search.py ml-platform/backend/app/services/automl_execution.py ml-platform/backend/app/api/training.py ml-platform/backend/tests/test_automl_catalog.py ml-platform/backend/tests/test_automl_search.py ml-platform/backend/tests/test_automl_tracking.py ml-platform/backend/tests/week_manifest.py ml-platform/frontend/src/pages/AutoMLPage.tsx ml-platform/frontend/src/pages/AutoMLPage.test.tsx
git diff --cached --check
git diff --cached --stat
git commit -m "feat(automl): add hyperparameter search"
```

The external shared experience file is not staged in this repository. Report its filesystem update separately.
