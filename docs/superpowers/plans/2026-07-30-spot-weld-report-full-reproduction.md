# 点焊质量报告最小改动复现 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有智擎平台内，以报告同结构的 CSV/XLSX 为输入，复现 73 维特征、10 组 AutoML、加权聚类、规则弱监督、四级预警、标签快照训练和 8 Sheet XLSX 结果；补齐算法集合选择、工作流特征工程、标注导出和样本队列滚动。

**Architecture:** 复用既有 `spot_weld_features.py`、`spot_weld_quality.py`、通用 AutoML、`ArtifactService`、标签修订/快照表和现有 `DataAnnotationPage`。不新建独立质量服务、数据源适配器、页面、数据库表或 Alembic 迁移；新增逻辑只进入现有 API、服务函数、工作流算子和页面控件。

**Tech Stack:** React 18, TypeScript, Ant Design, ECharts, FastAPI, SQLAlchemy, pandas, NumPy, scikit-learn, LightGBM/XGBoost/CatBoost, openpyxl.

---

## 0. 已复用能力与边界

| 报告阶段 | 现有实现 | 本计划动作 |
|---|---|---|
| CSV/XLS/XLSX 上传和项目隔离 | 数据管理、`read_report_dataset()`、ArtifactService | 直接复用；不接入报告中的私有 PostgreSQL |
| 4 通道 Base64 大端序波形、73 维特征 | `spot_weld_features.py` | 直接复用；仅封装为工作流算子 |
| 10 组候选、3 折 AUC/F1、加权 KMeans | `AUTOML_CONFIGS`、`run_automl()`、`run_clustering()` | 增加用户选择候选集合，默认保留全部 10 组 |
| 规则弱标注和四级预警 | `apply_report_v1_rules()`、`warning_level()` | 直接复用 |
| 4 模型、5 折训练和 8 Sheet XLSX | `run_snapshot_training()`、`_write_snapshot_report()` | 复用；允许从已保存自动标签创建明确标识的“报告复现”快照 |
| 人工标签、审核、修订历史、模型血缘和预警 | 现有质量 API、DataAnnotation、ModelLibrary、Monitor | 直接复用；只增加标注导出和滚动体验 |

**不做的改动：** 不增加私有数据库连接字符串、不新建登录态或权限模型、不重建训练调度、不新建“特征工程”页面、不新增持久化模型或迁移、不创建第二套报表/制品服务。

**数值验收边界：** 1875 条同源数据到位前，只能验收算法流程和结果结构。模拟数据必须带 `synthetic` 来源标识，不能宣称复现报告中的 `LGB_v2`、AUC、366 条告警或 `K=2` 固定数值。拿到同结构 CSV/XLSX 后，使用现有上传入口执行相同工作流，再比较数值。

## 1. 文件边界

- Modify: `ml-platform/backend/app/services/automl_execution.py` - 通用 AutoML 候选目录和按 ID 解析。
- Modify: `ml-platform/backend/app/api/training.py` - 请求校验并将通用候选 ID 存入既有 `TrainingJob.params`。
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py` - 质量候选集选择、自动标签快照来源和标注导出字节流。
- Modify: `ml-platform/backend/app/api/spot_weld_quality.py` - 扩展既有运行/快照请求及新增导出路由。
- Modify: `ml-platform/backend/app/operators/processing.py` - 新增一个 `spot_weld_feature_engineering` 算子。
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.ts` - 运行候选和标注导出 typed API。
- Modify: `ml-platform/frontend/src/pages/AutoMLPage.tsx` - 通用 AutoML 和点焊质量配方的算法集合多选。
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx` - 自动标签复现快照来源和 CSV/XLSX 导出菜单。
- Modify: `ml-platform/frontend/src/styles/global.css` - 样本队列的稳定纵向滚动区域。
- Modify tests: `backend/tests/test_automl_tracking.py`, `test_training_tasks.py`, `test_spot_weld_quality_service.py`, `test_api_spot_weld_quality.py`, `test_all_operators.py`, `frontend/src/pages/AutoMLPage.test.tsx`, `DataAnnotationPage.test.tsx`.

## 2. Task 1: Allow generic AutoML to select its existing algorithm set

**Files:** `backend/app/services/automl_execution.py`, `backend/app/api/training.py`, `frontend/src/pages/AutoMLPage.tsx`, and their existing tests.

- [x] **Step 1: Add failing API/executor tests**

```python
def test_automl_rejects_unknown_candidate_id(self):
    response = self.client.post("/api/training/automl/run", json={
        "project_id": str(self.project.id),
        "experiment_id": str(self.experiment.id),
        "dataset_artifact_id": str(self.dataset.id),
        "target_column": "quality",
        "task": "classification",
        "candidate_ids": ["does_not_exist"],
    })
    self.assertEqual(response.status_code, 400)
    self.assertEqual(response.json()["detail"]["code"], "AUTOML_CONFIG_INVALID")

