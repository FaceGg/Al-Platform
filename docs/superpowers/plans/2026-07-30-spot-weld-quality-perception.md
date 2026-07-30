# 点焊质量感知与数据标注 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付报告同结构 CSV/XLSX 驱动的点焊质量感知闭环，并把独立导航“数据标注”作为第一项代码交付。

**Architecture:** 新建项目级质量感知子域，不复用无状态通用 labeling API 或图片标注模型。Artifact 保存原始/派生文件；专用 ORM 保存质量运行、样本、规则、标签修订和训练快照。独立 /data-annotation 路由展示四通道波形、自动标签和人工审核。

**Tech Stack:** React 18, TypeScript, Vite, Ant Design, ECharts, FastAPI, SQLAlchemy, Alembic, Celery, pandas, NumPy, scikit-learn, XGBoost, LightGBM, CatBoost, openpyxl, joblib.

---

## File Structure

**Frontend**
- Create: ml-platform/frontend/src/pages/DataAnnotationPage.tsx and DataAnnotationPage.test.tsx
- Create: ml-platform/frontend/src/api/spotWeldQuality.ts and spotWeldQuality.test.ts
- Create: ml-platform/frontend/src/components/spotWeld/WaveformPanel.tsx and WaveformPanel.test.tsx
- Modify: ml-platform/frontend/src/App.tsx, src/components/AppLayout.tsx, src/components/AppLayout.test.tsx, src/i18n/index.tsx, src/styles/global.css, src/weekAcceptance.test.ts
- Modify: ml-platform/frontend/src/pages/DataManagePage.tsx, AutoMLPage.tsx, ModelLibraryPage.tsx, MonitorPage.tsx and their existing tests

**Backend**
- Create: ml-platform/backend/app/models/spot_weld_quality.py
- Create: ml-platform/backend/app/services/spot_weld_features.py and spot_weld_quality.py
- Create: ml-platform/backend/app/api/spot_weld_quality.py
- Create: ml-platform/backend/app/tasks/spot_weld_quality_tasks.py
- Create: ml-platform/backend/alembic/versions/20260730_09_spot_weld_quality.py
- Create: ml-platform/backend/tests/test_spot_weld_features.py, test_spot_weld_quality_models.py, test_spot_weld_quality_service.py, test_api_spot_weld_quality.py, test_spot_weld_quality_tasks.py
- Modify: ml-platform/backend/app/models/__init__.py, app/main.py, alembic/env.py, app/services/project_access.py, app/tasks/celery_app.py, requirements.txt, tests/week_manifest.py
- Modify: app/services/model_registry.py only for explicit registration of a platform-generated quality model

## Task 0: Isolate the Dirty Worktree

**Files:**
- Modify: none

- [ ] **Step 1: Invoke worktree isolation and create the feature branch**

Use superpowers:using-git-worktrees. Then run:

~~~powershell
Set-Location E:/codex_workspace/agent_spot_welding
git status --short
git worktree add -b codex/spot-weld-quality E:/codex_workspace/agent_spot_welding-spot-weld-quality 49823ba
~~~

Expected: existing dirty files remain in original worktree; new worktree starts at the approved design commit.

- [ ] **Step 2: Capture local baseline evidence**

~~~powershell
Set-Location E:/codex_workspace/agent_spot_welding-spot-weld-quality/ml-platform/backend
& C:/Users/17723/miniconda3/python.exe run_suite.py
Set-Location ../frontend
npm test -- --run
npm run build
~~~

Expected: record backend, frontend and build outcomes separately; do not infer remote CI, Docker, authenticated browser, or production verification.

- [ ] **Step 3: Leave branch clean**

No commit. Task 1 is the first requested feature delivery.

## Task 1: Complete Independent “数据标注” Navigation and Shell First

**Files:**
- Create: ml-platform/frontend/src/pages/DataAnnotationPage.tsx
- Create: ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx
- Modify: ml-platform/frontend/src/App.tsx
- Modify: ml-platform/frontend/src/components/AppLayout.tsx and AppLayout.test.tsx
- Modify: ml-platform/frontend/src/i18n/index.tsx
- Modify: ml-platform/frontend/src/styles/global.css
- Modify: ml-platform/frontend/src/weekAcceptance.test.ts

- [ ] **Step 1: Write failing route/menu/page tests**

~~~tsx
it("shows the independent annotation workspace before a quality run exists", async () => {
  render(<AntApp><DataAnnotationPage /></AntApp>);
  expect(await screen.findByRole("heading", { name: "数据标注" })).toBeInTheDocument();
  expect(screen.getByLabelText("Project")).toBeInTheDocument();
  expect(screen.getByText("样本队列")).toBeInTheDocument();
  expect(screen.getByText("四通道波形")).toBeInTheDocument();
  expect(screen.getByText("标注与审核")).toBeInTheDocument();
});

