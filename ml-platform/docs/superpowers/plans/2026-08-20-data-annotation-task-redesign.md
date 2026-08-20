# 数据标注任务重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将数据标注页面重构为任务列表、单标签手动标注和支持注册模型/弱监督聚类的自动标注流程，并让目标列成为所有任务的显式必选配置。

**Architecture:** 复用现有 `SpotWeldQualityRun`、`SpotWeldQualitySample`、点焊特征工程和模型库数据，不创建第二套任务表。把任务模式、目标列、所选模型、弱监督配置、簇标签映射和工艺规则持久化在现有 `input_fingerprint`/`statistics` JSON 契约中；对需要跨请求恢复的字段在序列化接口中显式返回。前端把创建页面拆为公共数据/目标列选择、手动配置和自动配置三块，通过任务状态轮询恢复样本队列和进度。

**Tech Stack:** FastAPI/Pydantic/SQLAlchemy、现有点焊质量服务、NumPy/Pandas/scikit-learn `KMeans`/`silhouette_score`、React/TypeScript/Ant Design、Vitest/Testing Library、unittest。

---

## 文件边界

- Modify: `ml-platform/backend/app/api/spot_weld_quality.py`，扩展创建请求、数据列元数据、标签删除、模型选择和弱监督配置接口。
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py`，实现目标列校验、模型推理、特征重要性加权聚类、簇标签校验和单标签输出。
- Modify: `ml-platform/backend/app/models/spot_weld_quality.py`，仅在现有 JSON 持久化不足以表达任务状态时增加字段；优先不迁移数据库。
- Create: `ml-platform/backend/alembic/versions/20260820_*.py`，仅当 ORM 增加非 JSON 字段时提供幂等迁移。
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.ts`，补充列元数据、模型、目标列、标签删除和自动标注配置类型/API。
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`，重构任务列表、两个创建入口、目标列配置、单标签编辑、自动标注配置和只读工艺规则展示。
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`，替换旧模拟数据/模式切换/规则编辑断言，增加新的页面契约测试。
- Modify: `ml-platform/frontend/src/styles/global.css`，调整任务列表、创建面板、簇结果、标签映射和详情置顶布局。
- Modify: `ml-platform/backend/tests/test_api_spot_weld_quality.py`，增加 API 输入、目标列和单标签删除测试。
- Modify: `ml-platform/backend/tests/test_spot_weld_quality_service.py`，增加聚类权重、K 搜索、标签映射和直接模型标注测试。
- Modify: `ml-platform/backend/tests/week_manifest.py`，若新增测试模块则登记唯一周次归属；优先复用已有测试模块避免清单遗漏。
- Modify: `DEVELOPMENT_PLAN.md`，记录实现状态、验证结果、未完成项和风险。
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`，追加可复用的输出协议/异步任务/标签契约经验。

### Task 1: 固定目标列与单标签后端契约

**Files:**
- Modify: `ml-platform/backend/app/api/spot_weld_quality.py`
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py`
- Test: `ml-platform/backend/tests/test_api_spot_weld_quality.py`
- Test: `ml-platform/backend/tests/test_spot_weld_quality_service.py`

- [ ] **Step 1: Write failing tests for required target columns and label deletion**

  增加以下测试行为：

  - `POST /validate` 和 `POST /runs` 在 `target_column` 缺失、为空或不存在时返回 `QUALITY_TARGET_COLUMN_REQUIRED`/`QUALITY_TARGET_COLUMN_INVALID`。
  - 已有列作为目标列时，`input_columns` 不得包含该列。
  - 新建目标列时允许列名不在输入表头中，并在任务配置中返回 `target_column_created=true`。
  - 目标列与输入已有列重名时按“选择已有列”处理，不重复创建。
  - `DELETE /runs/{run_id}/samples/{sample_id}/labels` 清空 `current_label`、`current_note`、`current_revision_id`，并更新手动任务进度。