def test_automl_uses_persisted_candidate_subset(self):
    job = self._create_job(params={"task": "regression", "candidate_ids": ["linear_regression"]})
    execute_automl_job(job.id, dependencies=self.dependencies)
    self.assertEqual([item["name"] for item in job.metrics["all_results"]], ["linear_regression"])
```

- [x] **Step 2: Verify the red state**

```powershell
Set-Location E:/codex_workspace/agent_spot_welding/.worktrees/spot-weld-quality/ml-platform/backend
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_automl_tracking tests.test_training_tasks -v
```

Expected: candidate IDs are rejected as extra fields or ignored by the executor.

- [x] **Step 3: Implement a single candidate resolver**

In `automl_execution.py`, keep `default_candidates(task)` as the catalog and add:

```python
def resolve_candidates(task: str, candidate_ids: Sequence[str] | None = None) -> tuple[AutoMLCandidate, ...]:
    catalog = {candidate.name: candidate for candidate in default_candidates(task)}
    requested = tuple(candidate_ids or ())
    if len(set(requested)) != len(requested) or any(name not in catalog for name in requested):
        raise ValueError("AUTOML_CONFIG_INVALID")
    return tuple(catalog[name] for name in requested) if requested else tuple(catalog.values())
```

Extend `AutoMLRunRequest` with `candidate_ids: list[str] = Field(default_factory=list, max_length=3)`. In `start_automl`, call `resolve_candidates(data.task, data.candidate_ids)` before creating the job and persist the ordered list in existing `TrainingJob.params`. In `execute_automl_job`, use the injected test candidates when supplied; otherwise call `resolve_candidates(task, params.get("candidate_ids"))`. Convert the resolver `ValueError` into the existing `AUTOML_CONFIG_INVALID` 400 response.

- [x] **Step 4: Add the existing options to the page**

Define the task-specific option lists once in `AutoMLPage.tsx`; add an Ant Design `Select mode="multiple"` labelled “算法集合”. Keep an empty selection as “all current defaults”, remove IDs invalid for a newly selected task, and send `candidate_ids` with the current project, experiment, dataset, target and task fields. Do not alter the existing dataset selector, experiment creation or polling flow.

- [x] **Step 5: Verify and commit**

```powershell
Set-Location ../frontend
& C:/Users/17723/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd exec vitest run src/pages/AutoMLPage.test.tsx
& C:/Users/17723/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd run build
Set-Location ..
git add ml-platform/backend/app/services/automl_execution.py ml-platform/backend/app/api/training.py ml-platform/backend/tests/test_automl_tracking.py ml-platform/backend/tests/test_training_tasks.py ml-platform/frontend/src/pages/AutoMLPage.tsx ml-platform/frontend/src/pages/AutoMLPage.test.tsx
git commit -m "feat: select AutoML candidates"
```

Expected: omitted selections retain current behavior, selected IDs remain ordered in the job, and unsupported/duplicated IDs are rejected before dispatch.

## 3. Task 2: Reuse the report quality pipeline with selectable candidates and automatic-label snapshots

**Files:** `backend/app/services/spot_weld_quality.py`, `backend/app/api/spot_weld_quality.py`, `frontend/src/api/spotWeldQuality.ts`, `AutoMLPage.tsx`, `DataAnnotationPage.tsx`, quality tests.

- [ ] **Step 1: Write failing quality-contract tests**

```python
def test_quality_run_persists_selected_report_candidates(self):
    run = create_quality_run_record(
        self.db, project_id=self.project.id, user_id=self.user.id,
        dataset_artifact_id=self.dataset.id, candidate_ids=["LGB_v2", "RF_v1"],
        artifact_service=self.artifacts,
    )
    self.assertEqual(run.input_fingerprint["selected_candidate_ids"], ["LGB_v2", "RF_v1"])
    execute_quality_run(self.db, run.id, artifact_service=self.artifacts)
    self.assertEqual([row["name"] for row in run.automl_results], ["LGB_v2", "RF_v1"])