it("renders data annotation as a dedicated sidebar link", async () => {
  renderLayoutAt("/");
  expect(await screen.findByText("数据标注")).toBeInTheDocument();
});
~~~

Add ./pages/DataAnnotationPage.test.tsx under frontend manifest week 17.

- [ ] **Step 2: Run tests and observe red state**

~~~powershell
Set-Location E:/codex_workspace/agent_spot_welding-spot-weld-quality/ml-platform/frontend
npm test -- --run src/components/AppLayout.test.tsx src/pages/DataAnnotationPage.test.tsx src/weekAcceptance.test.ts
~~~

Expected: FAIL because route, page, translations and menu item are missing.

- [ ] **Step 3: Add protected route, first menu item, translations and stable empty shell**

~~~tsx
const DataAnnotationPage = lazy(() => import("./pages/DataAnnotationPage"));

<Route
  path="/data-annotation"
  element={<ProtectedRoute><DataAnnotationPage /></ProtectedRoute>}
/>
~~~

Import TagsOutlined in AppLayout and insert before /data:

~~~tsx
{ key: "/data-annotation", icon: <TagsOutlined />, label: t.nav.data_annotation },
~~~

Add identical nav.data_annotation and spotWeld key shapes to Chinese/English dictionaries. DataAnnotationPage loads projects from /projects, renders aria-label="Project", and has fixed regions “样本队列”, “四通道波形”, “标注与审核”. Render Ant Design Empty when no run exists; do not create fake samples.

~~~css
.spot-weld-annotation__workspace {
  display: grid;
  grid-template-columns: minmax(220px, .8fr) minmax(420px, 1.6fr) minmax(260px, 1fr);
  gap: 16px;
}
@media (max-width: 900px) {
  .spot-weld-annotation__workspace { grid-template-columns: minmax(0, 1fr); }
}
~~~

- [ ] **Step 4: Verify green state**

~~~powershell
npm test -- --run src/components/AppLayout.test.tsx src/pages/DataAnnotationPage.test.tsx src/weekAcceptance.test.ts
npm run build
~~~

Expected: PASS. Existing /annotations image route is unchanged.

- [ ] **Step 5: Commit the navigation-first slice**

~~~powershell
git add ml-platform/frontend/src/App.tsx ml-platform/frontend/src/components/AppLayout.tsx ml-platform/frontend/src/components/AppLayout.test.tsx ml-platform/frontend/src/i18n/index.tsx ml-platform/frontend/src/pages/DataAnnotationPage.tsx ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx ml-platform/frontend/src/styles/global.css ml-platform/frontend/src/weekAcceptance.test.ts
git commit -m "feat: add data annotation navigation"
~~~

## Task 2: Add Models, Migration, and Explicit Quality Roles

**Files:**
- Create: ml-platform/backend/app/models/spot_weld_quality.py
- Create: ml-platform/backend/alembic/versions/20260730_09_spot_weld_quality.py
- Create: ml-platform/backend/tests/test_spot_weld_quality_models.py
- Modify: ml-platform/backend/app/models/__init__.py, app/main.py, alembic/env.py
- Modify: ml-platform/backend/app/services/project_access.py, tests/test_project_access.py, tests/week_manifest.py

- [ ] **Step 1: Write failing persistence and permission tests**

~~~python
def test_quality_permissions_are_explicit():
    assert "quality.label" in ROLE_PERMISSIONS[ProjectRole.OPERATOR]
    assert "quality.review" not in ROLE_PERMISSIONS[ProjectRole.OPERATOR]
    assert {"quality.label", "quality.review"} <= ROLE_PERMISSIONS[ProjectRole.EDITOR]
    assert "quality.label" not in ROLE_PERMISSIONS[ProjectRole.VIEWER]
~~~

Create project, Artifact, run, sample, revision and snapshot; delete the project and assert dependent rows are gone. Register test_spot_weld_quality_models under backend week 17.

- [ ] **Step 2: Run tests and observe red state**

~~~powershell
Set-Location E:/codex_workspace/agent_spot_welding-spot-weld-quality/ml-platform/backend
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_spot_weld_quality_models tests.test_project_access
~~~

Expected: FAIL on missing imports and permissions.

- [ ] **Step 3: Implement normalized project-scoped persistence**

~~~python
class SpotWeldQualityRun(Base):
    __tablename__ = "spot_weld_quality_runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_artifact_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"), nullable=False)
    status = Column(String(32), nullable=False, default="validating")
    field_mapping = Column(JSON, nullable=False, default=dict)
    feature_schema = Column(JSON, nullable=False, default=list)
    statistics = Column(JSON, nullable=False, default=dict)
    automl_results = Column(JSON, nullable=False, default=list)
    clustering_results = Column(JSON, nullable=False, default=dict)
    output_artifacts = Column(JSON, nullable=False, default=dict)
    task_id = Column(String(128), nullable=True, index=True)
    error_code = Column(String(64), nullable=True)