- [ ] **Step 2: Run the focused backend tests and confirm RED**

  Run:

  ```powershell
  C:\Users\17723\miniconda3\python.exe -m unittest tests.test_api_spot_weld_quality tests.test_spot_weld_quality_service
  ```

  Expected: new target-column and label-delete assertions fail because the existing request accepts optional targets and has no delete-label route.

- [ ] **Step 3: Implement the shared target-column normalization**

  在 `spot_weld_quality.py` 增加一个纯函数，接收 `frame`、`target_column`、`input_columns` 和 `create_target_column`，执行以下规则：

  ```python
  if not target_column or not target_column.strip():
      raise QualityPipelineError("QUALITY_TARGET_COLUMN_REQUIRED")
  if create_target_column:
      if target_column in frame.columns:
          raise QualityPipelineError("QUALITY_TARGET_COLUMN_EXISTS")
      normalized_input = list(frame.columns)
  else:
      if target_column not in frame.columns:
          raise QualityPipelineError("QUALITY_TARGET_COLUMN_INVALID")
      normalized_input = [name for name in input_columns or frame.columns if name != target_column]
  ```

  新建列只在内存任务帧中补充空值；不把空目标列送入模型输入。将标准化后的 `target_column`、`target_column_created`、`input_columns`、`target_schema` 写入 `input_fingerprint` 和 `statistics`，并在 `_serialize_run` 返回。

- [ ] **Step 4: Implement explicit single-label deletion**

  在 API 中增加 `DELETE /runs/{run_id}/samples/{sample_id}/labels`，复用 `quality.label` 权限和审计服务；只允许清除当前人工标签，不删除历史 `SpotWeldLabelRevision`，并将样本状态恢复为 `pending_review`。重新计算 `annotation_progress` 时以 `current_label.isnot(None)` 为唯一单标签完成条件。

- [ ] **Step 5: Run the focused backend tests and confirm GREEN**

  ```powershell
  C:\Users\17723\miniconda3\python.exe -m unittest tests.test_api_spot_weld_quality tests.test_spot_weld_quality_service
  ```

  Expected: existing tests and new target-column/delete-label tests pass.

### Task 2: 数据列元数据与项目注册模型 API

**Files:**
- Modify: `ml-platform/backend/app/api/spot_weld_quality.py`
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.ts`
- Test: `ml-platform/backend/tests/test_api_spot_weld_quality.py`
- Test: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`

- [ ] **Step 1: Write failing tests for dataset columns and registered model filtering**

  增加 API/UI 契约：

  - 选择数据集后可以请求实际表头及数据类型；返回 `columns`、`row_count`、`target_candidates`。
  - 模型列表只返回当前项目 `ModelLibrary` 中 `status=registered` 的模型，并包含模型 ID、名称、版本、框架、特征 schema、模型制品 ID 和可用标签类型。
  - 页面模型下拉框不显示其他项目模型、训练中模型或没有可读制品的模型。

- [ ] **Step 2: Run the focused tests and confirm RED**

  ```powershell
  C:\Users\17723\miniconda3\python.exe -m unittest tests.test_api_spot_weld_quality
  npm test -- --run src/pages/DataAnnotationPage.test.tsx
  ```

  Expected: column metadata route and registered-only model filtering assertions fail.

- [ ] **Step 3: Implement metadata and model serialization**

  增加 `GET /datasets/{artifact_id}/columns`，通过现有 artifact service 解析数据集但只返回表头和安全的 dtype/row_count，不返回完整波形内容。扩展 `GET /models` 的过滤条件为当前项目、已注册状态、点焊来源或兼容的 73 维 feature schema；继续通过项目访问控制和 artifact 可读性校验。

  前端 API 增加：

  ```ts
  export interface QualityDatasetColumns { columns: Array<{ name: string; dtype: string }>; row_count: number; }
  export interface QualityRegisteredModel { id: string; name: string; version?: string; feature_schema?: string[]; target_schema?: Record<string, unknown>; model_artifact_id?: string | null; }
  export function getQualityDatasetColumns(projectId: string, artifactId: string): Promise<QualityDatasetColumns>
  export function listRegisteredQualityModels(projectId: string): Promise<QualityRegisteredModel[]>
  export function deleteQualityLabel(projectId: string, runId: string, sampleId: string): Promise<void>
  ```