def test_automatic_snapshot_keeps_saved_rule_labels_distinct_from_human_labels(self):
    response = self.client.post(snapshot_url, json={"name": "report-v1-auto", "label_source": "automatic"})
    self.assertEqual(response.status_code, 201)
    snapshot = self.db.query(SpotWeldLabelSnapshot).one()
    self.assertTrue(all(item["source"] == "automatic" for item in snapshot.labels))
```

- [ ] **Step 2: Verify the red state**

```powershell
Set-Location E:/codex_workspace/agent_spot_welding/.worktrees/spot-weld-quality/ml-platform/backend
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_spot_weld_quality_service tests.test_api_spot_weld_quality -v
```

Expected: a quality request accepts no candidate selection and a snapshot can only select human-approved labels.

- [ ] **Step 3: Persist the quality run configuration without a migration**

Add `candidate_ids` to the existing `DatasetQualityRequest`. In `spot_weld_quality.py`, add `select_automl_configs(candidate_ids)` which validates a unique ordered subset of `AUTOML_CONFIGS`, returning all ten configurations for an empty list. Pass `candidate_ids` through `create_quality_run_record()` and store it in the existing `input_fingerprint` JSON as `selected_candidate_ids`; add the same value to `_serialize_run()`.

In `execute_quality_run()`, resolve `run.input_fingerprint.get("selected_candidate_ids")` and pass the result as the existing `configs=` argument to `run_automl()`. Keep `_fit_candidate_model()` on the canonical `AUTOML_CONFIGS` lookup so its persisted best candidate is reproducible. This requires no table, migration or dispatcher change.

- [ ] **Step 4: Reuse snapshots for the report's four-model training stage**

Extend `SnapshotRequest` with `label_source: Literal["approved", "automatic"] = "approved"`. Preserve the current approved-only query for `approved`; for `automatic`, query completed samples with non-null `automatic_label`, write each existing label into `SpotWeldLabelSnapshot.labels` with `source: "automatic"`, and retain `revision_id: null`. Add `label_source` to the existing audit changes and to the model/report lineage derived from the snapshot JSON.

The existing `run_snapshot_training()` and `_write_snapshot_report()` already run `AutoML(LGB_v2)`, two fusion MLPs and the table-only MLP with 5-fold validation, create the model, and write all eight required sheets. Do not create a second deep-learning service. The UI must label automatic snapshots “报告复现自动标签”, never “已人工审核”.

- [ ] **Step 5: Add only configuration controls to existing pages**

In the point-weld tab of `AutoMLPage.tsx`, add a multi-select labelled “报告候选算法” with the ten names from `AUTOML_CONFIGS`; send `candidate_ids` only to `createQualityRun()`. In `DataAnnotationPage.tsx`, add a select labelled “快照标签来源” beside the existing snapshot name: `approved` defaults to the current audited-label behavior; `automatic` is the explicit report-reproduction route. Change the existing “模拟数据” control into a compact menu that calls the existing `createQualityDemoDataset(projectId, 60)` for a quick sample or `createQualityDemoDataset(projectId, 1875)` for report reproduction; the existing API limit already permits both values. Use the existing quality run table, monitor warning counts, model-library quality tab and 8-sheet report download instead of a new dashboard.

- [ ] **Step 6: Verify and commit**

```powershell
Set-Location E:/codex_workspace/agent_spot_welding/.worktrees/spot-weld-quality/ml-platform/backend
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_spot_weld_quality_service tests.test_api_spot_weld_quality -v
Set-Location ../frontend
& C:/Users/17723/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd exec vitest run src/pages/AutoMLPage.test.tsx src/pages/DataAnnotationPage.test.tsx
git add ../backend/app/services/spot_weld_quality.py ../backend/app/api/spot_weld_quality.py ../backend/tests/test_spot_weld_quality_service.py ../backend/tests/test_api_spot_weld_quality.py src/api/spotWeldQuality.ts src/pages/AutoMLPage.tsx src/pages/DataAnnotationPage.tsx src/pages/AutoMLPage.test.tsx src/pages/DataAnnotationPage.test.tsx
git commit -m "feat: configure report quality reproduction"
```

Expected: a 1875-row report-structured simulated dataset can use all ten or a selected subset, generate saved automatic weak labels, then generate a clearly sourced snapshot model and the existing eight-sheet report.

## 4. Task 3: Add one workflow feature-engineering operator

**Files:** `backend/app/operators/processing.py`, `backend/tests/test_all_operators.py`.

- [ ] **Step 1: Write a failing operator test**

```python
def test_spot_weld_feature_engineering_reuses_report_feature_contract(self):
    frame = build_demo_report_frame(12)
    outputs = execute_operator(
        OperatorRegistry.get("spot_weld_feature_engineering"),
        {"data": frame.to_dict(orient="records")}, {},
    )
    self.assertEqual(len(outputs["features"]), 12)
    self.assertEqual(len(outputs["schema"]["columns"]), 73)
    self.assertEqual(outputs["statistics"]["feature_count"], 73)