class SpotWeldQualitySample(Base):
    __tablename__ = "spot_weld_quality_samples"
    run_id = Column(UUID(as_uuid=True), ForeignKey("spot_weld_quality_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    source_row_index = Column(Integer, nullable=False)
    automatic_label = Column(String(64), nullable=True)
    rule_hits = Column(JSON, nullable=False, default=list)
    review_status = Column(String(24), nullable=False, default="pending_review")
~~~

Add rule-set, label-revision and label-snapshot models with project/run/sample foreign keys, timestamps, a unique run/source-row pair, and query indexes. Import model module in models init, main and Alembic env. Add quality.label/quality.review permissions: owner/editor both, operator quality.label only.

Generate migration from current single head. Run alembic heads immediately before generation; planning baseline is 20260718_08.

- [ ] **Step 4: Verify models and migration**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_spot_weld_quality_models tests.test_project_access
& C:/Users/17723/miniconda3/python.exe -m compileall -q app
alembic upgrade head
alembic downgrade -1
alembic upgrade head
~~~

Expected: PASS with reversible migration.

- [ ] **Step 5: Commit**

~~~powershell
git add ml-platform/backend/app/models/spot_weld_quality.py ml-platform/backend/app/models/__init__.py ml-platform/backend/app/main.py ml-platform/backend/alembic/env.py ml-platform/backend/alembic/versions/20260730_09_spot_weld_quality.py ml-platform/backend/app/services/project_access.py ml-platform/backend/tests/test_spot_weld_quality_models.py ml-platform/backend/tests/test_project_access.py ml-platform/backend/tests/week_manifest.py
git commit -m "feat: add spot weld quality models"
~~~

## Task 3: Build Strict Waveform Decode and 73-Feature Service

**Files:**
- Create: ml-platform/backend/app/services/spot_weld_features.py
- Create: ml-platform/backend/tests/test_spot_weld_features.py
- Modify: ml-platform/backend/tests/week_manifest.py

- [ ] **Step 1: Write failing feature contracts**

~~~python
def waveform_payload() -> str:
    values = np.arange(870, dtype=">i2")
    return base64.b64encode(values.tobytes()).decode("ascii")

def test_decode_report_waveform_uses_big_endian_int16():
    decoded = decode_waveform(waveform_payload(), field_name="cvei", row_index=0)
    assert decoded.shape == (870,)
    assert decoded[1] == 1.0

def test_invalid_waveform_length_is_not_repaired():
    with pytest.raises(QualityPipelineError, match="QUALITY_WAVEFORM_LENGTH_INVALID"):
        decode_waveform(base64.b64encode(b"x" * 12).decode("ascii"), field_name="cvei", row_index=7)

def test_feature_schema_has_exactly_73_unique_names():
    frame, schema, _statistics = build_feature_frame(report_like_frame())
    assert len(schema) == 73
    assert len(set(schema)) == 73
    assert list(frame.columns) == schema
~~~

- [ ] **Step 2: Run tests and observe red state**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m pytest tests/test_spot_weld_features.py -q
~~~

Expected: FAIL because service is absent.

- [ ] **Step 3: Implement exact decoder and report_v1 features**

~~~python
WAVEFORM_BYTES = 1740
WAVEFORM_POINTS = 870

def decode_waveform(encoded: str, *, field_name: str, row_index: int) -> np.ndarray:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError, binascii.Error) as error:
        raise QualityPipelineError("QUALITY_WAVEFORM_INVALID_BASE64", row_index=row_index, field_name=field_name) from error
    if len(raw) != WAVEFORM_BYTES:
        raise QualityPipelineError("QUALITY_WAVEFORM_LENGTH_INVALID", row_index=row_index, field_name=field_name)
    values = np.frombuffer(raw, dtype=">i2").astype(np.float64)
    if values.shape != (WAVEFORM_POINTS,):
        raise QualityPipelineError("QUALITY_WAVEFORM_LENGTH_INVALID", row_index=row_index, field_name=field_name)
    return values
~~~

Expose immutable report_v1 field/schema constants, mapping validation, frame validation, 12 wave statistics per channel and 25 table features. Raise QUALITY_FEATURE_NONFINITE for zero divisions/infinite values. Do not pad, truncate, impute or silently drop rows.

- [ ] **Step 4: Verify green state**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m pytest tests/test_spot_weld_features.py -q
~~~

Expected: PASS for decode, Base64, byte length, mapping and fixed 73 ordering.

- [ ] **Step 5: Commit**

~~~powershell
git add ml-platform/backend/app/services/spot_weld_features.py ml-platform/backend/tests/test_spot_weld_features.py ml-platform/backend/tests/week_manifest.py
git commit -m "feat: add spot weld feature extraction"
~~~

## Task 4: Validate Artifacts and Create Immutable Quality Runs

**Files:**
- Create: ml-platform/backend/app/api/spot_weld_quality.py
- Create: ml-platform/backend/app/services/spot_weld_quality.py
- Create: ml-platform/backend/tests/test_api_spot_weld_quality.py
- Modify: ml-platform/backend/app/main.py, tests/week_manifest.py

- [ ] **Step 1: Write failing validation/run API tests**

~~~python
response = client.post(
    "/api/projects/" + project_id + "/spot-weld/validate",
    json={"dataset_artifact_id": dataset_id, "field_mapping": REPORT_MAPPING},
    headers=owner_headers,
)
assert response.status_code == 200
assert response.json()["valid_rows"] == 2

denied = client.post(
    "/api/projects/" + other_project_id + "/spot-weld/runs",
    json={"dataset_artifact_id": dataset_id, "field_mapping": REPORT_MAPPING},
    headers=owner_headers,
)
assert denied.status_code == 400
assert denied.json()["detail"]["code"] == "DATASET_ARTIFACT_INVALID"
~~~

- [ ] **Step 2: Run and observe red state**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_api_spot_weld_quality
~~~

Expected: FAIL because quality router is absent.

- [ ] **Step 3: Implement Artifact-only validation/run API**

~~~python
dataset = artifact_service.resolve(dataset_artifact_id, project_id, expected_type="dataset")
with artifact_service.materialize(dataset.id, project_id, expected_type="dataset") as path:
    frame = read_report_dataset(path)
~~~

Validate returns row counts, row errors, mapped fields and never Base64 payload. Persist input Artifact ID/SHA-256, mapping, report_v1 version, rule version and validation-report Artifact. Add:

~~~text
POST /api/projects/{project_id}/spot-weld/validate
POST /api/projects/{project_id}/spot-weld/runs
GET  /api/projects/{project_id}/spot-weld/runs
GET  /api/projects/{project_id}/spot-weld/runs/{run_id}
~~~

Require resource.create for validation/create, project.read for reads, and project_action audit with metadata-only changes.

- [ ] **Step 4: Verify**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_api_spot_weld_quality tests.test_artifact_storage_integration
~~~

Expected: PASS for CSV/XLSX, invalid mappings, invalid Base64, project isolation and safe audit output.

- [ ] **Step 5: Commit**

~~~powershell
git add ml-platform/backend/app/api/spot_weld_quality.py ml-platform/backend/app/services/spot_weld_quality.py ml-platform/backend/app/main.py ml-platform/backend/tests/test_api_spot_weld_quality.py ml-platform/backend/tests/week_manifest.py
git commit -m "feat: validate spot weld quality datasets"
~~~

## Task 5: Implement Report-Compatible AutoML, Cluster, PCA, and Rules

**Files:**
- Modify: ml-platform/backend/app/services/spot_weld_quality.py, requirements.txt
- Create: ml-platform/backend/tests/test_spot_weld_quality_service.py
- Modify: ml-platform/backend/tests/week_manifest.py

- [ ] **Step 1: Write failing algorithm tests**

~~~python
def test_candidate_selection_orders_auc_then_f1_then_index():
    results = [
        CandidateResult("lgb", auc=0.91, f1=0.80, config_index=0),
        CandidateResult("cat", auc=0.91, f1=0.82, config_index=1),
    ]
    assert select_best_candidate(results).name == "cat"

def test_report_rules_keep_all_hits_in_table_order():
    result = apply_report_v1_rules(
        {"wld_spatter_strength": 3, "power_std": 99},
        thresholds={"power_std_p95": 1},
    )
    assert result.primary_label == "strong_splatter"
    assert [hit.code for hit in result.hits] == ["strong_splatter", "power_fluctuation"]

def test_zero_spot_diameter_is_not_virtual_weld():
    assert "spot_too_small" not in apply_report_v1_rules({"spotdiameter": 0}, thresholds={}).hit_codes
~~~

- [ ] **Step 2: Run and observe red state**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m pytest tests/test_spot_weld_quality_service.py -q
~~~

Expected: FAIL on missing candidates, clustering and rules.

- [ ] **Step 3: Implement deterministic algorithm layer**

Add fixed LGB_v1/v2, XGB_v1/v2, CAT_v1/v2, GBDT_v1, RF_v1, ET_v1 and HGB_v1 configurations. Lazy-import LightGBM/CatBoost; missing import raises QUALITY_AUTOML_DEPENDENCY_UNAVAILABLE.

~~~python
def select_best_candidate(results: list[CandidateResult]) -> CandidateResult:
    successful = [result for result in results if result.error_code is None]
    if not successful:
        raise QualityPipelineError("QUALITY_AUTOML_ALL_CANDIDATES_FAILED")
    return max(successful, key=lambda item: (item.auc, item.f1, -item.config_index))
~~~

Use three-fold StratifiedKFold(random_state=42), binary AUC or macro OvR AUC, macro F1, StandardScaler, square-root importance weights, K=2..8 silhouette search, PCA and anomaly role by spatter_total then abs(energy_dev) then raw cluster ID. Rules are strong/weak splatter, small/large spot, energy, current jump, power fluctuation, anomaly cluster, normal. Save every hit, primary label, thresholds and rule version.

- [ ] **Step 4: Install dependencies and verify**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m pip install -r requirements.txt
& C:/Users/17723/miniconda3/python.exe -m pytest tests/test_spot_weld_quality_service.py -q
~~~

Expected: packages resolve; ranking, K search, PCA, rule and zero-diameter tests PASS.

- [ ] **Step 5: Commit**

~~~powershell
git add ml-platform/backend/app/services/spot_weld_quality.py ml-platform/backend/requirements.txt ml-platform/backend/tests/test_spot_weld_quality_service.py ml-platform/backend/tests/week_manifest.py
git commit -m "feat: add spot weld quality automl pipeline"
~~~

## Task 6: Add Durable Tasks and API Dispatch

**Files:**
- Create: ml-platform/backend/app/tasks/spot_weld_quality_tasks.py and tests/test_spot_weld_quality_tasks.py
- Modify: ml-platform/backend/app/api/spot_weld_quality.py, app/services/spot_weld_quality.py, app/tasks/celery_app.py, tests/test_api_spot_weld_quality.py

- [ ] **Step 1: Write failing queue/task contracts**

~~~python
def test_start_run_persists_queued_task_id(client, quality_dispatcher):
    response = client.post(run_url, json=run_payload)
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["task_id"] == "quality-task-1"

def test_task_failure_has_stable_code():
    outcome = execute_spot_weld_quality_task.run("not-a-run")
    assert outcome["status"] == "failed"
    assert outcome["error_code"] == "QUALITY_RUN_NOT_FOUND"
~~~

- [ ] **Step 2: Run and observe red state**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_spot_weld_quality_tasks tests.test_api_spot_weld_quality
~~~

Expected: FAIL because dispatcher/task are absent.

- [ ] **Step 3: Implement dispatcher and task ownership**

Create CeleryQualityDispatcher with enqueue(run_id) and test injection at request.app.state.quality_dispatcher.

~~~python
@celery_app.task(bind=True, name="ml_platform.execute_spot_weld_quality")
def execute_spot_weld_quality_task(self, run_id: str):
    result = execute_quality_run(
        uuid.UUID(run_id),
        worker_id=self.request.hostname or "worker",
        task_id=self.request.id or "unknown",
    )
    return result.to_dict()
~~~

Claim only queued/validating runs, save task ID, create generated Artifacts, and persist exact QualityPipelineError code on failure. Register task module in Celery include and import block.

- [ ] **Step 4: Verify**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_spot_weld_quality_tasks tests.test_api_spot_weld_quality
~~~

Expected: PASS for queueing, duplicate claim skip, dispatch failure and registration.

- [ ] **Step 5: Commit**

~~~powershell
git add ml-platform/backend/app/tasks/spot_weld_quality_tasks.py ml-platform/backend/app/api/spot_weld_quality.py ml-platform/backend/app/services/spot_weld_quality.py ml-platform/backend/app/tasks/celery_app.py ml-platform/backend/tests/test_spot_weld_quality_tasks.py ml-platform/backend/tests/test_api_spot_weld_quality.py
git commit -m "feat: run spot weld quality jobs asynchronously"
~~~

## Task 7: Add Label Revision, Review, Snapshot, and Access APIs

**Files:**
- Modify: ml-platform/backend/app/api/spot_weld_quality.py, app/services/spot_weld_quality.py
- Modify: ml-platform/backend/tests/test_api_spot_weld_quality.py, test_spot_weld_quality_service.py

- [ ] **Step 1: Write failing state/IDOR tests**

~~~python
created = client.post(sample_label_url, json={"label": "power_fluctuation", "note": "waveform confirmed"}, headers=operator_headers)
assert created.status_code == 201
assert created.json()["review_status"] == "submitted"

reviewed = client.post(sample_review_url, json={"decision": "approved", "comment": "verified"}, headers=editor_headers)
assert reviewed.status_code == 200
assert reviewed.json()["review_status"] == "approved"

assert client.post(sample_review_url, json={"decision": "approved"}, headers=operator_headers).status_code == 403
assert client.get(other_project_sample_url, headers=viewer_headers).status_code == 404
~~~

- [ ] **Step 2: Run and observe red state**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_api_spot_weld_quality
~~~

Expected: FAIL because mutation routes are absent.

- [ ] **Step 3: Implement append-only routes**

~~~text
GET  /api/projects/{project_id}/spot-weld/runs/{run_id}/samples
GET  /api/projects/{project_id}/spot-weld/runs/{run_id}/samples/{sample_id}
POST /api/projects/{project_id}/spot-weld/runs/{run_id}/samples/{sample_id}/labels
POST /api/projects/{project_id}/spot-weld/runs/{run_id}/samples/{sample_id}/review
POST /api/projects/{project_id}/spot-weld/runs/{run_id}/label-snapshots
GET  /api/projects/{project_id}/spot-weld/runs/{run_id}/label-snapshots
~~~

Each write inserts SpotWeldLabelRevision; never update historical rows. Cache current review status only on sample. Require quality.label for submission and quality.review for approval/return. Snapshot only approved sample/revision/label tuples. Before training reject any class with fewer than five rows using QUALITY_LABELS_INSUFFICIENT_FOR_5_FOLD. Audit label/review/snapshot actions without waveform or Base64 payloads.

- [ ] **Step 4: Verify**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m unittest tests.test_api_spot_weld_quality tests.test_project_access
~~~

Expected: PASS for revisions, approval, operator denial, viewer read-only, hidden foreign resources and immutable snapshot.

- [ ] **Step 5: Commit**

~~~powershell
git add ml-platform/backend/app/api/spot_weld_quality.py ml-platform/backend/app/services/spot_weld_quality.py ml-platform/backend/tests/test_api_spot_weld_quality.py ml-platform/backend/tests/test_spot_weld_quality_service.py
git commit -m "feat: add spot weld label review workflow"
~~~

## Task 8: Connect Data Annotation UI to Real Data

**Files:**
- Create: ml-platform/frontend/src/api/spotWeldQuality.ts and spotWeldQuality.test.ts
- Create: ml-platform/frontend/src/components/spotWeld/WaveformPanel.tsx and WaveformPanel.test.tsx
- Modify: ml-platform/frontend/src/pages/DataAnnotationPage.tsx, DataAnnotationPage.test.tsx, src/styles/global.css, src/weekAcceptance.test.ts

- [ ] **Step 1: Write failing client/UI interaction test**

~~~tsx
it("loads samples, renders four channels, and submits a label", async () => {
  listQualityRuns.mockResolvedValue([completedRun]);
  listQualitySamples.mockResolvedValue([sample]);
  getQualitySample.mockResolvedValue({ ...sample, waveforms: waveformPayload });
  render(<AntApp><DataAnnotationPage /></AntApp>);
  await userEvent.selectOptions(screen.getByLabelText("Project"), "project-1");
  await userEvent.click(screen.getByText("W-0001"));
  expect(await screen.findByText("电流")).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("人工标签"), "power_fluctuation");
  await userEvent.click(screen.getByRole("button", { name: "提交复核" }));
  expect(submitQualityLabel).toHaveBeenCalled();
});
~~~