- [ ] **Step 4: Run API and page tests and confirm GREEN**

  ```powershell
  C:\Users\17723\miniconda3\python.exe -m unittest tests.test_api_spot_weld_quality
  npm test -- --run src/pages/DataAnnotationPage.test.tsx
  ```

### Task 3: 直接模型标注与弱监督聚类服务

**Files:**
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py`
- Modify: `ml-platform/backend/app/api/spot_weld_quality.py`
- Test: `ml-platform/backend/tests/test_spot_weld_quality_service.py`
- Test: `ml-platform/backend/tests/test_api_spot_weld_quality.py`

- [ ] **Step 1: Write failing service tests for model inference and weighted clustering**

  测试以下纯服务行为：

  - 直接模型策略从注册模型制品加载模型，排除目标列，使用模型预测结果生成单标签；类别值与目标列的 `target_schema` 保持一致。
  - 弱监督策略从所选模型取得 73 维 `feature_importances_`，归一化后得到非负且和为 1 的权重。
  - 加权空间等于 `StandardScaler(X).transform(X) * sqrt(weights)`。
  - 在 `K=2..min(8, n-1)` 中搜索轮廓系数，保存每个 K 的分数和 `best_k`。
  - 簇数量不足以映射标签时返回 `QUALITY_CLUSTER_LABELS_REQUIRED`；标签数量足够时每个样本只生成一个目标标签。
  - 模型缺少 73 维特征重要性或权重和为零时返回稳定错误码，不静默使用错误维度。

- [ ] **Step 2: Run service tests and confirm RED**

  ```powershell
  C:\Users\17723\miniconda3\python.exe -m unittest tests.test_spot_weld_quality_service
  ```

  Expected: direct model strategy and cluster label mapping tests fail because current automatic path is rule-based and does not accept a selected model or label mapping.

- [ ] **Step 3: Implement model artifact loading and feature contract validation**

  增加服务函数 `load_registered_quality_model(db, project_id, model_id, artifact_service)`：验证项目归属、`status == registered`、模型制品存在、feature schema 与 `FEATURE_SCHEMA` 一致；使用现有 artifact materialization 和 `joblib.load`，禁止从客户端路径读取。将模型对象、特征 schema、target schema 和模型元数据封装为内部只读结构。

- [ ] **Step 4: Implement direct prediction and target-label mapping**

  增加 `run_direct_model_annotation(features, model_bundle, target_schema)`：使用 `predict` 产生单标签；若模型返回编码类别，则按照模型 `classes_` 和目标列类别顺序映射回目标列类型；目标列只有数值/字符串单值，不输出标签数组。将结果写入 `automatic_label` 和目标列映射结果。

- [ ] **Step 5: Implement weighted KMeans and cluster label assignment**

  复用现有 `run_clustering`，但把所选模型的 `feature_importances_` 作为唯一权重来源；扩展 `ClusterResult` 保存 `best_k`、所有轮廓系数、权重、簇 ID 和 PCA 坐标。增加 `assign_cluster_labels(cluster_ids, labels_by_cluster)`，要求映射覆盖所有簇且标签数量不少于簇数量，然后生成单标签数组。

- [ ] **Step 6: Persist automatic configuration and execute through the existing dispatcher**

  在 `DatasetQualityRequest`/`create_quality_run_record` 中增加：

  ```text
  selected_model_id: UUID | None
  weak_supervision: bool
  cluster_labels: dict[str, str]
  process_rules: list[dict[str, str | float | int | bool]]
  target_column_created: bool
  ```

  将这些字段写入任务输入快照；自动任务完成后把模型 ID、聚类结果、只读工艺规则和标签映射写入 `statistics`/`clustering_results`，由 worker 恢复并执行。手动任务不加载模型、不执行规则和聚类。

- [ ] **Step 7: Run service and API tests and confirm GREEN**

  ```powershell
  C:\Users\17723\miniconda3\python.exe -m unittest tests.test_spot_weld_quality_service tests.test_api_spot_weld_quality
  ```

### Task 4: 重构前端任务列表和创建流程

**Files:**
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.ts`
- Modify: `ml-platform/frontend/src/styles/global.css`
- Test: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`

- [ ] **Step 1: Write failing page tests for the new entry points and removed controls**

  页面测试必须覆盖：

  - `/data-annotation` 直接显示任务列表，右上角同时有“新建手动标注任务”和“新建自动标注任务”。
  - 创建页面不包含“准备模拟数据”“点焊标注配置”“SPOT WELD”“自动标注/手动标注”切换和“已有质量运行”。
  - 任务创建模式由入口决定，手动页按钮为“开始手动标注”，自动页按钮为“开始自动标注”。
  - 目标列是必填控件，能够在“已有列/新建列”之间切换；没有目标列时开始按钮禁用。
  - 选择数据文件后显示真实列名并可选择目标列。

- [ ] **Step 2: Run page tests and confirm RED**

  ```powershell
  npm test -- --run src/pages/DataAnnotationPage.test.tsx
  ```

  Expected: old setup controls and old mode switch assertions conflict with the new requirements, and new entry/target-column assertions fail.

- [ ] **Step 3: Split page state by immutable task mode**

  用 `creationMode: "manual" | "automatic"` 替代创建页的 `labelMode` 单选状态；创建入口写入 URL，页面只渲染对应配置。保留任务详情的 `selectedRun.label_mode` 作为历史任务只读状态。删除模拟数据、已有运行选择器、创建页规则编辑和 SPOT WELD/配置标题。

- [ ] **Step 4: Add target-column and dataset selection UI**

  选择数据集后调用列元数据 API；增加“目标列来源”分段控件：

  ```tsx
  <Segmented options={["选择已有列", "新建目标列"]} />
  ```

  已有列模式显示真实列名下拉框；新建模式显示文本输入框；两种模式都在没有有效值时禁止开始。创建请求传入 `target_column`、`target_column_created` 和排除目标列后的 `input_columns`。

- [ ] **Step 5: Add automatic model and weak-supervision controls**

  自动创建页加载当前项目已注册模型；显示模型名称/版本/框架和特征 schema 合法性。增加弱监督开关、规则模板按钮、规则编辑列表、聚类结果表和簇到标签的单值映射输入。聚类结果返回前，开始按钮禁用；簇标签数量小于 `best_k` 时显示字段错误。

- [ ] **Step 6: Run page tests and confirm GREEN**

  ```powershell
  npm test -- --run src/pages/DataAnnotationPage.test.tsx
  ```

### Task 5: 重构样本详情、进度与保存交互

**Files:**
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.ts`
- Modify: `ml-platform/frontend/src/styles/global.css`
- Test: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`

- [ ] **Step 1: Write failing tests for single-label detail behavior**

  覆盖：

  - 样本详情第一块显示“人工标签”。
  - 当前标签只能有一个；点击新标签覆盖旧标签。
  - 点击“删除人工标签”调用 DELETE API，标签恢复“未标注”。
  - 手动任务不显示“标注规则”；自动任务完成后显示只读“工艺规则”，不渲染可编辑 input 或“保存标注规则”。
  - 页面不显示“提交复核”，显示“保存到数据管理”。
  - 轮询任务详情和样本队列后，进度从 `0/10` 更新到 `5/10`，不能只更新任务卡片初始值。

- [ ] **Step 2: Run page tests and confirm RED**

  ```powershell
  npm test -- --run src/pages/DataAnnotationPage.test.tsx
  ```

- [ ] **Step 3: Implement single-label editor and delete action**

  把人工标签区域移动到详情顶部；保存仍调用现有单标签 POST 接口，删除调用新增 DELETE 接口。标签显示使用任务目标列的标签字典；标签按钮必须设置 `aria-pressed`，避免把自动标签误显示为人工标签。

- [ ] **Step 4: Implement read-only automatic process rules**

  创建阶段规则项可编辑；任务开始后将规则快照保存到任务配置，详情只渲染文本和命中状态，移除编辑输入与保存按钮。手动任务完全不渲染规则区域。

- [ ] **Step 5: Implement reliable progress refresh**

  在活动任务轮询中同时调用 `getQualityRun` 和 `listQualitySamples`，用响应中的任务对象替换 `runs` 中对应项，使用 `annotation_progress` 计算队列头进度；请求必须带当前项目/任务闭包校验，防止切换项目后旧响应覆盖新状态。

- [ ] **Step 6: Run page tests and confirm GREEN**

  ```powershell
  npm test -- --run src/pages/DataAnnotationPage.test.tsx
  ```

### Task 6: 回归、文档和发布前验证

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`
- Modify: `ml-platform/backend/tests/week_manifest.py` only if new test modules were added