```

- [ ] **Step 2: Verify the red state**

```powershell
Set-Location E:/codex_workspace/agent_spot_welding/.worktrees/spot-weld-quality/ml-platform/backend
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_all_operators -v
```

Expected: `OperatorRegistry.get("spot_weld_feature_engineering")` is absent.

- [ ] **Step 3: Implement the thin operator wrapper**

Append this class to `processing.py`; do not duplicate decoding or formulas:

```python
@register_operator
class SpotWeldFeatureEngineering(BaseOperator):
    id = "spot_weld_feature_engineering"
    name = "Spot Weld Feature Engineering"
    category = "processing"
    description = "Decode four report waveforms and produce the fixed 73-feature schema"
    inputs = [PortSpec("data", "DataTable", "Report Data")]
    outputs = [
        PortSpec("features", "DataTable", "73 Feature Data"),
        PortSpec("schema", "JSON", "Feature Schema"),
        PortSpec("statistics", "JSON", "Feature Statistics"),
    ]
    parameters = []

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        frame = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
        features, schema, statistics = build_feature_frame(frame)
        return OperatorResult(outputs={
            "features": features.to_dict(orient="records"),
            "schema": {"columns": schema},
            "statistics": statistics,
        })
```

Import `build_feature_frame` at module scope. Let its stable `QualityPipelineError` propagate through the existing workflow error path; do not invent an alternate report parser or state store.

- [ ] **Step 4: Verify and commit**

```powershell
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_all_operators tests.test_spot_weld_features -v
git add ml-platform/backend/app/operators/processing.py ml-platform/backend/tests/test_all_operators.py
git commit -m "feat: add spot weld feature workflow operator"
```

Expected: the operator exposes exactly 73 ordered feature columns and existing input validation remains the source of truth.

## 5. Task 4: Export persisted annotations and make the queue scroll

**Files:** `backend/app/services/spot_weld_quality.py`, `backend/app/api/spot_weld_quality.py`, `frontend/src/api/spotWeldQuality.ts`, `DataAnnotationPage.tsx`, `global.css`, quality API/page tests.

- [ ] **Step 1: Write failing export and layout tests**

```python
def test_annotation_export_contains_current_labels_and_revision_history(self):
    response = self.client.get(f"/api/projects/{self.project.id}/spot-weld/runs/{self.run.id}/annotations/export?format=xlsx")
    self.assertEqual(response.status_code, 200, response.text)
    workbook = load_workbook(BytesIO(response.content), read_only=True)
    self.assertEqual(workbook.sheetnames, ["标注样本", "标签修订", "标签快照"])
    self.assertIn("current_label", list(workbook["标注样本"].values)[0])