- [ ] **Step 2: Run and observe red state**

~~~powershell
Set-Location E:/codex_workspace/agent_spot_welding-spot-weld-quality/ml-platform/frontend
npm test -- --run src/api/spotWeldQuality.test.ts src/components/spotWeld/WaveformPanel.test.tsx src/pages/DataAnnotationPage.test.tsx
~~~

Expected: FAIL because typed API/chart component are absent.

- [ ] **Step 3: Implement typed project-scoped client and charts**

~~~ts
export async function listQualitySamples(projectId: string, runId: string, params: QualitySampleFilters = {}) {
  const response = await apiClient.get(
    "/projects/" + projectId + "/spot-weld/runs/" + runId + "/samples",
    { params },
  );
  return response.data.items as QualitySample[];
}
~~~

WaveformPanel creates four fixed-height ECharts line charts with shared dataZoom/axis-pointer and disposes all charts in useEffect cleanup. Page hydrates URL projectId/datasetId, queues, filters, details, labels, reviews, role-disabled states and formatApiError. Browser never decodes Base64 and never reuses image canvas behavior.

- [ ] **Step 4: Verify**

~~~powershell
npm test -- --run src/api/spotWeldQuality.test.ts src/components/spotWeld/WaveformPanel.test.tsx src/pages/DataAnnotationPage.test.tsx src/weekAcceptance.test.ts
npm run build
~~~

