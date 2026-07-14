# Week 4 Industrial Template and Dual-Platform Delivery Design

**Date:** 2026-07-14

**Status:** Approved design, pending implementation plan

## 1. Goal

Deliver a stable first-month version in which four industrial welding templates execute end to end from real resistance-spot-welding data, one browser workflow is automated, and local deployment is supported on Windows and Ubuntu Linux.

## 2. Scope

Week 4 includes:

- Four executable industrial templates: weld quality prediction, fault-risk parameter analysis, anomaly detection, and full ML comparison.
- A deterministic preparation command for the real dataset at `C:\Users\17723\Desktop\resistance_spot_welding_dataset-main`.
- Backend E2E coverage for all four templates.
- One Playwright browser E2E covering the main quality-prediction workflow.
- Windows local deployment scripts and verification.
- Ubuntu 22.04/24.04 deployment scripts and GitHub Actions verification.
- Markdown deployment, user, demo, and acceptance documentation.

Week 4 does not include production queues, object storage, Docker acceptance, Kubernetes, or production model serving.

## 3. Architecture

All templates use one declarative template contract and the existing DAG execution path. No template-specific executor is introduced, and templates do not bypass the DAG by invoking `TrainingService` directly.

The delivery flow is:

1. Read the four external source files: `current.csv`, `voltage.csv`, `force.csv`, and `labels.csv`.
2. Validate row count, row identity, required fields, and the binary `Fault` target.
3. Extract deterministic time-series statistics into a compact feature table.
4. Store the generated table as a project dataset Artifact.
5. Instantiate one of the four templates with validated parameter overrides.
6. Execute through `DAGExecutor` using `OperatorContext` and `OperatorResult`.
7. Persist run status and expose metrics, logs, previews, and structured errors.
8. Validate all four templates through backend E2E and the primary flow through Playwright.

## 4. Dataset Preparation

The raw dataset remains outside the repository and is never modified. The preparation command accepts a source directory and an output path or project upload target.

### 4.1 Required source files

- `labels.csv`: `Car Body`, `Welding Spot`, `Date`, `Fault`
- `current.csv`: identity fields plus `Current T-0` through `Current T-999`
- `voltage.csv`: identity fields plus `Voltage T-0` through `Voltage T-999`
- `force.csv`: identity fields plus `Force T-0` through `Force T-999`

### 4.2 Validation rules

- All four files must exist and be readable.
- All files must have equal row counts.
- Identity fields must correspond row by row. Duplicate identity combinations are allowed because the source data contains repeated keys; row order is the authoritative sample alignment.
- `Fault` must contain only `0` and `1`, and both classes must be present.
- Time-series columns must be numeric after coercion and must contain at least one usable value.
- The source files are read-only inputs.

### 4.3 Generated features

For current, voltage, and force, generate at least:

- Mean, standard deviation, minimum, maximum, median, and range.
- Non-zero sample count and non-zero ratio.
- Peak position and peak value.
- First non-zero and last non-zero positions.
- Area under the normalized curve.

The generated table also contains the identity fields and `Fault`. Its metadata records source file SHA-256 values, source row count, generated field list, class distribution, generation timestamp, and preparation version.

Output is written to a temporary file, validated, and atomically moved into place.

## 5. Template Contract

Each template definition includes:

- Stable template ID, localized name, description, and scenario.
- Task type and target column.
- Required dataset columns.
- Nodes with registered operator IDs, valid parameters, and stable positions.
- Edges whose source and target ports exist on their operators.
- User-configurable parameter declarations.
- Required terminal outputs and metrics used by E2E assertions.

Instantiation validates the full definition before creating database records. Invalid definitions return a stable error and create no partial workflow.

## 6. Four Templates

### 6.1 Weld quality prediction

- Task: binary classification.
- Target: `Fault`.
- Flow: import, missing-value handling, feature scaling, stratified split, classifier training, classification evaluation.
- Required outputs: predictions, accuracy, fault-class recall, fault-class F1, and confusion matrix.

### 6.2 Fault-risk parameter analysis

- Task: binary classification.
- Target: `Fault`.
- Business meaning: identify process characteristics associated with fault risk. It does not claim to generate continuous process setpoints.
- Flow: import, feature selection/scaling, stratified split, interpretable classifier, evaluation, feature importance.
- Required outputs: fault probability or prediction, fault-class recall/F1, and ranked important features.

### 6.3 Anomaly detection

- Task: unsupervised anomaly detection with supervised comparison.
- Target usage: `Fault` is excluded from model input and used only for evaluation.
- Flow: import, feature scaling, anomaly scoring, thresholding, distribution/statistics, comparison with `Fault`.
- Required outputs: anomaly score, anomaly flag, anomaly rate, and fault hit rate.