def test_annotation_export_is_project_scoped(self):
    response = self.client.get(f"/api/projects/{self.other.id}/spot-weld/runs/{self.run.id}/annotations/export?format=csv")
    self.assertEqual(response.status_code, 404)
```

```tsx
expect(await screen.findByRole("button", { name: "导出标注" })).toBeInTheDocument();
expect(globalCss).toContain(".spot-weld-annotation__sample-list");
expect(globalCss).toContain("overflow-y: auto");
```

- [ ] **Step 2: Verify the red state**

```powershell
Set-Location E:/codex_workspace/agent_spot_welding/.worktrees/spot-weld-quality/ml-platform/backend
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_api_spot_weld_quality -v
Set-Location ../frontend
& C:/Users/17723/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd exec vitest run src/pages/DataAnnotationPage.test.tsx
```

Expected: the export route and export control are absent; the list has no constrained vertical scroll region.

- [ ] **Step 3: Build export content from existing persistence**

In `spot_weld_quality.py`, add `build_annotation_export(run, db, format)` that queries existing `SpotWeldQualitySample`, `SpotWeldLabelRevision`, and `SpotWeldLabelSnapshot` rows. Emit:

```text
标注样本: source_row_index, display_id, automatic_label, current_label, current_note,
          review_status, warning_level, defect_probability, cluster_id, rule_hits, current_revision_id
标签修订: revision_id, sample_id, author_id, label, note, action, decision, review_comment,
          parent_revision_id, created_at