- [ ] **Step 1: Run focused backend and frontend suites**

  ```powershell
  C:\Users\17723\miniconda3\python.exe -m unittest tests.test_api_spot_weld_quality tests.test_spot_weld_quality_service tests.test_spot_weld_features
  npm test -- --run src/pages/DataAnnotationPage.test.tsx src/api/spotWeldQuality.test.ts
  ```

- [ ] **Step 2: Run the complete local quality checks**

  ```powershell
  C:\Users\17723\miniconda3\python.exe -m unittest discover -s tests
  npm test
  npm run build
  git diff --check
  ```

  Expected: all commands pass; existing ECharts chunk-size warnings may remain and must be reported separately from failures.

- [ ] **Step 3: Verify migrations and clean-checkout contracts**

  ```powershell
  C:\Users\17723\miniconda3\python.exe -m unittest tests.test_database_migrations tests.test_ci_workflow tests.test_week_manifest
  ```

  If ORM fields were added, run the repository's Alembic upgrade/downgrade and `alembic check` commands documented in `DEVELOPMENT_PLAN.md`; if JSON storage remains sufficient, record that no migration was required.

- [ ] **Step 4: Perform a browser-level smoke check**

  Start the frontend with the repository's existing dev command on an unused port. Verify: menu entry → task list → manual creation → target column → sample label add/delete → progress refresh → save; then automatic creation → model selection → weak supervision → cluster labels → read-only process rules → save. Capture failures with exact API request/response and do not treat skipped browser paths as passed.

