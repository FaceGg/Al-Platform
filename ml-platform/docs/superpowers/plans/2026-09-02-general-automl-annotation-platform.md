# 通用自动建模与数据标注平台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 将整个项目迁移为通用结构化数据平台，并交付四种 AutoML 任务、多列标签标注、三种自动标注策略、独立标注员门户、可审计回传和可复现模型导出推理。

**Architecture:** 先建立不可变数据版本、标签 schema、任务快照、输入输出合同和版本化制品，再把 AutoML、自动标注、人工标注、回传、模型注册和离线推理接到这些合同上。主平台负责项目、数据、任务、指派、验收和模型资产；标注员门户使用独立前端、独立后端、独立账号和独立会话，只通过受认证的内部 API 交付任务和回传结果。长任务继续使用持久化 worker，但每个操作都有幂等键、租约、重试和失败封闭语义。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy、Alembic、PostgreSQL/SQLite 兼容层、Redis/Celery、Artifact Storage、pandas、scikit-learn、Optuna、joblib/ONNX、React/TypeScript、Ant Design、Vitest、Playwright、PowerShell 7。

**Spec:** ml-platform/docs/technical-proposals/2026-09-01-general-automl-annotation-platform.md

**Supporting specs:** ml-platform/docs/superpowers/specs/2026-08-31-multilabel-annotation-annotator-portal-design.md、2026-08-20-data-annotation-task-redesign.md、2026-08-19-automl-result-registration-design.md、2026-08-27-weak-supervision-fallback-rule-design.md。

**Status:** planned。技术方案仍处于评审修订状态；本计划是评审通过后的实现顺序，不代表任何功能已完成。

## Global Constraints

- 整个项目只面向通用扁平结构化数据；新运行时代码、数据库合同、路由和页面不得依赖行业字段、固定特征、行业标签、行业规则或专用报告。
- 输入格式固定为 CSV、Excel、Parquet、JSON、XML。JSON/XML 先归一化为扁平标量表，再进入统一 schema 和数据版本流程。
- JSON 只接受顶层对象数组或管理员指定的记录数组路径；XML 只接受管理员指定的重复记录节点路径；非标量值、重复键、重复列名和不兼容标量类型整批拒绝。
- 解析上限默认为原文件 1 GB、解压后 4 GB、100 万条记录、200 列、32 层深度、单字段 64 KB；部署可下调但不能取消。
- 持久化的 AutoML 任务类型只有 classification、multioutput_classification、regression、multioutput_regression。multilabel_classification 和 multiregression 只在写入前作为兼容别名读取，不能进入数据库或导出 manifest。
- 多标签采用多个独立目标列或标签列，不使用数组型多选值；标签列类型只允许 int、float、string，首期不实现层级标签和互斥组。
- 单目标分类恰好一个目标列，多输出分类至少两个目标列；单目标回归恰好一个目标列，多输出回归至少两个目标列；回归目标只允许 int/float。
- 管理员默认勾选全部非目标输入特征，可手动取消；输入列名、顺序、类型、缺失策略、编码映射和预处理版本写入 input contract。
- 交叉验证可选 2 至 5 折，默认 5 折；单目标分类使用分层，多输出分类使用多标签迭代分层，回归使用打乱 KFold；不可用折数不静默降级。
- 搜索方法固定支持网格、随机、贝叶斯、进化、多保真，默认贝叶斯；搜索强度为轻度 10、中度 30、高度 80、ultra 200 次；时间档位为快速 30、标准 60、扩展 120、长时 240 分钟，默认标准。
- 算法目录默认勾选全部兼容且已启用算法；单任务最多并行 2 个候选算法。用户可以选择是否计算类别权重，默认启用；不自动过采样、欠采样或合成样本。
- 分类排行按 AUC、Macro-F1、Accuracy、运行时间的字典序排序，前三项越大越好、运行时间越小越好；回归按 R²、RMSE、MAE、运行时间排序。
- 特征重要性必须展示来源、逐目标向量、聚合向量、one-hot 还原和不可用维度；全部不可用时禁止伪造等权重要性。
- 自动标注启用聚类后只能选择一种策略：cluster、rule、cluster_rule。未启用聚类时使用模型输出，不读取用户簇/规则标签。
- 启用聚类时使用所选模型的特征重要性加权 KMeans：标准化后乘以权重平方根，K 取 2 至 8，按 Silhouette Score 选最优 K；超过 100,000 条样本时最多确定性抽样 50,000 条评估，最终簇分配覆盖全量样本。
- 同一标签列的来源优先级固定为规则 > 簇 > 其他；其他兜底始终存在、不可删除，每个标签列必须配置符合类型约束的合法兜底值；同优先级冲突进入 needs_review。
- 标注员门户使用独立前端、独立后端、独立账号和独立会话，默认可配置端口 8443；主平台 Cookie、账号和令牌不与门户共享。
- 标注员主体使用不可变 annotator_subject_id；主平台只保存受控主体映射和项目授权，浏览器提交的 project_id、annotator_id 和 assignment 范围不可信。
- 多人可重叠编辑同一样本；写入携带 base revision，过期返回 409 和服务端完整标签集合，只有标注员显式确认完整集合后才允许最后写入。
- 标注员主动回传；成功回传后指派范围只读并锁定回传按钮，显式编辑并成功生成新修订后才解除锁定。
- AutoML worker 只生成候选工件和报告，不自动创建或启用模型库记录；用户必须手动选择完整成功候选后注册。
- 导出包必须包含模型、预处理、映射表、输入输出合同、推理代码、聚类方法和标签规则工件（仅关联自动标注任务修订时）、manifest、全量 SHA-256、锁定依赖、SBOM 和签名，且不包含真实数据、账号或密钥。
- 所有写接口要求 Authorization、X-Request-ID 和 Idempotency-Key；长任务返回 202 和 operation_id；列表、样本、预览和差异使用 cursor 分页，默认 50、最大 200。
- 所有状态修改携带 task_revision 或 If-Match；状态守卫、项目权限、assignment 范围和审计由服务端执行；错误统一返回 request_id、code、message、details。
- JSON/XML 解析在隔离 worker 执行；XML 禁止 DTD、外部实体、外部 schema、网络和文件系统访问；登录、注册、批量标签和密码重置执行限流与审计。
- 任何 required 测试、构建、迁移、浏览器验收、导出校验或恢复演练处于 failed、cancelled、skipped 或未执行状态时，不得把功能或阶段标记为完成。

## 文件边界总览

### 主平台后端

- 修改：ml-platform/backend/app/main.py、app/api/datasets.py、app/api/training.py、app/api/annotations.py、app/api/labeling.py、app/api/model_registry.py、app/api/model_library.py、app/api/auth.py、app/tasks/celery_app.py。
- 修改并逐步去行业化：app/api/spot_weld_quality.py、app/services/spot_weld_quality.py、app/services/spot_weld_features.py、app/tasks/spot_weld_quality_tasks.py、app/models/spot_weld_quality.py。
- 新建：app/models/data_version.py、app/models/automl.py、app/models/labeling.py、app/models/annotator.py、app/models/model_export.py；app/schemas/dataset_import.py、automl.py、labeling.py、annotation_tasks.py、annotator.py、model_export.py；app/services/data_import.py、input_contract.py、label_schema.py、annotation_tasks.py、annotation_strategies.py、weighted_clustering.py、rule_dsl.py、annotation_concurrency.py、annotator_identity.py、model_export.py、offline_inference.py。
- 新建异步入口：app/tasks/automl_tasks.py、app/tasks/annotation_tasks.py、app/tasks/model_export_tasks.py、app/tasks/annotator_sync_tasks.py。
- 新建迁移：ml-platform/backend/alembic/versions/20260902_15_generic_data_versions.py 及后续按依赖递增的迁移文件；更新 app/database_migrations.py 和 app/models/__init__.py。

### 独立标注员服务

