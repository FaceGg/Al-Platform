# Spot-Weld Optuna Unification Design

Date: 2026-08-17

## Goal

Replace every fixed-candidate AutoML path in spot-weld quality perception and label-snapshot training with the same seven algorithm families and five Optuna search methods used by generic AutoML.

The migration is intentionally breaking. New and existing spot-weld execution code will not retain the ten `candidate_ids` configurations, the fixed `AutoML(LGB_v2)` snapshot candidate, or the three fixed MLP snapshot candidates.

## User-Facing Contract

The spot-weld quality form exposes four independent controls:

- algorithm families: `lightgbm`, `xgboost`, `catboost`, `gbdt`, `random_forest`, `extra_trees`, `hist_gradient_boosting`;
- search method: `grid`, `random`, `bayesian`, `evolutionary`, or `multi_fidelity`;
- maximum trials, from 5 through 200;
- total time budget, from 60 through 3600 seconds.

An empty algorithm selection means all seven families. The UI defaults are Bayesian search, 20 trials per family, and a 600-second total budget. Generic AutoML and spot-weld quality maintain separate form state so switching tabs cannot silently copy a configuration between different workflows.

The spot-weld create and validate requests accept `algorithm_ids`, `search_method`, `max_trials`, and `time_budget`. They no longer accept or return `candidate_ids` or `selected_candidate_ids`.

## Shared Architecture

`automl_catalog.py` remains the single source of truth for family identity, optional dependency checks, estimator construction, search spaces, and resource parameters.

`automl_search.py` remains the single Optuna orchestration layer. It will support a bounded evaluator callback so the generic workflow can retain its existing scorer while spot-weld quality supplies its classification-specific evaluator. Sampling, pruning, deadlines, terminal-trial accounting, deterministic family ordering, and unavailable-dependency behavior stay shared.

The spot-weld evaluator uses stratified cross-validation or the existing deterministic stratified holdout. Its Optuna objective is mean macro ROC-AUC. For each family winner it also records mean macro F1, AUC/F1 standard deviations, feature importance, elapsed time, and best parameters.

Family searches run independently. A failed or unavailable family remains visible and does not stop later families. The task fails only when no family completes successfully. The overall winner is selected by mean AUC, then mean F1, then immutable catalog order.

## Quality-Run Data Flow

The create endpoint validates the four search fields before queueing and stores the resolved values in `SpotWeldQualityRun.input_fingerprint`:

```json
{
  "search_contract": "optuna_v1",
  "algorithm_ids": ["lightgbm", "random_forest"],
  "search_method": "bayesian",
  "max_trials": 20,
  "time_budget": 600
}
```

Execution performs the existing dataset validation and feature extraction, then allocates the wall-time budget across the remaining selected families. Trial callbacks persist bounded progress in `statistics.modeling_progress`; the search configuration and budget state are persisted in `statistics.search`.

`automl_results` becomes a family-result collection. Each row includes:

- `algorithm_id` and display `name`;
- `status` and stable error information;
- `best_score`, `auc`, `f1`, `auc_std`, and `f1_std`;
- `best_params`;
- completed, pruned, and failed trial counts;
- training time and feature importance.

The winning family parameters are used for the existing clustering, automatic labeling, final model fitting, report generation, and model-library registration. Persisted model metadata records the stable algorithm ID, best parameters, search method, selected families, and originating quality-run ID.

## Snapshot Training

Snapshot training resolves the search configuration from the originating quality run and searches again against the snapshot's reviewed labels. This retraining is required because label distributions can differ from automatic labels.

The fixed `SNAPSHOT_TRAINING_CONFIGS`, fixed LightGBM configuration, and fixed MLP candidates are removed. Snapshot output and report sheets retain their existing roles, but their candidate table contains the seven-family search results and their best parameters. The registered model backbone is the winning algorithm family rather than a legacy candidate name.

## Removal Scope

The implementation removes:

- `AUTOML_CONFIGS` and `select_automl_configs`;
- the spot-weld `candidate_ids` API and frontend types;
- the old model-type builder used only by fixed candidates;
- `SNAPSHOT_TRAINING_CONFIGS` and fixed MLP snapshot comparison;
- tests and visible copy that refer to `LGB_v1`, `LGB_v2`, `RF_v1`, or other versioned candidates.

No database migration is required because the request contract, search configuration, progress, and result details use existing JSON columns. Existing rows that only contain the removed legacy configuration are outside the supported execution and rendering contract.

## Errors And Budgets

Invalid families or search parameters fail before queueing with `QUALITY_AUTOML_SEARCH_CONFIG_INVALID`. Missing optional model packages produce a family-level unavailable result. Trial errors produce bounded family-level failure details without serializing estimator objects or unbounded tracebacks.

The total time budget is monotonic and shared across families. A third-party estimator already running when the deadline expires may finish; no thread or Celery worker is force-killed. The persisted result must distinguish a fully completed search from budget exhaustion.

## Testing And Acceptance

Development follows RED-GREEN TDD for:

- spot-weld request validation and persisted search configuration;
- all seven family IDs and all five search methods;
- family failure isolation, missing optional dependencies, deadlines, progress, and deterministic winner selection;
- point-weld AUC/F1 metrics and best-parameter model fitting;
- snapshot retraining with the originating search configuration;
- removal of legacy candidate fields and UI options;
- task-result reopening with the new family result schema;
- report and model-library provenance.

Final acceptance includes focused and full backend/frontend tests, Python compilation, the Vite production build, WSL Linux execution, WSL Docker Compose build/start/readiness, a real authenticated spot-weld request-contract check, `git diff --check`, and remote GitHub Actions. Local, WSL/Compose, and remote-CI evidence remain separate.
