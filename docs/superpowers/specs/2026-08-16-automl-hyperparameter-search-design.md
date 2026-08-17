# AutoML Hyperparameter Search Design

## 1. Goal

Upgrade generic AutoML from ten manually versioned candidates to seven user-facing algorithm families with five real hyperparameter-search strategies. Each selected family is optimized independently, the best trial from every family is compared, and the overall best fitted model continues through the existing artifact, MLflow, and model-library flow.

The AutoML task table also gains a result action so users can reopen completed generic AutoML and spot-weld modeling results after the original browser session has ended.

## 2. Confirmed Decisions

- The generic AutoML algorithm selector exposes exactly seven families: LightGBM, XGBoost, CatBoost, GBDT, Random Forest, Extra Trees, and HistGradientBoosting.
- `LGB_v1`, `LGB_v2`, and the other manually versioned candidates are not shown in the generic AutoML selector.
- Every selected algorithm family receives an independent search. The family winners are compared to choose the final model.
- The supported search methods are grid, random, Bayesian, evolutionary, and multi-fidelity search.
- Optuna is the single search engine. The backend pins `optuna==4.9.0`.
- The user configures one maximum-trial count, default `20`, range `5..200`.
- The backend also enforces one total wall-time budget, default `600` seconds, range `60..3600` seconds.
- Generic classification continues to optimize accuracy. Generic regression continues to optimize R2.
- Existing cross-validation behavior remains available with 3, 4, or 5 folds; disabling it uses the existing deterministic holdout evaluation.
- Historical jobs using `candidate_ids` remain executable and readable.
- Missing LightGBM, XGBoost, or CatBoost dependencies produce an explicit unavailable result. They are never silently replaced with GBDT.
- The spot-weld report recipe retains its ten fixed report candidates and does not enter generic dynamic hyperparameter search in this change.
- Completed modeling tasks can reopen their persisted results from the task table in the current page.

## 3. Scope Boundaries

### 3.1 Included

- Generic AutoML request validation, task persistence, execution, progress, MLflow lineage, artifact creation, and result rendering.
- Seven-family algorithm catalog with classification and regression estimators, typed search spaces, default parameters, and multi-fidelity resource axes.
- Five Optuna-backed search strategies.
- Backward compatibility for persisted `candidate_ids` jobs and existing result fields.
- Result reopening for generic AutoML and spot-weld task-table rows.
- Focused and full backend/frontend verification plus plan and experience updates.

### 3.2 Excluded

- Dynamic search for the spot-weld report-reproduction recipe.
- Distributed Optuna storage, multi-worker studies, or a separate Optuna dashboard.
- User-defined Python search spaces or arbitrary estimator imports.
- Changing the optimization metric, adding multi-objective UI, or model-size optimization.
- Database schema changes; `TrainingJob.params` and `TrainingJob.metrics` remain JSON storage boundaries.

## 4. Frontend Contract

### 4.1 Generic AutoML Form

The generic form adds these controls:

- `算法家族`: multi-select with seven family options. An empty selection means all seven families.
- `搜索方法`: single select with `grid`, `random`, `bayesian`, `evolutionary`, and `multi_fidelity`; default `bayesian`.
- `最大试验次数`: numeric input, default `20`, minimum `5`, maximum `200`.
- `总时间上限`: numeric input in seconds, default `600`, minimum `60`, maximum `3600`.
- Existing task type, input/target columns, experiment, cross-validation switch, and fold selector remain.

The frontend submits family IDs rather than versioned candidate IDs:

```json
{
  "algorithm_ids": ["lightgbm", "random_forest"],
  "search_method": "bayesian",
  "max_trials": 20,
  "time_budget": 600
}
```

The form must not send `candidate_ids` for a new search request. Switching between classification and regression preserves selected family IDs because all seven families support both task types.

### 4.2 Search Results

The generic result area displays:

- configured search method, maximum trials, and time budget;
- current or final budget-exhausted state;
- aggregate trial progress and the current algorithm family;
- one summary row per family with status, best score, best parameters, successful, pruned, and failed trial counts;
- the overall best family, score, parameters, training time, and existing feature-importance and comparison views;
- explicit family-level unavailable or failed messages.

Existing `best_model` and `all_results` rendering remains valid for historical tasks. New results enrich rather than remove those fields.

### 4.3 Modeling Task Result Action

The task-table operation column adds a result action alongside delete:

- completed generic AutoML row: label `查看建模结果`; fetch `/training/jobs/{job_id}`, select the generic tab, normalize the persisted metrics into the result state, and scroll/focus the result region;
- completed spot-weld row: label `查看建模结果`; fetch the existing project-scoped quality-run detail, select the spot-weld tab, and populate the existing quality result, charts, and report actions;
- queued, validating, pending, or running row: label `查看进度`; refresh the corresponding task detail and keep the result action disabled until persisted results exist;
- failed or cancelled row: keep the task-table error details and do not offer a result action;
- result loading has a row-specific busy state and reports structured API errors without clearing an already displayed result.

No new route or modal is introduced. Historical results reopen below the task table in the existing result regions.

## 5. API Contract

`POST /api/training/automl/run` accepts these new fields:

```json
{
  "algorithm_ids": ["lightgbm", "random_forest"],
  "search_method": "bayesian",
  "max_trials": 20,
  "time_budget": 600
}
```

Validation rules:

- `algorithm_ids` defaults to an empty list, interpreted as all seven families;
- family IDs must be unique and present in the server catalog;
- `search_method` must be one of the five stable method IDs;
- `max_trials` is `5..200`;
- `time_budget` is `60..3600` for new search requests;
- `algorithm_ids` and `candidate_ids` are mutually exclusive;
- legacy requests containing `candidate_ids` and no new search fields retain the old candidate execution path;
- unknown request fields remain rejected by Pydantic.

The request model retains the existing broad `time_budget` field range needed by historical callers, then applies the new `60..3600` minimum only when the new search contract is active. The API determines that contract from Pydantic's explicitly supplied field set rather than from post-validation default values: an explicit `algorithm_ids`, `search_method`, or `max_trials` selects the new path; a request with none of those fields selects the legacy path. This prevents default values from silently migrating old clients to Optuna.

The accepted configuration is frozen into `TrainingJob.params`. No public endpoint accepts estimator classes, import paths, arbitrary Python expressions, or unbounded parameter dictionaries.

## 6. Algorithm Catalog

A dedicated catalog module owns immutable family definitions. Each definition contains:

- stable family ID and display name;
- classifier and regressor factories;
- optional dependency name and availability probe;
- default parameters;
- typed search-space declarations for categorical, integer, float, and log-float parameters;
- a finite grid for grid search;
- the resource parameter and minimum/maximum resource values for multi-fidelity search;
- parameter normalization needed before estimator construction.

The catalog contains exactly:

| Family ID | Display name | Multi-fidelity resource |
|---|---|---|
| `lightgbm` | LightGBM | `n_estimators` |
| `xgboost` | XGBoost | `n_estimators` |
| `catboost` | CatBoost | `iterations` |
| `gbdt` | GBDT | `n_estimators` |
| `random_forest` | Random Forest | `n_estimators` |
| `extra_trees` | Extra Trees | `n_estimators` |
| `hist_gradient_boosting` | HistGradientBoosting | `max_iter` |

Factories always set deterministic seeds and bounded worker counts where supported. Optional-family factories raise a stable unavailable exception before a trial starts when the required package is absent.

## 7. Search Engine

### 7.1 Common Interface

The search service accepts the estimator family, task type, feature/target data, evaluation configuration, method, trial budget, wall-time slice, and progress callback. It returns a family result containing the best parameters, score, fitted estimator, feature importance, trial counters, duration, and safe error information.

Every trial:

1. receives parameters from the configured Optuna sampler;
2. constructs the exact selected-family estimator;
3. evaluates it with the configured cross-validation or holdout strategy;
4. reports intermediate values when multi-fidelity is active;
5. records state, score, parameters, duration, and safe failure code;
6. increments persisted job progress;
7. participates in family-best selection only when complete and finite.

After a family study finishes, the service builds and fits a fresh estimator with the best parameters on the full prepared dataset. This fitted estimator is the only family model eligible for final comparison and artifact persistence.

### 7.2 Method Mapping

- `grid`: Optuna `GridSampler(seed=42)`; deterministic seeded order; execute at most `max_trials`; if the finite grid is smaller, execute its actual size.
- `random`: Optuna `RandomSampler(seed=42)`.
- `bayesian`: Optuna `TPESampler(seed=42)` with bounded startup trials derived from `max_trials`.
- `evolutionary`: Optuna `NSGAIISampler(seed=42)` operating on the single current objective while preserving a future path to multiple objectives.
- `multi_fidelity`: Optuna `TPESampler(seed=42)` plus `HyperbandPruner`; each trial evaluates low, medium, and full resource rungs and calls `trial.report`/`trial.should_prune` between rungs.

Multi-fidelity rungs use approximately 25%, 50%, and 100% of the catalog resource maximum, clamped to valid integer values. Classical estimators may be rebuilt at each rung with identical non-resource parameters; correctness and clear pruning semantics take priority over estimator-specific warm-start behavior.

### 7.3 Time Allocation

The task has one monotonic deadline. Before each family starts, its allowed wall time is:

```text
remaining task seconds / remaining algorithm families
```

The value is recomputed after every family so unused time flows to later families and one slow family cannot consume the whole task budget. No new trial starts after the family slice or task deadline. A trial already running is allowed to finish because the current thread/Celery execution model cannot safely kill arbitrary estimator code.

## 8. Progress and Result Persistence

`TrainingJob.metrics.progress` becomes:

```json
{
  "completed": 17,
  "total": 40,
  "percent": 42.5,
  "current_algorithm": "random_forest",
  "current_trial": 7,
  "search_method": "bayesian",
  "budget_exhausted": false
}
```

Progress counts terminal trials, including complete, pruned, and failed trials. For grid search, `total` uses the catalog's actual capped combination count. Other methods use selected family count multiplied by `max_trials`. Multi-fidelity rungs do not increase the trial total.

The final metrics retain `best_model`, `all_results`, `feature_importance`, and `progress`, and add:

```json
{
  "search": {
    "method": "bayesian",
    "max_trials": 20,
    "time_budget": 600,
    "budget_exhausted": false
  },
  "algorithm_results": [
    {
      "algorithm_id": "random_forest",
      "status": "completed",
      "best_score": 0.9312,
      "best_params": {"n_estimators": 420, "max_depth": 18},
      "completed_trials": 19,
      "pruned_trials": 0,
      "failed_trials": 1,
      "training_time_seconds": 42.3
    }
  ]
}
```

The database stores family summaries rather than every full trial record. MLflow stores detailed trial parameters, score, duration, state, family, search method, and lineage.

## 9. MLflow and Model Artifact Lineage

The existing AutoML job remains the MLflow parent run. Each Optuna trial is one child run tagged with:

- `platform.algorithm_family`;
- `platform.search_method`;
- `platform.trial_number`;
- `platform.trial_state`;
- `platform.run_type=automl_trial`.

The parent run receives the search configuration, family summaries, best family, best child run ID, budget-exhausted state, and terminal status. Failed and pruned trials close with explicit states and do not become model artifacts.

Only the overall best freshly fitted estimator is serialized through the existing controlled artifact service and registered in `ModelLibrary`. Its algorithm field uses the stable family display name, while its metrics include the exact best parameters and search provenance.

## 10. Failure Handling

Stable codes include:

- `AUTOML_SEARCH_CONFIG_INVALID`: invalid method, family ID, budget, or conflicting old/new fields;
- `AUTOML_ALGORITHM_UNAVAILABLE`: selected optional package is not installed;
- `AUTOML_SEARCH_TRIAL_FAILED`: one trial failed safely;
- `AUTOML_ALGORITHM_SEARCH_FAILED`: one family produced no successful trial;
- `AUTOML_ALL_ALGORITHMS_FAILED`: every selected family failed or was unavailable.