Expected: PASS for client payloads, four channels, label/review interactions, viewer disabled actions and responsive layout.

- [ ] **Step 5: Commit**

~~~powershell
git add ml-platform/frontend/src/api/spotWeldQuality.ts ml-platform/frontend/src/api/spotWeldQuality.test.ts ml-platform/frontend/src/components/spotWeld/WaveformPanel.tsx ml-platform/frontend/src/components/spotWeld/WaveformPanel.test.tsx ml-platform/frontend/src/pages/DataAnnotationPage.tsx ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx ml-platform/frontend/src/styles/global.css ml-platform/frontend/src/weekAcceptance.test.ts
git commit -m "feat: connect spot weld data annotation"
~~~

## Task 9: Extend Existing Data, AutoML, Model Library, and Monitor Pages

**Files:**
- Modify: ml-platform/frontend/src/pages/DataManagePage.tsx and DataManagePage.test.tsx
- Modify: ml-platform/frontend/src/pages/AutoMLPage.tsx and AutoMLPage.test.tsx
- Modify: ml-platform/frontend/src/pages/ModelLibraryPage.tsx and ModelLibraryPage.test.tsx
- Modify: ml-platform/frontend/src/pages/MonitorPage.tsx
- Modify: ml-platform/frontend/src/api/spotWeldQuality.ts and backend api/spot_weld_quality.py