- 新建：ml-platform/annotator/backend/app/main.py、config.py、api/auth.py、api/tasks.py、api/comments.py、services/platform_client.py、services/session.py、models/annotator.py、requirements.txt、Dockerfile。
- 新建：ml-platform/annotator/frontend/package.json、vite.config.ts、index.html、src/main.tsx、src/App.tsx、src/api/client.ts、src/api/auth.ts、src/api/tasks.ts、src/pages/LoginPage.tsx、RegisterPage.tsx、TaskQueuePage.tsx、TaskWorkspacePage.tsx、src/pages/*.test.tsx。
- 修改：docker-compose.yml、docker-compose.acceptance.yml、.env.example 或等价部署配置，注入 ANNOTATOR_PUBLIC_ORIGIN、ANNOTATOR_API_ORIGIN、ANNOTATOR_PORT=8443 和服务身份凭据引用。

### 主平台前端和测试

- 修改：ml-platform/frontend/src/App.tsx、pages/AutoMLPage.tsx、pages/AutoMLTaskPage.tsx、pages/DataAnnotationPage.tsx、pages/AnnotationPage.tsx、pages/ModelLibraryPage.tsx、api/datasets.ts、api/auth.ts、api/modelRegistry.ts、i18n/index.tsx。
- 新建：frontend/src/api/annotationTasks.ts、annotationReturns.ts、annotatorAssignments.ts、automl.ts、modelExports.ts；组件 PreviewDrawer.tsx、AssignmentDialog.tsx、ReturnBatchList.tsx、LabelSchemaEditor.tsx。
- 测试：ml-platform/backend/tests/test_genericization_contract.py、test_dataset_import_contract.py、test_automl_multioutput.py、test_label_schema.py、test_annotation_task_state.py、test_annotation_strategies.py、test_annotator_auth.py、test_annotation_concurrency.py、test_annotation_return_acceptance.py、test_model_export_contract.py、test_offline_inference_contract.py；前端对应 Vitest 和 frontend/e2e/generic-annotation-portal.spec.ts、automl-multioutput.spec.ts、model-export.spec.ts。

## Task 1: 全项目去行业化迁移基线

**Objective:** 建立生产代码的通用边界，迁移旧行业数据和入口，并阻止新功能继续依赖行业字段。

**Files:**
- Create: ml-platform/docs/migrations/2026-09-02-genericization-inventory.md
- Create: ml-platform/backend/tests/test_genericization_contract.py
- Modify: ml-platform/backend/app/main.py、app/api/spot_weld_quality.py、app/services/spot_weld_quality.py、app/services/spot_weld_features.py、app/tasks/spot_weld_quality_tasks.py、app/models/spot_weld_quality.py、app/models/platform_models.py
- Modify: ml-platform/frontend/src/App.tsx、pages/AnnotationPage.tsx、pages/DataAnnotationPage.tsx、api/spotWeldQuality.ts、i18n/index.tsx
- Modify: ml-platform/backend/tests/week_manifest.py

**Interfaces:**
- Produces GET /api/annotation-tasks、POST /api/annotation-tasks 和 POST /api/automl-tasks 的通用入口。
- Legacy spot-weld API 只允许迁移期读取、弃用响应或明确重定向，不接受新任务写入。
- migrate_legacy_quality_run(run_id: UUID) -> GenericAnnotationTask 将旧运行记录、样本、标签修订和快照转换为通用任务合同，并保留 source_legacy_id。

- [ ] **Step 1: Write the failing migration and route tests**

~~~python
def test_generic_annotation_create_does_not_require_industry_columns(client):
    response = client.post("/api/annotation-tasks", json={
        "project_id": str(project_id),
        "dataset_version_id": str(dataset_version_id),
        "mode": "manual",
        "label_schema_id": str(label_schema_id),
        "sample_scope": {"kind": "all"},
    })
    assert response.status_code == 201
    assert "industry_field" not in response.json()

def test_legacy_spot_weld_write_is_closed(client):
    response = client.post("/api/projects/{}/spot-weld/runs".format(project_id), json={})
    assert response.status_code in (410, 307)

def test_legacy_quality_run_migrates_to_generic_task(db):
    task = migrate_legacy_quality_run(db, legacy_run_id)
    assert task.mode in {"manual", "automatic"}
    assert task.source_legacy_id == str(legacy_run_id)
~~~

- [ ] **Step 2: Run the tests and verify the old implementation fails**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m unittest tests.test_genericization_contract -v
~~~

Expected: the generic route is missing or still requires the old industry payload, and the legacy write route is accepted.

- [ ] **Step 3: Implement the migration boundary**

1. Add a production-source forbidden reference list covering old route prefixes, fixed feature schema names, industry label constants and industry-only model classes. The scan excludes historical plans, archived evidence, test fixtures used only for migration input and the migration document itself.
2. Add generic route modules and make main.py include them before the deprecated route. The deprecated route returns a structured 410 with GENERIC_API_REQUIRED for writes.
3. Add a one-way data migration that copies legacy runs into generic dataset versions, label schemas, task snapshots and revision history. Never delete legacy rows before the new records pass row-count, sample-id and checksum checks.
4. Make old spot-weld services adapters only; new code calls generic services and never imports industry feature builders.
5. Replace production navigation and i18n text with generic names while preserving historical documents and evidence.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m unittest tests.test_genericization_contract tests.test_suite_manifest -v
rg -n -i "spot[-_ ]weld|weld_fault|report_v1|FEATURE_SCHEMA" app api models services tasks ..\..\frontend\src
py -3.14 -m py_compile app/main.py app/api/annotations.py app/services/annotation_tasks.py
git diff --check
~~~

Expected: genericization tests pass; the source scan returns only explicitly marked migration adapters and no new business dependency; every new test module has exactly one week owner.

**Dependencies:** none. This task gates all subsequent implementation.

## Task 2: 数据导入、数据版本和统一输入合同

**Objective:** 将 CSV、Excel、Parquet、JSON、XML 统一为可复用的扁平表和不可变数据版本，并区分缺列和列值为空。

**Files:**
- Create: ml-platform/backend/app/models/data_version.py、app/schemas/dataset_import.py、app/services/data_import.py、app/services/input_contract.py、ml-platform/backend/tests/test_dataset_import_contract.py
- Modify: ml-platform/backend/app/api/datasets.py、app/models/artifact.py、app/models/platform_models.py、app/database_migrations.py、ml-platform/backend/requirements.txt
- Create: ml-platform/backend/alembic/versions/20260902_15_generic_data_versions.py

**Interfaces:**
- read_dataset_upload(path: Path, source_format: str, options: ParseOptions) -> NormalizedTable
- freeze_dataset_version(db: Session, normalized: NormalizedTable, operator_id: UUID) -> DatasetVersion
- build_input_contract(frame: DataFrame, feature_columns: list[str], missing_policy: dict[str, str], preprocessing_version: str) -> InputContract
- validate_input_contract(frame: DataFrame, contract: InputContract) -> ValidationReport

- [ ] **Step 1: Write RED tests for normal formats and hostile inputs**

~~~python
def test_json_object_array_is_normalized_and_hash_is_stable(tmp_path):
    path = tmp_path / "rows.json"
    path.write_text('[{"id": 1, "score": 2.5}, {"id": 2, "score": 3.0}]', encoding="utf-8")
    table = read_dataset_upload(path, "json", ParseOptions(record_path=None))
    assert table.frame.columns.tolist() == ["id", "score"]
    assert table.parse_contract["parser_version"]
    assert table.schema_hash == read_dataset_upload(path, "json", ParseOptions(record_path=None)).schema_hash

def test_xml_external_entity_and_json_duplicate_key_are_rejected(tmp_path):
    xml = tmp_path / "evil.xml"
    xml.write_text("<!DOCTYPE r [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><r/>", encoding="utf-8")
    with pytest.raises(DataImportError) as xml_error:
        read_dataset_upload(xml, "xml", ParseOptions(record_path=".//record"))
    assert xml_error.value.code == "DATA_PARSE_UNSAFE_XML"

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('[{"a": 1, "a": 2}]', encoding="utf-8")
    with pytest.raises(DataImportError) as json_error:
        read_dataset_upload(duplicate, "json", ParseOptions(record_path=None))
    assert json_error.value.code == "DATA_PARSE_DUPLICATE_KEY"

def test_missing_column_is_not_treated_as_null():
    report = validate_input_contract(pd.DataFrame({"x": [1]}), {
        "required_columns": ["x", "y"],
        "columns": {"x": {"dtype": "int"}, "y": {"dtype": "float"}},
    })
    assert report.code == "INPUT_REQUIRED_COLUMN_MISSING"
    assert report.partial_output_allowed is False
~~~

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_dataset_import_contract.py -q
~~~

Expected: the parser module, data version model or input contract validator is not present, or accepts unsafe input.

- [ ] **Step 3: Implement safe parsing and version freezing**

1. Add a JSON decoder using object_pairs_hook to reject duplicate keys; accept only object records and scalar values.
2. Add XML parsing through a hardened parser dependency, reject DTD/entity/schema/network access, and map only attributes plus direct child scalar nodes to columns.
3. Enforce file, decompressed, record, column, depth, field-length and elapsed-time limits before committing an artifact.
4. Store original artifact, normalized table artifact, parser options, field mapping, parser version, schema hash, content hash, sample-id index and row locator in immutable DatasetVersion rows.
5. Preserve administrator-confirmed int, float, string types. Generate UUID sample ids when no unique non-empty column is selected.
6. Implement validate_input_contract with required-column, dtype, null policy, enum/range, sample-id and finite-float checks. Extra non-feature columns are allowed; missing required columns are not.
7. Add an additive Alembic migration and an idempotent SQLite compatibility path; the compatibility path must not recreate existing tables.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_dataset_import_contract.py -q
py -3.14 -m pytest tests/test_database_migrations.py tests/test_artifact_storage_integration.py -q
py -3.14 -m alembic upgrade head
git diff --check
~~~

Expected: all five formats have frozen parse contracts; XXE, duplicate keys, non-scalars, limits and path traversal are rejected without a partial data version; fresh Alembic and legacy SQLite compatibility both pass.

**Dependencies:** Task 1.

## Task 3: AutoML 四种任务类型和训练合同

**Objective:** 在现有 AutoML 搜索基础上支持单/多输出分类和回归，保留候选工件而不自动注册模型。

**Files:**
- Create: ml-platform/backend/app/models/automl.py、app/schemas/automl.py、app/tasks/automl_tasks.py、ml-platform/backend/tests/test_automl_multioutput.py
- Modify: ml-platform/backend/app/services/automl_catalog.py、automl_search.py、automl_execution.py、app/api/training.py、app/models/training.py、app/models/experiment.py、app/tasks/celery_app.py
- Modify: ml-platform/frontend/src/pages/AutoMLPage.tsx、AutoMLTaskPage.tsx、src/api/training.ts
- Create: ml-platform/backend/alembic/versions/20260902_16_automl_contract.py

**Interfaces:**
- normalize_task_type(raw: str) -> Literal["classification", "multioutput_classification", "regression", "multioutput_regression"]
- validate_target_columns(frame: DataFrame, task_type: str, target_columns: list[str]) -> TargetValidation
- run_automl_search(frame: DataFrame, contract: AutoMLContract) -> AutoMLExecutionResult
- aggregate_feature_importance(per_target: dict[str, Sequence[float]], feature_map: FeatureMap) -> FeatureImportanceReport
- rank_candidates(candidates: Sequence[CandidateSummary], task_type: str) -> list[CandidateSummary]

- [ ] **Step 1: Write RED tests for task normalization, CV, search and ranking**

~~~python
def test_only_four_task_types_are_persisted():
    assert normalize_task_type("multilabel_classification") == "multioutput_classification"
    assert normalize_task_type("multiregression") == "multioutput_regression"
    with pytest.raises(AutoMLContractError):
        normalize_task_type("industry_quality")

def test_multioutput_classification_uses_independent_targets_and_iterative_stratification(contract):
    result = run_automl_search(frame, contract(task_type="multioutput_classification",
        target_columns=["label_a", "label_b"], cross_validation_folds=5))
    assert result.per_target["label_a"].macro_f1 is not None
    assert result.per_target["label_b"].auc is not None
    assert result.cv_strategy == "iterative_stratified"

def test_candidate_ranking_is_auc_then_f1_then_accuracy_then_runtime():
    ranked = rank_candidates([
        CandidateSummary("a", auc=0.90, macro_f1=0.60, accuracy=0.80, runtime_s=20),
        CandidateSummary("b", auc=0.90, macro_f1=0.60, accuracy=0.80, runtime_s=10),
    ], "classification")
    assert [item.algorithm_id for item in ranked] == ["b", "a"]

def test_worker_does_not_create_model_library_record(db, candidate):
    execute_automl_job(db, candidate.task_id)
    assert db.query(ModelLibrary).filter(ModelLibrary.training_job_id == candidate.task_id).count() == 0
~~~

- [ ] **Step 2: Run the tests and verify the current single-output implementation fails**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_automl_multioutput.py tests/test_automl_catalog.py -q
~~~

Expected: only classification and regression are accepted, target arrays are ignored, or the worker creates a model-library row.

- [ ] **Step 3: Implement training contracts and search controls**

1. Normalize aliases at request parsing and reject aliases in persisted rows, model contracts and manifests.
2. Validate target count, dtype, missing values, finite values, class cardinality and target leakage before queueing.
3. Implement per-target encoders for string classification targets and independent estimators or an explicit multi-output wrapper. Preserve per-target predictions, metrics, failures and feature importance.
4. Implement 2-5 fold selection with the required CV strategy and freeze the random seed in the task snapshot. Fit preprocessing inside each training fold.
5. Expose all five search methods, four strength levels, four time budgets, algorithm multiselect defaulting to all compatible families and the user-controlled class-weight switch.
6. Implement AUC fallback from predict_proba to decision_function; mark AUC unavailable when any target lacks a valid continuous score and exclude the candidate from the complete-AUC tier.
7. Persist per-target reports, aggregate metrics, search configuration, runtime, input contract, preprocessing and feature-importance report. Candidate completion may store artifacts but cannot mutate model registry tables.
8. Wire tasks/automl_tasks.py into the durable dispatcher with idempotency key, lease fields, progress and cancellation.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_automl_multioutput.py tests/test_automl_catalog.py tests/test_api_training.py -q
py -3.14 -m py_compile app/services/automl_catalog.py app/services/automl_search.py app/services/automl_execution.py
git diff --check
~~~

Expected: four task types, 2-5 fold CV, all search controls, ranking, feature importance and worker non-registration tests pass; incomplete candidates cannot be registered.

**Dependencies:** Tasks 1 and 2.

## Task 4: 标签 schema、类型校验和修订历史

**Objective:** 提供版本化的多列标签合同，并让手动标签、自动标签和回传都经过同一列级校验。

**Files:**
- Create: ml-platform/backend/app/models/labeling.py、app/schemas/labeling.py、app/services/label_schema.py、app/services/annotation_concurrency.py、ml-platform/backend/tests/test_label_schema.py
- Modify: ml-platform/backend/app/models/platform_models.py、app/models/__init__.py、app/api/annotations.py
- Create: ml-platform/backend/alembic/versions/20260902_17_label_schema_revision.py
- Modify: ml-platform/frontend/src/pages/DataAnnotationPage.tsx
- Create: ml-platform/frontend/src/components/LabelSchemaEditor.tsx、src/components/LabelSchemaEditor.test.tsx

**Interfaces:**
- validate_label_value(column: LabelColumnContract, value: object) -> object
- validate_label_values(schema: LabelSchemaContract, values: Mapping[str, object], allow_partial: bool) -> dict[str, object]
- write_label_revision(db: Session, task_id: UUID, sample_id: str, values: Mapping[str, object], author_id: UUID, base_revision: int) -> LabelWriteResult
- get_current_label_set(db: Session, task_id: UUID, sample_id: str) -> CurrentLabelSet

- [ ] **Step 1: Write RED tests for int/float/string and independent columns**

~~~python
def test_label_types_reject_invalid_values():
    assert validate_label_value(LabelColumnContract("count", "int"), "12") == 12
    with pytest.raises(LabelValueError):
        validate_label_value(LabelColumnContract("count", "int"), "12.5")
    with pytest.raises(LabelValueError):
        validate_label_value(LabelColumnContract("score", "float"), float("nan"))
    with pytest.raises(LabelValueError):
        validate_label_value(LabelColumnContract("name", "string", max_length=4), "abcdef")

def test_partial_edit_preserves_unmodified_label_columns():
    result = write_label_revision(db, task_id, sample_id,
        {"label_a": "accepted"}, annotator_id, base_revision=2)
    assert result.values == {"label_a": "accepted", "label_b": 3}
    assert result.revision_no == 3

def test_completion_rejects_missing_required_label():
    with pytest.raises(LabelValueError) as error:
        validate_label_values(schema, {"label_a": 1}, allow_partial=False)
    assert error.value.code == "LABEL_REQUIRED_MISSING"
~~~

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_label_schema.py -q
~~~

Expected: the current single-label string storage accepts invalid numeric values or cannot preserve independent columns and revision numbers.

- [ ] **Step 3: Implement schema and revision persistence**

1. Add label_schemas, label_columns, label_value_constraints, annotation_task_labels, annotation_sample_current, annotation_revisions, annotation_comments and annotation_confirmations with project and task indexes.
2. Freeze machine key, display name, ordinal, type, required flag, enum/range and string byte limit at schema version creation. Do not coerce arrays or multi-select values.
3. Store current complete values separately from immutable revisions. Each revision records author, source, base revision, action, timestamp and provenance reference.
4. Implement exact int parsing, finite float validation, UTF-8 string length and enum checks. Allow partial writes during editing but reject missing required values during confirm and return.
5. Add migration backfill from legacy single-label fields into one-column schemas and preserve legacy revision ids.
6. Update the editor to let administrators create columns, choose type and constraints, and show validation errors before submitting.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_label_schema.py -q
py -3.14 -m pytest tests/test_database_migrations.py -q
Set-Location ..\frontend
npm test -- --run src/components/LabelSchemaEditor.test.tsx
npm run build
~~~

Expected: type and required-value tests pass, schema migration is idempotent, and the editor sends typed independent values.

**Dependencies:** Tasks 1 and 2.

## Task 5: 标注任务状态机、任务列表和预览

**Objective:** 统一手动标注和自动标注任务的创建、预览、发布、执行、暂停、完成和归档行为，所有操作停留在任务列表或预览上下文。

**Files:**
- Create: ml-platform/backend/app/services/annotation_tasks.py、app/schemas/annotation_tasks.py、ml-platform/backend/tests/test_annotation_task_state.py
- Modify: ml-platform/backend/app/api/annotations.py、app/models/labeling.py、app/tasks/annotation_tasks.py、app/main.py
- Create: ml-platform/backend/alembic/versions/20260902_18_annotation_task_state.py
- Modify: ml-platform/frontend/src/pages/AnnotationPage.tsx、DataAnnotationPage.tsx
- Create: ml-platform/frontend/src/api/annotationTasks.ts、src/components/PreviewDrawer.tsx、src/components/AssignmentDialog.tsx、src/pages/DataAnnotationPage.test.tsx

**Interfaces:**
- create_annotation_task(db: Session, request: AnnotationTaskCreate, actor: Principal) -> AnnotationTaskResponse
- create_annotation_preview(task_id: UUID, task_revision: int, config_hash: str) -> OperationRef
- transition_annotation_task(task_id: UUID, expected_revision: int, action: TaskAction) -> AnnotationTaskResponse
- list_annotation_tasks(project_id: UUID, cursor: str | None, limit: int) -> CursorPage[AnnotationTaskResponse]
- get_annotation_preview(task_id: UUID, preview_id: UUID, cursor: str | None, limit: int) -> AnnotationPreviewPage

- [ ] **Step 1: Write RED tests for state guards and preview idempotency**

~~~python
def test_manual_task_publish_requires_preview_ready(client):
    response = client.post("/api/annotation-tasks/{}/publish".format(task_id), json={
        "task_revision": 0,
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TASK_STATE_INVALID"

def test_preview_reuses_same_operation_for_same_config_hash(client):
    payload = {"task_revision": 0, "config_hash": "sha256:abc"}
    first = client.post("/api/annotation-tasks/{}/preview".format(task_id), json=payload)
    second = client.post("/api/annotation-tasks/{}/preview".format(task_id), json=payload)
    assert first.status_code == second.status_code == 202
    assert first.json()["operation_id"] == second.json()["operation_id"]

def test_automatic_task_execution_requires_valid_preview(client):
    response = client.post("/api/annotation-tasks/{}/execute".format(task_id), json={
        "task_revision": 1,
        "preview_id": str(other_preview_id),
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PREVIEW_STALE"
~~~

- [ ] **Step 2: Run the tests and verify the current endpoints fail**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_annotation_task_state.py -q
~~~

Expected: the existing annotation API accepts direct status edits, has no preview operation key, or cannot distinguish stale previews.

- [ ] **Step 3: Implement the task contract**

1. Add task snapshots containing dataset version, fixed sample-id set, visible columns, label schema, instructions and configuration hash.
2. Implement the states draft, previewing, preview_ready, executing, awaiting_annotation, in_progress, awaiting_return, returned_pending_acceptance, accepted, completed, paused, cancelled, failed and needs_review.
3. Enforce server-side transition guards. Configuration changes increment task_revision and invalidate previous previews.
4. Make preview and execution asynchronous, return operation_id, persist progress and expose cursor-paginated sample statistics, cluster statistics, rule hits and final labels.
5. Use one task list for manual and automatic tasks. The API never redirects to a detail page and the response contains preview and assignment affordances.
6. Record audit events for every state transition and reject client-supplied project or sample scope that differs from the stored snapshot.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_annotation_task_state.py -q
Set-Location ..\frontend
npm test -- --run src/pages/DataAnnotationPage.test.tsx
npm run build
~~~

Expected: state and idempotency tests pass; manual and automatic list actions show preview and assignment controls without automatic navigation.

**Dependencies:** Tasks 2 and 4.

## Task 6: 三种自动标注策略和特征重要性加权 KMeans

**Objective:** 实现未聚类时的模型输出、聚类后的 cluster/rule/cluster_rule 互斥策略，以及可复现的加权 KMeans 和逐列来源链。

**Files:**
- Create: ml-platform/backend/app/services/weighted_clustering.py、app/services/rule_dsl.py、app/services/annotation_strategies.py、ml-platform/backend/tests/test_annotation_strategies.py
- Modify: ml-platform/backend/app/services/spot_weld_quality.py、app/api/labeling.py、app/tasks/annotation_tasks.py、app/models/labeling.py
- Create: ml-platform/backend/alembic/versions/20260902_19_annotation_strategy_artifacts.py
- Modify: ml-platform/frontend/src/pages/DataAnnotationPage.tsx、src/api/annotationTasks.ts
- Create: ml-platform/frontend/src/pages/AutomaticAnnotationConfig.test.tsx

**Interfaces:**
- aggregate_model_importance(per_target: Mapping[str, Sequence[float]], feature_map: FeatureMap) -> ImportanceVector
- build_weighted_clusters(frame: DataFrame, model: object, feature_contract: InputContract, seed: int, max_k: int = 8) -> ClusterArtifact
- validate_strategy_config(config: AutomaticAnnotationConfig, schema: LabelSchemaContract) -> None
- apply_annotation_strategy(model_output: Mapping[str, object], cluster_id: int | None, frame_row: Mapping[str, object], config: AutomaticAnnotationConfig) -> AnnotationDecision

- [ ] **Step 1: Write RED tests for strategy exclusivity, fallback and weighted clustering**

~~~python
def test_strategy_is_exclusive_and_fallback_is_required():
    with pytest.raises(StrategyConfigError):
        validate_strategy_config(AutomaticAnnotationConfig(
            clustering=True, strategy="cluster_rule",
            cluster_labels={"1": {"label_a": "x"}},
            rules=[{"id": "r1", "values": {"label_a": "y"}}],
        ), schema)
    with pytest.raises(StrategyConfigError) as error:
        validate_strategy_config(AutomaticAnnotationConfig(
            clustering=True, strategy="cluster",
            cluster_labels={"1": {"label_a": "x"}},
        ), schema)
    assert error.value.code == "CLUSTER_FALLBACK_REQUIRED"

def test_cluster_rule_uses_rule_then_cluster_then_other_per_column():
    decision = apply_annotation_strategy(
        {"label_a": "model-a", "label_b": "model-b"}, cluster_id=2,
        {"score": 0.9},
        config_with_rule_cluster_and_other(),
    )
    assert decision.values == {"label_a": "rule-a", "label_b": "cluster-b"}
    assert decision.provenance["label_a"]["source"] == "rule"

def test_weighted_kmeans_scores_k_2_to_8_and_assigns_all_rows(model, frame):
    artifact = build_weighted_clusters(frame, model, input_contract, seed=7)
    assert set(artifact.k_scores) <= set(range(2, 9))
    assert len(artifact.labels) == len(frame)
    assert artifact.sample_count_evaluated <= 50000
~~~

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_annotation_strategies.py -q
~~~

Expected: the old rule service stores one string label, has no cluster/rule exclusivity, or performs unweighted clustering.

- [ ] **Step 3: Implement the strategy pipeline**

1. When clustering is disabled, copy validated model output to each label column and record source=model; ignore cluster and rule label values.
2. When clustering is enabled, require exactly one of cluster, rule or cluster_rule. Require an immutable other mapping for every label column and validate its type.
3. Implement feature-importance aggregation: per-target non-negative finite vectors are L1-normalized, one-hot dimensions are restored to source columns, and multi-target vectors are averaged equally. A zero-sum or unavailable vector yields needs_review.
4. Standardize numeric/encoded feature space, compute weights = importance / sum(importance), then multiply each dimension by sqrt(weight). Evaluate K from 2 through 8 with Silhouette Score, using all rows up to 100,000 and a deterministic hash-based sample of at most 50,000 rows above that threshold. Run final KMeans over all eligible rows.
5. Persist seed, weight vector, feature map, K scores, sampling mode/hash, centers, preprocessing artifact and final assignment artifact.
6. Implement cluster strategy for selected one or more clusters plus other fallback; implement rule strategy with typed condition DSL and multi-column values; implement cluster_rule with rule > cluster > other per-column priority.
7. Send same-priority conflicts, missing mappings, invalid rules and invalid label values to needs_review. Never silently merge conflicting values.
8. Return model output, cluster id, matched rule ids, final values and provenance in preview; keep internal provenance out of returned data versions.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_annotation_strategies.py tests/test_api_spot_weld_quality.py -q
py -3.14 -m py_compile app/services/weighted_clustering.py app/services/rule_dsl.py app/services/annotation_strategies.py
git diff --check
~~~

Expected: all three strategy modes, fallback and weighted KMeans tests pass; a million-row fixture verifies full-row assignment and bounded Silhouette sampling.

**Dependencies:** Tasks 3, 4 and 5.

## Task 7: 标注员独立认证、主体映射和服务边界

**Objective:** 建立独立标注员账号、认证服务、会话和主平台主体映射，确保门户不复用主平台登录态。

**Files:**
- Create: ml-platform/annotator/backend/app/main.py、config.py、api/auth.py、services/session.py、services/platform_client.py、models/annotator.py、requirements.txt、Dockerfile
- Create: ml-platform/backend/app/models/annotator.py、app/services/annotator_identity.py、app/api/annotator_internal.py、ml-platform/backend/tests/test_annotator_auth.py
- Modify: ml-platform/backend/app/models/user.py、app/api/auth.py、app/config.py、app/main.py
- Create: ml-platform/backend/alembic/versions/20260902_20_annotator_identity.py
- Modify: docker-compose.yml、docker-compose.acceptance.yml、.env.example 或等价配置文件

**Interfaces:**
- register_annotator(data: AnnotatorRegisterRequest) -> AnnotatorAccountView
- authenticate_annotator(username: str, password: str) -> PortalSession
- map_annotator_subject(subject_id: UUID, platform_principal_id: UUID | None, actor: Principal) -> SubjectMapping
- require_portal_session(request: Request) -> AnnotatorPrincipal
- verify_internal_service_token(request: Request, required_scope: str, project_id: UUID) -> ServicePrincipal

- [ ] **Step 1: Write RED tests for independent auth and revocation**

~~~python
def test_portal_registration_requires_eight_character_password(client):
    response = client.post("/portal/auth/register", json={
        "username": "annotator-a", "password": "short"
    })
    assert response.status_code == 422

def test_portal_cookie_is_not_accepted_by_platform_auth(portal_client, platform_client):
    login = portal_client.post("/portal/auth/login", data={
        "username": "annotator-a", "password": "valid-pass-8"
    })
    platform_client.cookies.update(login.cookies)
    response = platform_client.get("/api/auth/me")
    assert response.status_code == 401

def test_disabled_or_reset_annotator_session_is_invalidated(db, session):
    disable_annotator(db, session.subject_id)
    with pytest.raises(PortalAuthError) as error:
        require_portal_session(session.request)
    assert error.value.code == "ANNOTATOR_SESSION_REVOKED"
~~~

- [ ] **Step 2: Run tests and verify the shared-auth implementation fails**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_annotator_auth.py -q
~~~

Expected: there is no portal service, the platform accepts the portal token, or password/session revocation rules are missing.

- [ ] **Step 3: Implement the separate identity and service contract**

1. Add annotator_accounts, annotator_sessions, annotator_subject_mappings and project_annotator_grants with immutable subject ids, status, session_version and audit fields.
2. Use Argon2id or equivalent password hashing, accept password length 8-128, return a generic error for unknown accounts and apply registration/login/reset rate limits.
3. Keep portal origin, API origin and port in environment settings; default ANNOTATOR_PORT to 8443 without hard-coding it in frontend code.
4. Issue short-lived, rotating portal sessions in Secure, HttpOnly, controlled SameSite cookies. Increment session_version on disable, password reset, project revoke and service revoke.
5. Authenticate portal-to-platform calls with service JWT or mTLS and validate issuer, audience, expiry, nonce, scope and project id. Never pass a browser cookie to internal endpoints.
6. Expose internal endpoints for account review, project grant/revoke, assignment delivery and session invalidation; reject client-supplied project or annotator identity.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_annotator_auth.py tests/test_database_migrations.py -q
Set-Location ..\annotator\backend
py -3.14 -m pytest -q
docker compose -f ..\..\..\docker-compose.yml config
~~~

Expected: independent login/register/revocation and service-token tests pass; Compose exposes the portal on configured 8443 and no platform cookie is accepted.

**Dependencies:** Tasks 1, 2 and 4.

## Task 8: 指派、重叠样本并发、自动保存和回传锁

**Objective:** 将管理员指派固定样本范围给一个或多个标注员，并实现乐观 revision、显式冲突确认、主动回传和回传后的只读锁。

**Files:**
- Create: ml-platform/backend/app/services/annotation_concurrency.py、app/schemas/annotator.py、ml-platform/backend/tests/test_annotation_concurrency.py
- Modify: ml-platform/backend/app/api/annotations.py、app/api/annotator_internal.py、app/models/labeling.py、app/tasks/annotator_sync_tasks.py
- Create: ml-platform/annotator/backend/app/api/tasks.py、api/comments.py、services/platform_client.py
- Create: ml-platform/backend/alembic/versions/20260902_21_annotation_assignments.py

**Interfaces:**
- create_assignments(task_id: UUID, annotator_ids: list[UUID], sample_scope: SampleScope, due_at: datetime | None, actor: Principal) -> list[Assignment]
- save_labels(assignment_id: UUID, sample_id: str, values: Mapping[str, object], base_revision: int) -> LabelWriteResult | RevisionConflict
- confirm_assignment(assignment_id: UUID, task_revision: int, scope_hash: str) -> ConfirmationResult
- edit_for_return(assignment_id: UUID, task_revision: int) -> AssignmentState
- return_assignment(assignment_id: UUID, task_revision: int, scope_hash: str, idempotency_key: str) -> ReturnBatchRef

- [ ] **Step 1: Write RED tests for overlap, conflict and return lock**

~~~python
def test_two_annotators_can_read_same_sample_but_stale_write_returns_full_conflict(db):
    first = save_labels(assignment_a, "s-1", {"label_a": "x", "label_b": 1}, base_revision=0)
    conflict = save_labels(assignment_b, "s-1", {"label_a": "y", "label_b": 2}, base_revision=0)
    assert first.revision_no == 1
    assert isinstance(conflict, RevisionConflict)
    assert conflict.current_values == {"label_a": "x", "label_b": 1}

def test_return_is_idempotent_and_locks_assignment(db):
    first = return_assignment(assignment_id, 3, scope_hash, "return-key")
    second = return_assignment(assignment_id, 3, scope_hash, "return-key")
    assert first.return_batch_id == second.return_batch_id
    assert assignment.state == "returned_pending_acceptance"
    with pytest.raises(AssignmentLockedError):
        save_labels(assignment_id, "s-1", {"label_a": "z"}, base_revision=1)

def test_edit_for_return_requires_new_revision_before_unlock(db):
    edit_for_return(assignment_id, 3)
    with pytest.raises(AssignmentLockedError):
        return_assignment(assignment_id, 3, scope_hash, "second-key")
    save_labels(assignment_id, "s-1", {"label_a": "z", "label_b": 1}, base_revision=3)
    assert return_assignment(assignment_id, 4, scope_hash, "second-key").state == "pending"
~~~

- [ ] **Step 2: Run the tests and verify the old last-write behavior fails**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_annotation_concurrency.py -q
~~~

Expected: the current API silently overwrites stale edits, does not retain a complete label set, or allows a second return without an edit.

- [ ] **Step 3: Implement assignment and optimistic concurrency**

1. Resolve administrator-selected sample scopes to sorted, fixed sample ids and store sample_scope_hash. Allow overlapping scopes and do not duplicate source rows.
2. On every label write, lock the current sample row transactionally, compare base_revision, validate the complete resulting label set, append an immutable revision and increment revision_no.
3. Return 409 REVISION_CONFLICT with current revision, complete server values, diff summary and reread address. Add a portal action that explicitly confirms the complete collection before retrying.
4. Prevent writes and return when assignment is revoked, task is paused/cancelled, session is invalid, or a return lock is active.
5. Require confirmation only for the annotator's fixed scope; global task completion is computed from all samples and all required columns.
6. After successful return, set assignment to read-only and create a pending return batch. edit_for_return changes state only after at least one new successful revision; the new batch supersedes the prior unaccepted batch.
7. Keep task and sample comments separate from label values, with author, related revision and resolved state.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_annotation_concurrency.py tests/test_annotator_auth.py -q
Set-Location ..\annotator\backend
py -3.14 -m pytest -q
~~~

Expected: overlapping editing, explicit conflict resolution, assignment revocation and return-lock tests pass; repeated requests produce one return batch.

**Dependencies:** Tasks 4, 5 and 7.

## Task 9: 回传结果列表、数据管理验收和站内通知

**Objective:** 让标注员主动回传固定范围，主平台在数据管理中列出回传批次、提供预览/批注/差异，并由管理员验收或退回。

**Files:**
- Create: ml-platform/backend/app/api/annotation_returns.py、app/services/annotation_returns.py、ml-platform/backend/tests/test_annotation_return_acceptance.py
- Modify: ml-platform/backend/app/api/datasets.py、app/api/notifications.py、app/services/notification_outbox.py、app/models/labeling.py
- Create: ml-platform/backend/alembic/versions/20260902_22_annotation_return_batches.py
- Create: ml-platform/frontend/src/api/annotationReturns.ts、src/components/ReturnBatchList.tsx、src/components/ReturnBatchList.test.tsx
- Modify: ml-platform/frontend/src/pages/DataManagePage.tsx、DataAnnotationPage.tsx、components/NotificationCenter.tsx

**Interfaces:**
- create_return_batch(assignment_id: UUID, expected_task_revision: int, scope_hash: str, idempotency_key: str) -> ReturnBatch
- list_return_batches(project_id: UUID, cursor: str | None, limit: int) -> CursorPage[ReturnBatchView]
- diff_return_batch(return_batch_id: UUID, cursor: str | None, limit: int) -> CursorPage[LabelDiff]
- accept_return_batch(return_batch_id: UUID, expected_revision: int, actor: Principal) -> DatasetVersion
- reject_return_batch(return_batch_id: UUID, expected_revision: int, reason: str, actor: Principal) -> ReturnBatch

- [ ] **Step 1: Write RED tests for return, diff, acceptance and notifications**

~~~python
def test_acceptance_creates_new_dataset_version_without_mutating_source(db):
    result = accept_return_batch(return_batch_id, expected_revision=4, actor=project_admin)
    assert result.status == "ready"
    assert result.id != source_dataset_version.id
    assert load_dataset(source_dataset_version.id).columns == load_dataset(result.id).columns

def test_return_diff_is_sample_id_aligned_and_cursor_paged(client):
    response = client.get("/api/annotation-return-batches/{}/diff?limit=1".format(batch_id))
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["sample_id"]
    assert "next_cursor" in response.json()

def test_rejected_return_requires_reason_and_notifies_annotator(client):
    response = client.post("/api/annotation-return-batches/{}/return".format(batch_id), json={
        "task_revision": 4, "reason": ""
    })
    assert response.status_code == 422
    reject_return_batch(batch_id, 4, "label_a needs correction", project_admin)
    assert has_in_app_notification(annotator_subject_id, "returned_for_changes")
~~~

- [ ] **Step 2: Run the tests and verify the old save/export behavior fails**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_annotation_return_acceptance.py -q
~~~

Expected: no return-batch list or diff endpoint exists, acceptance mutates the source version, or rejection does not notify the annotator.

- [ ] **Step 3: Implement return processing and data-management integration**

1. Create immutable return batches carrying assignment id, fixed scope hash, source task revision, idempotency key, actor subject and state pending, superseded, accepted, returned_for_changes or archived.
2. Re-read the source dataset version and current complete label sets by sample_id inside one transaction. Validate every required label column and type before creating a new dataset version.
3. Keep source and historical versions immutable. Accepted results create a new version containing original columns plus final label columns; never silently merge overlapping ranges or perform majority voting.
4. Reject stale task revisions with 409, make repeated idempotency keys return the same batch, and serialize acceptance for the same task/scope.
5. Expose cursor-paged return list, preview and per-sample diff. Add task-level and sample-level comments that do not enter the returned dataset or training data.
6. Emit in-app notifications for assignment, return, rejection, acceptance, overdue and background failure. Avoid exposing full rows or label values in notification payloads.
7. Keep DataManagePage as the result entry point and show preview, annotate/comment, accept and return actions without redirecting to an annotation detail page.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_annotation_return_acceptance.py tests/test_notification_outbox.py -q
Set-Location ..\frontend
npm test -- --run src/components/ReturnBatchList.test.tsx src/pages/DataManagePage.test.tsx
npm run build
~~~

Expected: return/accept/reject/diff tests pass; accepted versions are new immutable versions and all user-facing events are in-app notifications.

**Dependencies:** Tasks 4, 5 and 8.

## Task 10: 模型候选手动注册和模型库生命周期

**Objective:** 复用现有注册逻辑，让用户从完整成功候选中手动选择模型注册，且重复注册幂等、状态受控。

**Files:**
- Create: ml-platform/backend/tests/test_model_registration_contract.py
- Modify: ml-platform/backend/app/api/model_registry.py、app/services/model_registry.py、app/api/model_library.py、app/models/model_registry.py、app/models/model_library.py
- Modify: ml-platform/frontend/src/api/modelRegistry.ts、src/pages/AutoMLTaskPage.tsx、src/pages/ModelLibraryPage.tsx
- Create: ml-platform/backend/alembic/versions/20260902_23_model_contract_metadata.py

**Interfaces:**
- register_automl_candidate(task_id: UUID, candidate_id: UUID, model_name: str, actor: Principal, idempotency_key: str) -> ModelVersion
- list_registerable_candidates(task_id: UUID) -> CursorPage[CandidateSummary]
- validate_model_contract(model_version_id: UUID) -> ContractValidationReport
- transition_model_version(model_version_id: UUID, action: Literal["approve","disable","revoke","archive"], actor: Principal) -> ModelVersion

- [ ] **Step 1: Write RED tests for manual registration and no worker side effect**

~~~python
def test_only_complete_candidate_can_be_registered(client):
    response = client.post("/api/automl-tasks/{}/register".format(task_id), json={
        "candidate_id": str(incomplete_candidate.id), "model_name": "candidate-a"
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CANDIDATE_NOT_REGISTERABLE"

def test_registration_is_idempotent_for_same_candidate_and_key(client):
    payload = {"candidate_id": str(complete_candidate.id), "model_name": "candidate-a"}
    first = client.post("/api/automl-tasks/{}/register".format(task_id), json=payload,
        headers={"Idempotency-Key": "register-1"})
    second = client.post("/api/automl-tasks/{}/register".format(task_id), json=payload,
        headers={"Idempotency-Key": "register-1"})
    assert first.json()["model_version_id"] == second.json()["model_version_id"]

def test_registered_model_preserves_multilabel_contract(client):
    version = register_automl_candidate(task_id, complete_candidate.id, "candidate-a", admin, "key")
    assert version.output_schema["target_columns"] == ["label_a", "label_b"]
    assert version.conversion_metadata["input_contract_hash"]
~~~

- [ ] **Step 2: Run the tests and verify automatic registration is still possible**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_model_registration_contract.py tests/test_automl_result_registration.py -q
~~~

Expected: incomplete candidates can be registered, repeated requests create duplicates, or the registration path loses target/contract metadata.

- [ ] **Step 3: Implement candidate registration and lifecycle**

1. Make the existing registration endpoint accept a candidate source id and task id, verify project ownership, candidate state, artifact hash, input/output contract and model format.
2. Use one transaction and an idempotency record keyed by project, task, candidate and idempotency key. Repeated calls return the existing RegisteredModel/ModelVersion.
3. Persist normalized task type, ordered target columns, data version, preprocessing, mappings, metrics, per-target metrics, feature importance, cluster/annotation references and artifact checksums.
4. Keep worker code free of registry writes. A candidate may be visible as registerable only after all required artifacts and reports are committed.
5. Preserve model state transitions pending_review, enabled, disabled, revoked and archived; only enabled models can be used for new annotation or export.
6. Update the AutoML result table with a row-level register action and explicit loading, conflict and success states. The model library shows contract and feature-importance summaries.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_model_registration_contract.py tests/test_automl_result_registration.py tests/test_api_model_registry.py -q
Set-Location ..\frontend
npm test -- --run src/pages/AutoMLTaskPage.test.tsx src/pages/ModelLibraryPage.test.tsx
npm run build
~~~

Expected: manual selection is required, registration is idempotent, model states are enforced, and all four task types remain visible in the model library.

**Dependencies:** Tasks 2, 3, 4 and 5.

## Task 11: 模型导出包和离线 predict/annotate

**Objective:** 生成包含模型、合同、预处理、映射、聚类/规则工件、依赖、SBOM、签名和校验和的可复现导出包，并在推理前后执行整批合同校验。

**Files:**
- Create: ml-platform/backend/app/services/model_export.py、app/services/offline_inference.py、app/schemas/model_export.py、ml-platform/backend/tests/test_model_export_contract.py、test_offline_inference_contract.py
- Modify: ml-platform/backend/app/api/model_registry.py、app/api/model_library.py、app/tasks/model_export_tasks.py、app/models/model_registry.py
- Create: ml-platform/backend/alembic/versions/20260902_24_model_exports.py
- Modify: ml-platform/frontend/src/api/modelExports.ts、src/pages/ModelLibraryPage.tsx
- Create: ml-platform/frontend/e2e/model-export.spec.ts

**Interfaces:**
- create_model_export(model_version_id: UUID, annotation_task_revision: UUID | None, include_runtime: bool, idempotency_key: str) -> ExportOperation
- build_export_manifest(model_version: ModelVersion, files: Sequence[Path]) -> Manifest
- validate_export_package(path: Path) -> ExportValidationReport
- run_offline_predict(package: Path, input_path: Path, output_path: Path) -> PredictionResult
- run_offline_annotate(package: Path, input_path: Path, output_path: Path) -> AnnotationResult

- [ ] **Step 1: Write RED tests for package contents, signatures and invalid input**

~~~python
def test_export_contains_contracts_checksums_sbom_and_signature(tmp_path, registered_version):
    export = create_model_export(registered_version.id, None, include_runtime=True, idempotency_key="export-1")
    validate_export_package(export.path)
    names = set(zipfile.ZipFile(export.path).namelist())
    assert {"manifest.json", "checksums.json", "security/sbom.spdx.json",
            "security/manifest.sig", "runtime/inference.py"} <= names
    assert "data/" not in "\n".join(names)

def test_annotation_export_includes_strategy_only_when_task_revision_is_bound(registered_version):
    export = create_model_export(registered_version.id, annotation_revision.id, False, "export-2")
    names = set(zipfile.ZipFile(export.path).namelist())
    assert "annotation/strategy.json" in names
    assert "annotation/cluster_method.json" in names

def test_offline_predict_rejects_missing_column_without_partial_output(package, tmp_path):
    with pytest.raises(InputContractError) as error:
        run_offline_predict(package, tmp_path / "missing.csv", tmp_path / "out.csv")
    assert error.value.code == "INPUT_CONTRACT_MISMATCH"
    assert not (tmp_path / "out.csv").exists()
~~~

- [ ] **Step 2: Run the tests and verify no complete export contract exists**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_model_export_contract.py tests/test_offline_inference_contract.py -q
~~~

Expected: the old download contains only a model file or allows inference with missing/wrong input columns.

- [ ] **Step 3: Implement deterministic export and offline runtime**

1. Build a temporary export directory containing model files, preprocessing, mappings, contracts, runtime/inference.py, optional Dockerfile, locked requirements, README and optional annotation artifacts.
2. Create manifest fields for normalized task type, target columns, data/model/candidate ids, input/output contract hashes, preprocessing and library versions, Python/runtime, CPU/OS compatibility, all seeds, deterministic settings, thread settings, artifact SHA-256, strategy/rule hashes and export tool version.
3. Generate checksums for every file, SPDX SBOM for direct/transitive dependencies and a detached signature over manifest plus checksums. If signing is unavailable, fail closed instead of publishing.
4. Exclude real data, sample rows, labels, comments, users, credentials and private keys. Expose downloads only for completed, signed and checksum-validated exports.
5. Implement predict for model output and annotate for the bound annotation revision. Parse CSV/Excel/Parquet/JSON/XML; JSON/XML require matching parse_contract.
6. Validate required columns, order semantics, dtypes, missing policy, mappings, ranges, sample_id uniqueness/order and finite output values. On any error, write only a sanitized validation-report.json and remove partial output.
7. Add one-time download authorization and audit logging; do not expose service credentials in the ZIP or URL.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_model_export_contract.py tests/test_offline_inference_contract.py -q
Set-Location ..\frontend
npm test -- --run src/pages/ModelLibraryPage.test.tsx
npm run build
Set-Location ..\..
Set-Location ml-platform/frontend
npm run test:e2e -- e2e/model-export.spec.ts
Set-Location ..\..
~~~

Expected: export structure, signature, checksum, SBOM, annotation inclusion and all-or-nothing input/output validation pass.

**Dependencies:** Tasks 2, 3, 6 and 10.

## Task 12: 主平台和标注员门户前端

**Objective:** 完成任务列表中心、预览、指派、回传结果、模型注册/导出和独立标注员工作区，保证桌面和窄屏布局可用。

**Files:**
- Modify: ml-platform/frontend/src/App.tsx、src/pages/AutoMLPage.tsx、AutoMLTaskPage.tsx、DataAnnotationPage.tsx、AnnotationPage.tsx、DataManagePage.tsx、ModelLibraryPage.tsx、src/api/datasets.ts、auth.ts、modelRegistry.ts、i18n/index.tsx
- Create: ml-platform/frontend/src/api/annotationTasks.ts、annotationReturns.ts、annotatorAssignments.ts、automl.ts、modelExports.ts
- Create: ml-platform/frontend/src/components/PreviewDrawer.tsx、AssignmentDialog.tsx、ReturnBatchList.tsx、LabelSchemaEditor.tsx 及对应测试
- Create: ml-platform/annotator/frontend/package.json、vite.config.ts、index.html、src/main.tsx、src/App.tsx、src/api/client.ts、auth.ts、tasks.ts、comments.ts、src/pages/LoginPage.tsx、RegisterPage.tsx、TaskQueuePage.tsx、TaskWorkspacePage.tsx 及对应测试
- Modify: ml-platform/frontend/e2e/core-navigation.spec.ts；Create: ml-platform/frontend/e2e/generic-annotation-portal.spec.ts、automl-multioutput.spec.ts

**Interfaces:**
- Main platform client functions mirror GET/POST /api/annotation-tasks, preview, publish, execute, assignments, return batches and model exports.
- Portal client functions mirror POST /portal/auth/register/login/logout, GET /portal/tasks, GET samples, PUT labels, POST bulk-labels, confirm, edit-for-return, return and comments.
- AssignmentDialog emits {annotator_ids: string[], sample_scope: SampleScope, due_at?: string} and never accepts a client-owned project id.

- [ ] **Step 1: Write RED component and browser tests**

~~~typescript
it("keeps the task list context after automatic execution and exposes preview and assignment", async () => {
  render(<DataAnnotationPage />);
  expect(await screen.findByRole("button", { name: "预览" })).toBeVisible();
  expect(screen.getByRole("button", { name: "指派标注员" })).toBeVisible();
  expect(window.location.pathname).toBe("/data-annotation");
});

test("portal conflict dialog requires explicit complete-set confirmation", async () => {
  render(<TaskWorkspacePage />);
  await screen.findByText("版本冲突");
  expect(screen.getByRole("button", { name: "确认并覆盖完整标签" })).toBeDisabled();
});
~~~

Playwright must cover administrator multi-select assignment, annotator registration and approved login, unauthorized project refusal, automatic save, conflict confirmation, return lock, explicit edit and successful return.

- [ ] **Step 2: Run focused tests and verify the current UI lacks these flows**

Run:

~~~text
Set-Location ml-platform/frontend
npm test -- --run src/pages/DataAnnotationPage.test.tsx src/pages/AutoMLTaskPage.test.tsx
Set-Location ..\annotator\frontend
npm test -- --run
~~~

Expected: current pages navigate to a detail view, do not expose preview/assignment, or have no independent portal entry.

- [ ] **Step 3: Implement main-platform and portal interactions**

1. Keep DataAnnotationPage as a task-list operation center. Manual and automatic completion open a preview drawer and assignment dialog in place; neither flow pushes a detail route automatically.
2. Render automatic preview with model output, selected strategy, cluster distribution, rule hit counts, final per-column values and provenance. Render manual preview with sample range, visible columns and label schema.
3. Add multi-select annotator search, fixed scope summary, due time, overlap warning, assignment state and audit result. Disable submit when the server reports stale task_revision.
4. Render return batch list in DataManagePage with preview, comments, diff, accept and return actions. Keep notification center in-app only.
5. Build a separate Vite entry for the portal. Its router has only login, register, task queue and workspace; it does not import the main AppLayout, model pages or project selectors.
6. Use typed controls for int, float, string, enum, range and free text labels. Bulk labeling previews affected sample count and requires explicit confirmation to overwrite legal values.
7. Handle 409 revision conflicts by showing server complete label set and requiring explicit confirmation before resubmitting with the new base revision.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/frontend
npm test -- --run src/pages/DataAnnotationPage.test.tsx src/pages/AutoMLTaskPage.test.tsx src/pages/ModelLibraryPage.test.tsx
npm run build
Set-Location ..\annotator\frontend
npm test -- --run
npm run build
Set-Location ..\..
Set-Location ml-platform/frontend
npm run test:e2e -- e2e/generic-annotation-portal.spec.ts
~~~

Expected: no automatic redirect occurs, preview/assignment/return actions are visible and the independent portal works without loading main-platform authentication or navigation.

**Dependencies:** Tasks 5, 7, 8, 9, 10 and 11.

## Task 13: 异步 worker、幂等、恢复、清理和安全门禁

**Objective:** 让导入、预览、训练、聚类、回传和导出在重复请求、worker 重启和基础设施短暂故障下保持可恢复且失败封闭。

**Files:**
- Create: ml-platform/backend/tests/test_async_operation_contract.py、test_security_contract.py
- Modify: ml-platform/backend/app/tasks/celery_app.py、dispatcher.py、recovery.py、training_recovery.py、notification_tasks.py、app/services/artifact_service.py、config.py、main.py
- Modify: ml-platform/annotator/backend/app/config.py、app/main.py、services/session.py
- Modify: docker-compose.yml、docker-compose.acceptance.yml、backend/Dockerfile、backend/Dockerfile.worker、annotator/backend/Dockerfile
- Modify: ml-platform/backend/tests/week_manifest.py

**Interfaces:**
- claim_operation(db: Session, operation_id: UUID, worker_id: str, lease_seconds: int) -> bool
- heartbeat_operation(db: Session, operation_id: UUID, worker_id: str) -> None
- complete_operation(db: Session, operation_id: UUID, result_artifact_id: UUID, checksum: str) -> None
- cleanup_orphan_artifacts(storage: ArtifactStorage, older_than: timedelta) -> CleanupReport
- enforce_request_security(request: Request, policy: SecurityPolicy) -> None

- [ ] **Step 1: Write RED tests for lease recovery, duplicate keys, cleanup and web security**

~~~python
def test_expired_lease_can_be_reclaimed_once(db):
    assert claim_operation(db, operation_id, "worker-a", 30) is True
    assert claim_operation(db, operation_id, "worker-b", 30) is False
    expire_lease(db, operation_id)
    assert claim_operation(db, operation_id, "worker-b", 30) is True

def test_failed_operation_does_not_publish_partial_artifact(db):
    fail_operation(db, operation_id, "MODEL_EXPORT_FAILED")
    assert published_artifact(db, operation_id) is None
    assert operation_error_code(db, operation_id) == "MODEL_EXPORT_FAILED"

def test_cors_csrf_and_rate_limits_are_fail_closed(client):
    assert client.options("/portal/auth/login", headers={"Origin": "https://unknown.example"}).status_code == 403
    assert client.post("/portal/auth/login", headers={"Origin": allowed_origin}).status_code in (401, 403)
    for _ in range(6):
        client.post("/portal/auth/login", data={"username": "a", "password": "bad"})
    assert client.post("/portal/auth/login", data={"username": "a", "password": "bad"}).status_code == 429
~~~

- [ ] **Step 2: Run the tests and verify current worker/security gaps**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_async_operation_contract.py tests/test_security_contract.py -q
~~~

Expected: duplicate requests enqueue multiple workers, stale leases cannot be recovered, partial artifacts remain visible, or CORS/CSRF/rate limiting is permissive.

- [ ] **Step 3: Implement reliability and security controls**

1. Persist operation id, resource key, idempotency key, state, stage, progress, attempt, lease_owner, lease_expires_at, heartbeat and sanitized error details for every long operation.
2. Claim with a transaction and unique resource key. Retry one transient infrastructure error with exponential backoff; move further failures to failed and keep partial artifacts unpublished.
3. Mark artifacts committed only after database transaction, checksum, audit and result validation succeed. Clean abandoned temporary prefixes by TTL and keep cleanup audit records.
4. Add recovery tasks that reclaim expired leases and resume from committed stages. A repeated request returns the original operation and result.
5. Configure exact CORS allowlists for both origins, CSRF validation for state-changing cookie requests, secure cookies, service JWT/mTLS validation and the stated login/register/reset/bulk-label rate limits.
6. Enforce upload magic-byte checks, path traversal rejection, decompression limits, XML hardening and redacted error details. Add dependency lock and runtime image smoke checks.
7. Update the test week manifest in the same change as every new test module, then run the manifest contract before the full suite.

- [ ] **Step 4: Run GREEN verification**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_async_operation_contract.py tests/test_security_contract.py tests/test_suite_manifest.py -q
py -3.14 -m py_compile app/tasks/celery_app.py app/tasks/recovery.py app/services/artifact_service.py
docker compose -f ..\..\docker-compose.yml config
git diff --check
~~~

Expected: lease/retry/cleanup/security tests pass, every test module has one week owner, Compose has no wildcard credentialed CORS, and unpublished artifacts remain inaccessible.

**Dependencies:** Tasks 2, 5, 7, 8, 9, 10 and 11.

## Task 14: 全量验收、文档同步和发布门禁

**Objective:** 用可追溯证据验证方案覆盖，更新项目计划和用户文档，并在同一 SHA 上完成后端、前端、迁移、浏览器、导出和恢复验收。

**Files:**
- Modify: ml-platform/docs/api_reference.md、ml-platform/docs/user_guide.md、ml-platform/docs/technical-proposals/2026-09-01-general-automl-annotation-platform.md（仅在评审产生新决策时）、DEVELOPMENT_PLAN.md
- Create: ml-platform/docs/acceptance/2026-09-02-general-platform-acceptance-matrix.md、ml-platform/docs/acceptance/2026-09-02-export-runtime-checklist.md
- Modify: .github/workflows/ci.yml、ml-platform/backend/tests/week_manifest.py
- Create: ml-platform/backend/tests/test_acceptance_manifest.py、ml-platform/frontend/e2e/generic-platform-acceptance.spec.ts

**Interfaces:**
- Acceptance matrix maps DAT-01..02、LAB-01..02、CLU-01..02、CON-01..02、RET-01、AUTH-01..02、API-01、AUTO-01..02、EXP-01、INF-01 and REL-01 to exact test commands and evidence files.
- Release gate consumes current Git SHA, required job statuses, artifact hashes, migration head and browser receipts; old SHA or skipped evidence cannot satisfy the gate.

- [ ] **Step 1: Write the acceptance matrix and failing gate checks**

~~~python
def test_acceptance_manifest_rejects_skipped_required_evidence(manifest):
    manifest["evidence"]["EXP-01"]["status"] = "skipped"
    with pytest.raises(AcceptanceGateError) as error:
        validate_acceptance_manifest(manifest)
    assert error.value.code == "REQUIRED_EVIDENCE_NOT_PASSED"

def test_acceptance_manifest_binds_all_evidence_to_current_sha(manifest, current_sha):
    manifest["commit_sha"] = "old-sha"
    with pytest.raises(AcceptanceGateError):
        validate_acceptance_manifest(manifest, current_sha=current_sha)
~~~

- [ ] **Step 2: Run the gate tests and verify the matrix is incomplete**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_acceptance_manifest.py -q
~~~

Expected: no matrix or gate exists, or skipped/old-SHA evidence is accepted.

- [ ] **Step 3: Implement documentation and release evidence**

1. Document generic import formats, four AutoML types, CV/search choices, label columns, three strategies, cluster weighting, portal URL/port configuration, assignment, conflict handling, return lock, data-management acceptance, model registration and export contents.
2. Document all public and internal API contracts, error codes, cursor pagination, idempotency keys, revision headers, role matrix and security requirements. Keep historical records unchanged.
3. Add the acceptance matrix with exact commands for backend tests, frontend Vitest/build, Playwright, Alembic fresh/legacy upgrade, export validation, offline invalid-input tests, security checks and recovery rehearsal.
4. Generate a final evidence manifest containing current SHA, environment, migration head, test outputs, browser receipt, export hashes, SBOM/signature validation and recovery results. Store failed/cancelled/skipped evidence as such.
5. Update DEVELOPMENT_PLAN.md by appending this plan path, dependencies, current status planned and known risks. Do not mark any task complete before its implementation and required evidence exist.

- [ ] **Step 4: Run GREEN verification and release decision**

Run:

~~~text
Set-Location ml-platform/backend
py -3.14 -m pytest tests/test_acceptance_manifest.py tests/test_suite_manifest.py -q
py -3.14 run_suite.py
py -3.14 -m alembic upgrade head
Set-Location ..\frontend
npm test -- --run
npm run build
npm run test:e2e -- e2e/generic-platform-acceptance.spec.ts
Set-Location ..\..
git diff --check
~~~

Expected: the full suite, build, migration, browser, export and recovery evidence all bind to the same current SHA. Any required failure, cancellation, skip or missing artifact keeps the release status in_progress.

**Dependencies:** Tasks 1 through 13.

## Dependency and Delivery Order

1. Task 1 establishes the generic boundary and migration inventory.
2. Task 2 freezes data versions and input contracts.
3. Tasks 3 and 4 can proceed in parallel after Task 2; both are required by automatic annotation.
4. Task 5 builds task state and preview on top of data and label contracts.
5. Task 6 builds automatic strategies after model and label contracts are stable.
6. Task 7 establishes the independent annotator service; Task 8 adds assignment and concurrency.
7. Task 9 adds data-management acceptance after return semantics are stable.
8. Task 10 keeps manual model registration compatible with the existing registry path.
9. Task 11 requires registered model and automatic annotation artifacts.
10. Task 12 integrates the main and portal UIs after API contracts stabilize.
11. Task 13 hardens every long-running path and security boundary.
12. Task 14 is the final documentation, evidence and release gate.

## Requirements Coverage

| Requirement | Tasks |
|---|---|
| 全项目通用化 | 1 |
| CSV/Excel/Parquet/JSON/XML 导入 | 2 |
| 多标签分类和回归 | 3 |
| int/float/string 多列标签 | 4 |
| 手动/自动标注任务和预览 | 5、12 |
| cluster/rule/cluster_rule | 6 |
| 特征重要性加权 KMeans | 3、6 |
| 独立标注员注册登录和端口 8443 | 7、12 |
| 多选指派、重叠编辑和冲突确认 | 8、12 |
| 标注员主动回传、回传锁和数据管理验收 | 8、9、12 |
| 模型手动注册 | 10 |
| 模型导出、聚类/规则工件 | 11 |
| predict/annotate 输入输出一致性 | 11 |
| 异步恢复、清理、限流和安全 | 13 |
| 文档、CI、浏览器和最终发布门禁 | 14 |

## Known Risks and Controls

- 旧行业数据结构可能缺少可恢复的原始列：先保存原始 artifact，迁移只写入可验证的新版本，无法映射时进入 needs_review。
- 多输出算法能力不一致：算法目录在任务创建时做 capability 过滤，候选失败只影响自身，不生成不可注册结果。
- 大数据聚类内存不足：启动前估算资源，Silhouette 使用受限确定性样本，最终赋簇覆盖全量；超出配额直接阻断。
- 重叠标注冲突频繁：所有写入使用完整标签集合和 revision，冲突必须显式确认，不做静默覆盖。
- 独立门户部署配置错误：通过 origin/port 环境变量、Compose 合同和 Playwright 跨 origin 验收发现问题。
- 导出依赖或签名不可用：导出失败封闭，缺少签名、SBOM、校验和或锁定依赖时不开放下载。
- 测试模块新增后漏登记周次：每次新增 test_*.py 同步更新 week_manifest.py，并先运行 test_suite_manifest。

## Plan Completion Checklist

- [ ] Task 1 through Task 14 each have implementation diff, focused RED/GREEN evidence and dependency review.
- [ ] All new test modules have exactly one week-manifest owner.
- [ ] Main platform and annotator service use separate origins, sessions and credentials.
- [ ] All task, label, assignment, return, model and export state transitions are audited and revision guarded.
- [ ] Current SHA has passing required jobs, no required evidence is skipped, and migration/export/recovery evidence is present.
- [ ] DEVELOPMENT_PLAN.md contains the append-only plan record and unresolved risks without rewriting historical entries.