A family failure does not stop later families. If at least one trial succeeds, the task may complete using the best available result. Deadline exhaustion after a success is a completed task with `budget_exhausted=true`; deadline exhaustion before any success contributes a family failure and may lead to `AUTOML_ALL_ALGORITHMS_FAILED`.

Safe API and persisted error messages never include credentials, storage paths, raw dataset values, estimator object representations, or unrestricted dependency tracebacks.

## 11. Backward Compatibility

- Existing `candidate_ids` values, including legacy aliases, remain resolved by the existing candidate path.
- Existing pending or recovered jobs with `candidate_ids` do not enter Optuna search.
- New jobs never persist versioned candidate IDs.
- Existing task-list and job-detail endpoints remain the sources for reopening generic results.
- Existing quality-run detail and artifact endpoints remain the sources for reopening spot-weld results.
- Existing consumers of `best_model` and `all_results` continue to work.
- No database migration or historical JSON rewrite is required.

## 12. Testing Strategy

Implementation follows red-green-refactor. Each behavior receives a failing focused test before production code changes.

### 12.1 Backend

- catalog contains exactly seven unique stable family IDs;
- every available family builds classification and regression estimators with deterministic settings;
- missing optional dependencies return unavailable rather than a fallback estimator;
- every search method creates the intended sampler/pruner;
- grid order and `max_trials` cap are deterministic;
- random, TPE, and NSGA-II use fixed seeds;
- multi-fidelity reports rungs and can prune a weak trial;
- each family has an independent study and contributes at most one family winner;
- final comparison selects the highest finite score with deterministic tie-breaking;
- trial progress counts success, prune, and failure;
- dynamic time slicing prevents the first family from taking the whole remaining budget;
- partial family failure, deadline exhaustion, and all-family failure use the specified terminal behavior;
- new API validation, persistence, permissions, audit behavior, and dispatch remain correct;
- old `candidate_ids` API and persisted execution tests remain green;
- artifact, MLflow lineage, and ModelLibrary registration identify the true selected family and parameters.

### 12.2 Frontend

- generic algorithm selector renders exactly seven families and no versioned candidates;
- search selector renders five methods with Bayesian default;
- numeric controls enforce the confirmed defaults and ranges;
- submission sends `algorithm_ids`, `search_method`, `max_trials`, and `time_budget`, and omits `candidate_ids`;
- progress, family summaries, best parameters, unavailable state, and budget exhaustion render correctly;
- completed generic task result action fetches job detail and displays persisted metrics;
- completed spot-weld task result action fetches quality detail and restores quality results;
- running, failed, and cancelled task rows expose only the allowed actions;
- result-loading failure preserves the previously displayed result;
- the new frontend test file coverage is registered exactly once in `weekAcceptance.test.ts`.

### 12.3 Verification Gates

- focused AutoML backend tests using `C:\Users\17723\miniconda3\python.exe` and isolated SQLite/DataBus paths;
- focused AutoML frontend Vitest tests;
- complete backend `run_suite.py`;
- complete frontend Vitest suite;
- frontend production build;
- Python compile check and `git diff --check`;
- manual browser verification of seven-family selection, all five method controls, task progress, historical generic result reopening, and historical spot-weld result reopening.

Local evidence is reported separately from Compose, real Celery/Redis/MLflow, target Ubuntu, and remote CI evidence.

## 13. Documentation and Delivery

After implementation:

- update `DEVELOPMENT_PLAN.md` with implementation status, verification evidence, failures, risks, and remaining external acceptance;
- append reusable observations, root causes, solutions, verification, and prevention measures to `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`;
- preserve unrelated dirty-worktree and generated files;
- stage and commit only reviewed AutoML, tests, dependency, and documentation scope unless the user requests broader publication.