- [ ] **Step 1: Write failing extension tests**

~~~tsx
it("opens annotation with selected dataset", async () => {
  render(<AntApp><DataManagePage /></AntApp>);
  await userEvent.click(await screen.findByLabelText("质量感知 weld.csv"));
  expect(navigate).toHaveBeenCalledWith("/data-annotation?projectId=project-1&datasetId=dataset-1");
});

it("starts a quality run from the AutoML quality recipe", async () => {
  render(<AntApp><AutoMLPage /></AntApp>);
  await userEvent.click(screen.getByRole("tab", { name: "点焊质量感知" }));
  await userEvent.click(screen.getByRole("button", { name: "运行质量感知" }));
  expect(createQualityRun).toHaveBeenCalled();
});
~~~

- [ ] **Step 2: Run and observe red state**

~~~powershell
npm test -- --run src/pages/DataManagePage.test.tsx src/pages/AutoMLPage.test.tsx src/pages/ModelLibraryPage.test.tsx
~~~

Expected: FAIL because quality actions/tabs/metadata are absent.

- [ ] **Step 3: Implement page handoff and summaries**

DataManage adds tooltip/icon action labelled “质量感知 <filename>” for project CSV/XLS/XLSX and navigates to /data-annotation with projectId/datasetId. Preserve preview/download/delete.

