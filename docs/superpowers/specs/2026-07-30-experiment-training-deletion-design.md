# Experiment and Training Deletion Design

## Goal

Add safe, project-authorized delete actions for Experiment and Training Job rows on the model-training page.

## Scope

- Add `DELETE /api/experiments/{experiment_id}`.
- Add typed frontend deletion clients for Experiment and Training Job resources.
- Add confirmed icon delete controls to Experiment and Training Job tables.
- Keep existing project authorization and audit semantics.

## Experiment Deletion

The platform Experiment record is deleted after `resource.delete` authorization succeeds. The action is audited as `experiment.delete` in the same database transaction.

Associated `TrainingJob` records are retained. Their nullable `experiment_id` relationship is set to `NULL`, consistent with its existing `ON DELETE SET NULL` foreign-key contract. This preserves job status, model lineage, logs, checkpoints, and existing MLflow run identifiers.

MLflow history is deliberately retained. The current tracking adapter has no transaction-safe delete operation, so deleting external history could leave the platform and tracking store inconsistent after a partial failure.

## Training Job Deletion

The page uses the existing `POST /api/training/batch-delete` contract with one job ID. The server remains authoritative: `running`, `queued`, and `cancel_requested` jobs are not deletable. The page shows the delete control only for other states and refreshes the table after the request.

## User Interface

Both tables use destructive icon buttons with tooltips, accessible names, and confirmation popups. The action columns remain right-fixed and non-wrapping so controls remain reachable on narrow viewports. Existing shared translations (`delete`, `confirm`, and `cancel`) are reused.

## Error Handling

API failures show the existing formatted error message. A training deletion response with `deleted: 0` is treated as a failed deletion attempt and the table is refreshed, covering a state transition that occurs between render and confirmation.

## Verification

- Backend API tests prove authorized Experiment deletion, denied deletion auditing, and retained Training Job records with a cleared `experiment_id`.
- Project write-audit completeness tests require `experiment.delete`.
- Frontend API tests verify exact DELETE and batch-delete request contracts.
- Training page tests verify confirmed Experiment and terminal Training Job deletion controls, and absence of a delete control for a running job.
- Relevant backend and frontend suites, production build, and whitespace checks run after implementation.
