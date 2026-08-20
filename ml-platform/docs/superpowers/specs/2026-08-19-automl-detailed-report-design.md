# AutoML Detailed Report Design

## Goal

Generate a persisted, project-scoped report from a completed AutoML job and show a five-tab preview on the task page.

## Contract

- `POST /api/training/jobs/{job_id}/automl-report` generates or reuses the latest valid report.
- `GET /api/training/jobs/{job_id}/automl-report/artifacts/{artifact_key}` downloads an allowlisted artifact.
- The ZIP contains exactly `AutoML全流程报告.xlsx`, `automl_results.csv`, `automl_comparison.png`, `feature_importance_automl.png`, and `clustering_automl.png`.
- The workbook contains exactly `总览`, `AutoML选型`, `聚类画像`, `特征重要性`, and `推理结果`.

## Analysis

Feature importance is taken from the best model using `feature_importances_`, absolute `coef_`, then deterministic permutation importance. Standardized features are multiplied by the square root of normalized importance weights; KMeans searches K=2..8 by silhouette score and breaks ties toward the smaller K.

The report manifest is stored in a reassigned `TrainingJob.metrics` value and includes a source fingerprint, artifact IDs, and a preview limited to 100 inference rows. Artifact downloads remain project-authorized and use a fixed key allowlist.