### 6.4 Full ML comparison

- Task: binary classification.
- Target: `Fault`.
- Flow: shared preprocessing and stratified split, multiple classifiers, per-model evaluation, metric comparison, and selected best model.
- Required outputs: metrics for every candidate, best-model identity, fault-class recall/F1, and comparison visualization data.

## 7. Imbalanced Classification

The dataset contains substantially fewer fault samples than normal samples. Therefore:

- Train/test splitting is stratified.
- Classification templates report fault-class recall and F1 in addition to accuracy.
- Confusion matrices are required acceptance outputs.
- Models use deterministic random seeds.
- Class weighting is used where supported.
- Tests do not require a fragile exact score; they require finite metrics, both classes in evaluation data, and a minimum structural result contract.

## 8. Error Handling

Stable preparation errors cover missing directories, missing files, unreadable files, row-count mismatch, row-identity mismatch, invalid `Fault`, unusable features, and output-write failures.

Stable template errors cover unknown operators, invalid operator parameters, unknown ports, missing required input edges, incompatible task targets, and missing terminal outputs.

Execution failures preserve the workflow run, failed node, attempt, error code, bounded logs, and available previews. Source data remains unchanged, and partial generated output is removed or left outside the accepted output path.

## 9. Frontend Experience

The existing project and template workflow remains the primary UI. The template experience must:

- Present the four approved industrial templates.
- Show scenario, target, required data, and expected output before instantiation.
- Accept a prepared dataset Artifact rather than a server filesystem path.
- Create a workflow with valid nodes, edges, and parameter overrides.
- Reset progress before every run.
- Show run status, failed node errors, metrics, and result previews.
- Use complete Chinese and English labels.

No marketing landing page or separate template execution engine is added.

## 10. Testing and Acceptance

### 10.1 Unit and contract tests

- Dataset preparation validation and deterministic feature extraction.
- Atomic output behavior and metadata.
- Template IDs, task types, target columns, operators, parameters, ports, edges, and expected outputs.

### 10.2 Backend E2E

For every template:

1. Prepare features from the approved source dataset or a bounded subset preserving both classes.
2. Create a user and project in an isolated test database.
3. Create the dataset Artifact.
4. Instantiate the template.
5. Execute the workflow.
6. Assert terminal `completed` state and required outputs/metrics.

### 10.3 API E2E

Cover authentication, project creation, dataset preparation/upload, template instantiation, run creation, status polling, and result retrieval.

### 10.4 Browser E2E

Use Playwright for one quality-prediction main flow: login, create project, select template, attach prepared dataset, instantiate, run, and inspect completed results. Capture failures with trace and screenshot artifacts.

### 10.5 Regression gates

- Backend `python run_suite.py` passes.
- Frontend `npm test` passes.
- Frontend `npm run build` passes.
- Windows local startup and health checks pass.
- Ubuntu GitHub Actions workflow passes before Week 4 is marked complete.

## 11. Dual-Platform Delivery

### 11.1 Windows

Provide PowerShell or batch commands for environment checking, dependency installation, startup, stop, and health verification. Validate on the current Windows machine.

### 11.2 Ubuntu Linux

Support Ubuntu 22.04 and 24.04 with Bash scripts using Python 3.10+ and Node.js 18+. GitHub Actions executes backend tests, frontend tests, production build, service startup, and `/api/health` verification.

### 11.3 Portability rules

- Formal code contains no Windows drive paths or fixed Linux paths.
- Database, uploads, generated demo data, Artifact storage, and logs use configuration and project-relative defaults.
- Scripts handle spaces in paths and fail with actionable messages.
- Line endings and executable permissions are validated in CI.

## 12. Documentation Deliverables

- `docs/delivery/WINDOWS_DEPLOYMENT.md`
- `docs/delivery/UBUNTU_DEPLOYMENT.md`
- `docs/delivery/USER_GUIDE.md`
- `docs/delivery/DEMO_GUIDE.md`
- `docs/delivery/WEEK4_ACCEPTANCE.md`
- Updated `ml-platform/USAGE.md`
- Updated `DEVELOPMENT_PLAN.md`
- Updated shared development experience document

## 13. Completion Rule

Week 4 is complete only when all four templates execute successfully on prepared real-data features, backend and frontend regression gates pass, the Playwright main flow passes, Windows local verification passes, Ubuntu GitHub Actions passes, and all delivery documentation records evidence and remaining risks.

If Ubuntu CI cannot run because the repository has not been pushed or external CI is unavailable, Week 4 remains in progress and the missing evidence is recorded explicitly.