- [ ] **Step 5: Update project records**

  Append to `DEVELOPMENT_PLAN.md`: implemented behavior, test counts, build result, migration status, browser status, remote Actions status and remaining risks. Append a reusable entry to `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md` containing observed behavior, verified root cause, solution, verification and prevention; do not include secrets or customer data.

- [ ] **Step 6: Review scoped diff before any publication**

  ```powershell
  git status --short --branch
  git diff --stat
  git diff --check
  ```

  Stage only files belonging to this feature. Preserve the existing dirty changes in the workflow canvas and spot-weld feature-engineering files; do not run `reset`, `checkout`, force push, or broad staging.

## Self-review

- Spec coverage: task list and buttons are covered by Task 4; target-column selection/new column and persistence by Tasks 1, 2 and 4; manual single-label add/delete/progress/detail by Tasks 1 and 5; model selection/direct inference/weak supervision/K search/cluster-label minimum by Task 3; read-only process rules and save action by Task 5; test/documentation requirements by Task 6.
- Placeholder scan: no unresolved placeholder or unspecified implementation step is used in this plan.
- Type consistency: `target_column_created`, `selected_model_id`, `weak_supervision`, `cluster_labels` and `process_rules` are introduced in Task 3 and consumed by Task 4; `deleteQualityLabel` is introduced in Task 2 and consumed by Task 5; all label values remain single strings.
- Known boundary: the current `SpotWeldQualityRun` worker is rule-oriented. Task 3 explicitly changes the worker execution path before Task 4 exposes the automatic controls, so the UI cannot advertise a strategy that the backend does not execute.