AutoML adds quality tab calling createQualityRun/getQualityRun, renders AUC/F1/K-search/PCA and links to annotation. It never calls generic /training/automl/run. ModelLibrary shows params.quality_run_id, feature_version, label_snapshot_id and rule_set_version tags. Quality API exposes project warning summary for MonitorPage; each warning routes to selected sample.

- [ ] **Step 4: Verify**

~~~powershell
npm test -- --run src/pages/DataManagePage.test.tsx src/pages/AutoMLPage.test.tsx src/pages/ModelLibraryPage.test.tsx
npm run build
~~~

Expected: PASS with generic behavior preserved.

- [ ] **Step 5: Commit**

~~~powershell
git add ml-platform/frontend/src/pages/DataManagePage.tsx ml-platform/frontend/src/pages/DataManagePage.test.tsx ml-platform/frontend/src/pages/AutoMLPage.tsx ml-platform/frontend/src/pages/AutoMLPage.test.tsx ml-platform/frontend/src/pages/ModelLibraryPage.tsx ml-platform/frontend/src/pages/ModelLibraryPage.test.tsx ml-platform/frontend/src/pages/MonitorPage.tsx ml-platform/frontend/src/api/spotWeldQuality.ts ml-platform/backend/app/api/spot_weld_quality.py
git commit -m "feat: expose spot weld quality workflow"
~~~

## Task 10: Train Approved Labels, Produce Warnings, and Generate Report Artifacts

**Files:**
- Modify: ml-platform/backend/app/services/spot_weld_quality.py, app/tasks/spot_weld_quality_tasks.py, app/api/spot_weld_quality.py
- Modify: ml-platform/backend/tests/test_spot_weld_quality_service.py, test_spot_weld_quality_tasks.py, test_api_spot_weld_quality.py
- Modify: ml-platform/backend/app/services/model_registry.py only for explicit quality registry registration

- [ ] **Step 1: Write failing training/report tests**

~~~python
def test_training_uses_frozen_approved_snapshot(service, snapshot):
    result = service.train_snapshot(snapshot.id)
    assert result.model_library.params["label_snapshot_id"] == str(snapshot.id)
    assert result.model_library.params["feature_version"] == "report_v1"

def test_probability_maps_to_four_warning_levels():
    assert warning_level(0.8) == "critical"
    assert warning_level(0.6) == "warning"
    assert warning_level(0.3) == "notice"
    assert warning_level(0.299) == "none"

def test_report_has_eight_named_sheets(report_path):
    assert load_workbook(report_path).sheetnames == [
        "总览", "AutoML选型", "深度学习对比", "缺陷标签",
        "聚类画像", "特征重要性", "推理结果", "多分类评估",
    ]
~~~

- [ ] **Step 2: Run and observe red state**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m pytest tests/test_spot_weld_quality_service.py tests/test_spot_weld_quality_tasks.py tests/test_api_spot_weld_quality.py -q
~~~