标签快照: snapshot_id, name, label_source, sample_id, label, revision_id, created_at
```

For CSV, export `标注样本` only. For XLSX, write the three named sheets with `pd.ExcelWriter(..., engine="openpyxl")`. Use `BytesIO` and return bytes; do not create a second Artifact row for a transient user download.

Add `GET /runs/{run_id}/annotations/export?format=csv|xlsx` to `spot_weld_quality.py` API after the existing project-read check. Return a `StreamingResponse` with a fixed content type and `Content-Disposition`; reject every other format with `QUALITY_ANNOTATION_EXPORT_FORMAT_INVALID`.

- [ ] **Step 4: Add a compact existing-page download action**

Add `downloadQualityAnnotationExport(projectId, runId, format)` to `spotWeldQuality.ts`. In `DataAnnotationPage.tsx`, use one `DownloadOutlined` “导出标注” button with an Ant Design `Dropdown` menu containing CSV and XLSX. Download through a Blob URL and revoke it after clicking. Show it only after a project and run are selected; keep all labels sourced from the existing run, never from client-side state.

Set the existing list style to a bounded scrolling region:

```css
.spot-weld-annotation__sample-list {
  display: grid;
  gap: 6px;
  max-block-size: min(62vh, 680px);
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  padding-right: 2px;
}
```

Add the existing narrow-screen media override only if a test screenshot shows the queue exceeding the viewport; it must retain vertical scrolling rather than growing the page indefinitely.

- [ ] **Step 5: Verify and commit**

```powershell
Set-Location E:/codex_workspace/agent_spot_welding/.worktrees/spot-weld-quality/ml-platform/backend
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_api_spot_weld_quality tests.test_spot_weld_quality_service -v
Set-Location ../frontend
& C:/Users/17723/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd exec vitest run src/pages/DataAnnotationPage.test.tsx
& C:/Users/17723/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd run build
git add ../backend/app/services/spot_weld_quality.py ../backend/app/api/spot_weld_quality.py ../backend/tests/test_api_spot_weld_quality.py ../backend/tests/test_spot_weld_quality_service.py src/api/spotWeldQuality.ts src/pages/DataAnnotationPage.tsx src/pages/DataAnnotationPage.test.tsx src/styles/global.css
git commit -m "feat: export spot weld annotations"
```

Expected: exported labels include the current state and immutable history, cross-project export returns 404, and a 1875-sample queue stays within a scrollable panel.

## 6. Task 5: Execute the report flow and record evidence

**Files:** existing tests, `DEVELOPMENT_PLAN.md`, `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`.

- [ ] **Step 1: Create or upload the report-compatible input**

Use existing “模拟数据” request with `row_count=1875` for a synthetic flow, or upload the authorized report-structured CSV/XLSX through data management. The required input is the currently enforced table fields plus `cvei`, `cvev`, `cver`, `cvep`; additional source columns are retained in the uploaded Artifact but do not require a new parser.

- [ ] **Step 2: Run the platform flow**

1. Select project and dataset in the existing point-weld AutoML recipe.
2. Select all ten candidates or an explicit subset, then start the existing quality run.
3. Inspect the existing AutoML table, K search/PCA summary, label queue/four waveforms, and Monitor warning distribution.
4. Create an `automatic` report-reproduction snapshot, train it with the existing snapshot route, and download its existing 8 Sheet XLSX/model artifacts.
5. Export annotations as CSV and XLSX from the data-labeling page.

- [ ] **Step 3: Run focused and full local validation**

```powershell
Set-Location E:/codex_workspace/agent_spot_welding/.worktrees/spot-weld-quality/ml-platform/backend
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_automl_tracking tests.test_training_tasks tests.test_spot_weld_features tests.test_spot_weld_quality_service tests.test_api_spot_weld_quality tests.test_all_operators -v
& C:/Users/17723/miniconda3/python.exe run_suite.py
Set-Location ../frontend
& C:/Users/17723/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd exec vitest run
& C:/Users/17723/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/pnpm.cmd run build
```

Expected: all focused tests pass; a synthetic 1875 run has 73 features, selected candidate count, persisted labels, an eight-sheet training report, and both annotation exports. Local test success must be recorded separately from browser/Compose/remote CI evidence.

- [ ] **Step 4: Update records only after evidence exists**

Append to `DEVELOPMENT_PLAN.md` and the shared development experience only after implementation and validation. Record input type (`synthetic` or uploaded), row count, selected candidate IDs, test commands/results, browser result, and remaining original-data/remote-CI gates. Do not record private data paths, credentials, tokens or copied source rows.

## Coverage review

- Existing platform reproduces waveform decode, 73 features, all ten report configurations, feature-importance weighted clustering, rules, four-level warnings, label revisions, snapshots, 4-model training, model lineage and 8 Sheet XLSX.
- Task 1 adds the user-requested generic AutoML algorithm-set selection without changing task persistence or dispatch.
- Task 2 makes report candidate choice and automatic weak-label training explicit without adding tables, pages or a parallel ML stack.
- Task 3 makes report feature engineering reusable from the existing workflow canvas.
- Task 4 satisfies export-with-saved-labels and the scrollable sample queue request.
- Static PNG/DOCX generation and a private PostgreSQL adapter are intentionally excluded: the report data and charts are represented by existing platform pages/XLSX, and neither is needed to reproduce the algorithm or data-labeling workflow.