Expected: FAIL because training/prediction/report behavior is missing.

- [ ] **Step 3: Implement generated-only training and result artifacts**

Train LightGBM, MLP 128-64-32, MLP 256-128-64 and table-only MLP 128-64-32 using five-fold stratification. Enforce five samples per class, then choose final model by AUC/F1. Create only platform-generated model/preprocessor/schema/label Artifact with source spot_weld_quality and ModelLibrary params quality run ID, feature version, rule version and snapshot ID.

Batch prediction reads frozen feature Artifact and maps >=0.8 critical, >=0.6 warning, >=0.3 notice, otherwise none. Generate XLSX Artifact with the eight tested sheets. Explicit model-registry registration requires matching completed quality job, Artifact, ModelLibrary and source; never broaden trusted artifacts.

- [ ] **Step 4: Verify**

~~~powershell
& C:/Users/17723/miniconda3/python.exe -m pytest tests/test_spot_weld_quality_service.py tests/test_spot_weld_quality_tasks.py tests/test_api_spot_weld_quality.py -q
& C:/Users/17723/miniconda3/python.exe -m compileall -q app
~~~

Expected: PASS for snapshot isolation, warnings, provenance, workbook order and project isolation.

- [ ] **Step 5: Commit**

~~~powershell
git add ml-platform/backend/app/services/spot_weld_quality.py ml-platform/backend/app/tasks/spot_weld_quality_tasks.py ml-platform/backend/app/api/spot_weld_quality.py ml-platform/backend/tests/test_spot_weld_quality_service.py ml-platform/backend/tests/test_spot_weld_quality_tasks.py ml-platform/backend/tests/test_api_spot_weld_quality.py ml-platform/backend/app/services/model_registry.py
git commit -m "feat: train and alert on spot weld quality"
~~~

## Task 11: Validate Delivery and Update Required Records

**Files:**
- Modify: DEVELOPMENT_PLAN.md
- Modify: C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md
- Modify: docs/未解决bug清单.md only when a newly confirmed unresolved defect exists

- [ ] **Step 1: Run complete local quality verification**

~~~powershell
Set-Location E:/codex_workspace/agent_spot_welding-spot-weld-quality/ml-platform/backend
& C:/Users/17723/miniconda3/python.exe -m pytest tests/test_spot_weld_features.py tests/test_spot_weld_quality_models.py tests/test_spot_weld_quality_service.py tests/test_api_spot_weld_quality.py tests/test_spot_weld_quality_tasks.py -q
& C:/Users/17723/miniconda3/python.exe run_suite.py
Set-Location ../frontend
npm test -- --run
npm run build
~~~

Expected: record focused/full backend, full frontend and build evidence separately.

- [ ] **Step 2: Run authorized browser validation**

Use an existing authorized project and user-provided report-shaped CSV/XLSX. Verify upload, mapping, completed run, candidate table, K search, queue, four waveforms, operator submission, editor review, snapshot, model provenance, warning link and report download. Do not fabricate credentials, localStorage or protected-route data.

- [ ] **Step 3: Verify migration and diff**

~~~powershell
Set-Location E:/codex_workspace/agent_spot_welding-spot-weld-quality/ml-platform/backend
alembic upgrade head
& C:/Users/17723/miniconda3/python.exe -m compileall -q app tests
Set-Location ../..
git diff --check
git status --short
~~~

Expected: database at head, compilation succeeds and diff is clean.

- [ ] **Step 4: Append evidence**

Append verified status, results, risks and remaining work to DEVELOPMENT_PLAN.md. Append observed behavior, root cause, solution, verification and prevention to C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md. Modify docs/未解决bug清单.md only for a confirmed unresolved defect.

- [ ] **Step 5: Commit delivery records**

~~~powershell
git add DEVELOPMENT_PLAN.md
git commit -m "docs: record spot weld quality delivery"
~~~

Add docs/未解决bug清单.md only when it changed; never stage unrelated original-worktree files.

## Coverage Review

- Upload, mapping, strict >i2 decode, 870 points and 73 features: Tasks 3-4.
- 10 configurations, AUC/F1, weighted KMeans, K search, PCA and weak labels: Task 5.
- Durable execution and output Artifacts: Task 6.
- Requested independent navigation first, then real annotation UI: Tasks 1 and 8.
- Project roles, audit, revisions and snapshots: Tasks 2 and 7.
- Data/AutoML/model/monitor extensions: Task 9.
- LightGBM/MLP, warnings and report workbook: Task 10.
- Project records and local-vs-remote evidence: Task 11.

## Plan Self-Review

- Every approved design section maps to a numbered task.
- Every quality route carries project ID before loading Artifact/run/sample.
- Every executable model Artifact is platform generated.
- Backend/frontend test manifests include each new test.
- Task 1 is the user-requested “数据标注” navigation/page delivery.
