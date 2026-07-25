# Workflow Operator Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make workflow parameters, Join configuration, spreadsheet import, export destinations, node port labels, and execution workspaces reliable and isolated.

**Architecture:** Add declarative required-parameter metadata to the existing operator contract and validate every node before a run is created or scheduled. Preserve existing operator IDs and workflow payloads; use a workflow/run-scoped DataBus workspace for backend files and a browser directory handle for an explicitly selected client-side export directory. Keep ReactFlow handle IDs, positions, and edge persistence unchanged while rendering short labels adjacent to ports.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, Python unittest, pandas, React 18, TypeScript, Zustand, Ant Design, ReactFlow, Vitest.

---

### Task 1: Required Parameter Contract And Preflight Validation

**Files:**
- Modify: `ml-platform/backend/app/engine/base_operator.py`
- Modify: `ml-platform/backend/app/engine/operator_contract.py`
- Modify: `ml-platform/backend/app/engine/dag_executor.py`
- Modify: `ml-platform/backend/app/schemas/operator.py`
- Modify: `ml-platform/backend/app/api/operators.py`
- Modify: `ml-platform/backend/app/operators/blending.py`
- Modify: `ml-platform/backend/app/operators/control_operators.py`
- Modify: `ml-platform/backend/app/operators/io_operators.py`
- Modify: `ml-platform/backend/app/operators/processing.py`
- Modify: `ml-platform/backend/app/operators/utility_operators.py`
- Modify: `ml-platform/backend/app/operators/visualization.py`
- Test: `ml-platform/backend/tests/test_operator_contract.py`
- Test: `ml-platform/backend/tests/test_dag.py`
- Test: `ml-platform/backend/tests/test_api_runs.py`
- Test: `ml-platform/backend/tests/test_workflow_operator_regressions.py`

- [x] **Step 1: Write failing contract and DAG tests**

```python
def test_required_parameter_rejects_missing_and_whitespace(self):
    spec = ParamSpec("dataset", "str", "", required=True)
    for value in ({}, {"dataset": "   "}):
        with self.assertRaisesRegex(OperatorContractError, "OPERATOR_PARAM_REQUIRED"):
            validate_operator_params([spec], value)

def test_execute_rejects_required_parameters_before_any_node_runs(self):
    executor = DAGExecutor([
        {"id": "import", "operator_id": "csv_import", "params": {"source": "local"}},
        {"id": "join", "operator_id": "join", "params": {"left_keys": "", "right_keys": ""}},
    ], [])
    with self.assertRaisesRegex(RuntimeError, "OPERATOR_PARAM_REQUIRED"):
        executor.execute("run")
```

- [x] **Step 2: Run failing backend tests**

Run: `python -m unittest tests.test_operator_contract tests.test_dag -v`

Expected: FAIL because `ParamSpec` has no `required` field and DAG validation does not validate node parameters.

- [x] **Step 3: Add declarative metadata and validation**

```python
@dataclass
class ParamSpec:
    # existing fields
    required: bool = False
    required_when: dict[str, Any] | None = None

def validate_operator_params(specs, params):
    # validate unknown keys and coerce all values first
    # then reject None and whitespace-only strings when the requirement is active
    raise OperatorContractError("OPERATOR_PARAM_REQUIRED", ...)
```

`DAGExecutor.validate()` must call the same validator for every registered node after stripping execution-policy parameters. Keep errors in its existing string-list API so `/api/workflows/{workflow_id}/run` rejects before creating a `WorkflowRun`.

- [x] **Step 4: Mark only parameters needed for normal execution**

Mark direct runtime requirements explicitly: CSV source-dependent file/URL/artifact ID, Join key pairs, aggregation, pivot, generated-column, sort, condition, merge join key, data source paths/URLs, explicit column/filter expressions, executable script, and chart axes/columns that do not have a usable default. Leave intentional optional fields unmarked, including export file names and optional display/color columns.

- [x] **Step 5: Expose metadata through API schemas**

```python
class ParamSpecSchema(BaseModel):
    required: bool = False
    required_when: dict[str, object] | None = None
```

Populate `required`, `required_when`, `range_min`, and `range_max` in `list_operators()`.

- [x] **Step 6: Run contract, DAG, and API tests**

Run: `python -m unittest tests.test_operator_contract tests.test_dag tests.test_api_runs -v`

Expected: PASS, including a request that returns `WORKFLOW_INVALID` without enqueuing a run for missing required fields.

### Task 2: Make Join Key Pairs Persistent And Reject Blank Pairs

**Files:**
- Modify: `ml-platform/frontend/src/components/workspace/NodeConfigPanel.tsx`
- Modify: `ml-platform/frontend/src/stores/workflowStore.ts`
- Modify: `ml-platform/backend/app/operators/blending.py`
- Create: `ml-platform/backend/tests/test_workflow_operator_regressions.py`
- Test: `ml-platform/frontend/src/components/workspace/NodeConfigPanel.join.test.tsx`

- [x] **Step 1: Write failing Join interaction and direct-execution tests**

```tsx
await user.click(screen.getByRole("button", { name: "添加键对" }));
expect(screen.getAllByText("左侧键列")).toHaveLength(2);
expect(useWorkflowStore.getState().nodes[0].data.params).toMatchObject({
  left_keys: "plant,", right_keys: "site,",
});
```

```python
with self.assertRaisesRegex(ValueError, "Join key pairs are required"):
    execute_operator(op, {"left": [{"id": 1}], "right": [{"id": 1}]}, {})
```

- [x] **Step 2: Run failing focused tests**

Run: `npm test -- --run src/components/workspace/NodeConfigPanel.join.test.tsx`

Expected: FAIL because `parseJoinKeyPairs()` removes the trailing empty slot.

Run: `python -m unittest tests.test_workflow_operator_regressions.TestJoinRequirements -v`

Expected: FAIL because blank keys use auto-detection.

- [x] **Step 3: Preserve empty structured slots and selection state**

Count raw comma-separated slots, not only nonempty values, so an added blank pair survives re-render. Update `updateNodeParams()` to update the selected-node snapshot when it is the edited node. Keep serialized `left_keys`/`right_keys` compatibility.

- [x] **Step 4: Remove blank-key fallback in Join**

Reject either missing side before empty-input shortcuts or `pandas.merge`. Preserve unequal-count and missing-column errors.

- [x] **Step 5: Run focused Join tests**

Run: `npm test -- --run src/components/workspace/NodeConfigPanel.join.test.tsx`

Run: `python -m unittest tests.test_workflow_operator_regressions.TestJoinRequirements -v`

Expected: PASS.

### Task 3: Clarify Excel Import And Add Safe Export Configuration

**Files:**
- Modify: `ml-platform/backend/app/operators/io_operators.py`
- Modify: `ml-platform/backend/app/operators/utility_operators.py`
- Create: `ml-platform/backend/app/engine/export_paths.py`
- Modify: `ml-platform/frontend/src/components/workspace/NodeConfigPanel.tsx`
- Create: `ml-platform/frontend/src/components/workspace/workflowExport.ts`
- Test: `ml-platform/backend/tests/test_workflow_operator_regressions.py`
- Test: `ml-platform/frontend/src/components/workspace/NodeConfigPanel.test.tsx`
- Test: `ml-platform/frontend/src/components/workspace/workflowExport.test.ts`

- [x] **Step 1: Write failing Excel and export tests**

```python
result = execute_operator(read_excel, {}, {
    "file_path": workbook, "sheet_name": "Data", "header_row": 0,
    "skiprows": 1, "usecols": "A:C", "nrows": 5,
})
self.assertEqual(result["data"], expected)

path = resolve_export_path(context, "csv_export", "", "csv")
self.assertTrue(path.is_relative_to(context.workspace_dir / "exports"))
```

```tsx
expect(buildExportBlob([{ id: 1 }], { format: "csv" }).type).toContain("text/csv");
expect(buildExportFilename("csv_export", "node-1", { file_name: "" })).toBe("csv_export_node-1.csv");
```

- [x] **Step 2: Run failing focused tests**

Run: `python -m unittest tests.test_workflow_operator_regressions -v`

Run: `npm test -- --run src/components/workspace/NodeConfigPanel.test.tsx src/components/workspace/workflowExport.test.ts`

Expected: FAIL because Read Excel lacks its spreadsheet options and exports silently skip empty paths.

- [x] **Step 3: Retain and expand `read_excel`**

Keep `read_excel` because it is spreadsheet-specific while `csv_import` supports CSV/Excel source transport. Add local file upload type, `skiprows`, `usecols`, and `nrows`; preserve sheet and header options; reject missing/unreadable files with a clear error.

- [x] **Step 4: Use an isolated default export path**

Add a shared resolver that puts unnamed server-side exports under `<workflow workspace>/exports`. Add optional `file_name`; force `.csv` for CSV-only operators and retain the editable format selector only for `write_as_text` formats. Continue honoring an existing `file_path` only as a backward-compatible legacy value.

- [x] **Step 5: Add client folder selection and writing**

Use `window.showDirectoryPicker({ mode: "readwrite" })` behind a user-clicked control. Store the nonserializable directory handle in Zustand by node ID, not in persisted workflow params. On an export-node completion, serialize its data using its selected format and write the file through `getFileHandle(...).createWritable()`. For browsers without File System Access API, trigger a normal download and report that browser-managed save location is used.

- [x] **Step 6: Render file and export controls**

Give every `file` parameter the existing upload flow. For export operators, render the directory picker and filename field. Display a disabled fixed-format field for single-format operators; retain a `Select` only when multiple output formats are supported.

- [x] **Step 7: Run focused Excel/export tests**

Run: `python -m unittest tests.test_workflow_operator_regressions -v`

Run: `npm test -- --run src/components/workspace/NodeConfigPanel.test.tsx src/components/workspace/workflowExport.test.ts`

Expected: PASS.

### Task 4: Label Every ReactFlow Port Without Changing Its Contract

**Files:**
- Modify: `ml-platform/frontend/src/components/workspace/CustomNode.tsx`
- Modify: `ml-platform/frontend/src/styles/global.css`
- Test: `ml-platform/frontend/src/components/workspace/CustomNode.test.tsx`

- [x] **Step 1: Write failing port-label test**

```tsx
expect(screen.getByTestId("port-label-in-left")).toHaveTextContent("LEF");
expect(screen.getByTestId("port-label-out-predictions")).toHaveTextContent("PRE");
expect(screen.getByTestId("port-in-left")).toHaveAttribute("id", "left");
```

- [x] **Step 2: Run focused port test**

Run: `npm test -- --run src/components/workspace/CustomNode.test.tsx`

Expected: FAIL because nodes display only aggregate `IN`/`OUT` counts.

- [x] **Step 3: Render concise labels adjacent to handles**

Add an exported deterministic abbreviation helper using uppercase first three logical characters. Render a semantic label per input/output handle, retain handle IDs/type/position/style and tooltips, and style labels to fit within existing node dimensions.

- [x] **Step 4: Run focused port test**

Run: `npm test -- --run src/components/workspace/CustomNode.test.tsx`

Expected: PASS.

### Task 5: Isolate Workflow Execution Workspaces

**Files:**
- Modify: `ml-platform/backend/app/engine/data_bus.py`
- Modify: `ml-platform/backend/app/engine/operator_contract.py`
- Modify: `ml-platform/backend/app/engine/dag_executor.py`
- Modify: `ml-platform/backend/app/services/workflow_execution.py`
- Modify: `ml-platform/backend/app/operators/io_operators.py`
- Test: `ml-platform/backend/tests/test_dag.py`
- Test: `ml-platform/backend/tests/test_workflow_execution_service.py`

- [x] **Step 1: Write failing workspace-isolation tests**

```python
left = DataBus.save_data("same-run", "node", "data", {"side": "left"}, workflow_id="workflow-a")
right = DataBus.save_data("same-run", "node", "data", {"side": "right"}, workflow_id="workflow-b")
self.assertNotEqual(left, right)
self.assertEqual(DataBus.load_data(left), {"side": "left"})
self.assertEqual(DataBus.load_data(right), {"side": "right"})
```

- [x] **Step 2: Run failing isolation tests**

Run: `python -m unittest tests.test_dag tests.test_workflow_execution_service -v`

Expected: FAIL because DataBus derives its path from `run_id` only and the execution service does not pass workflow identity.

- [x] **Step 3: Add safe workflow/run workspace paths**

Create a sanitized `<base>/workflows/<workflow>/runs/<run>` directory API. Thread `workflow_id` through `DAGExecutor`, `DataBus.save_data`, loop persistence, cleanup, and `OperatorContext.workspace_dir`. Do not change data loading APIs for existing saved absolute paths.

- [x] **Step 4: Bind temporary downloads and default exports to workspace**

Make URL downloads use `<workspace>/downloads`, then delete them in `finally`. Use the workspace resolver for new exports. Explicit browser-selected output remains a client-side operation and never exposes server filesystem paths.

- [x] **Step 5: Pass persisted workflow identity from service**

Instantiate `DAGExecutor(..., workflow_id=str(workflow.id))` in `_execute_loaded_workflow`.

- [x] **Step 6: Run focused isolation tests**

Run: `python -m unittest tests.test_dag tests.test_workflow_execution_service -v`

Expected: PASS.

### Task 6: Integration, Documentation, And Evidence

**Files:**
- Modify: `ml-platform/backend/tests/week_manifest.py`
- Modify: `ml-platform/frontend/src/weekAcceptance.test.ts`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [x] **Step 1: Register new tests without removing user entries**

Add only the new backend/frontend test files to their unique week manifest entries. Keep all unrelated current changes intact.

- [x] **Step 2: Run focused and full checks**

Run: `python -m unittest tests.test_operator_contract tests.test_dag tests.test_workflow_operator_regressions tests.test_workflow_execution_service tests.test_api_runs -v`

Run: `python -m compileall -q app`

Run: `npm test -- --run`

Run: `npm run build`

Run: `git diff --check`

- [x] **Step 3: Inspect final status and append records**

Append verified observed behavior, root cause, solution, test evidence, prevention, and remaining browser-security limitations to `DEVELOPMENT_PLAN.md` and the project category in `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`. Never overwrite historical entries.

- [ ] **Step 4: Commit only this scope after verification**

Run: `git add` only the files changed for this plan, then create a focused commit after all tests and documentation checks pass.

### Task 7: Close Remaining Workflow And AgentTask Regressions

**Files:**
- Modify: `ml-platform/frontend/src/pages/WorkspacePage.tsx`
- Test: `ml-platform/frontend/src/pages/WorkspacePage.test.ts`
- Modify: `ml-platform/backend/app/api/orchestration.py`
- Test: `ml-platform/backend/tests/test_agents.py`
- Modify: `docs/未解决bug清单.md`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [x] **Step 1: Write and run failing legacy Handle hydration regression**

```tsx
const nodes = [
  { id: "source", data: { outputs: [{ name: "data" }] } },
  { id: "target", data: { inputs: [{ name: "input" }] } },
];
const hydrate = hydrateWorkflowEdges as (edges: any[], nodes: any[]) => any[];
expect(hydrate([
  { id: "legacy", source: "source", target: "target", source_port: "out-0", target_port: "in-0" },
  { id: "replacement", source: "source", target: "target", source_port: "data", target_port: "input" },
], nodes)).toEqual([expect.objectContaining({ id: "replacement", sourceHandle: "data", targetHandle: "input" })]);
```

Run: `npm test -- --run src/pages/WorkspacePage.test.ts`

Expected: FAIL because `hydrateWorkflowEdges()` retains `out-0`/`in-0` instead of mapping them by node port metadata before deduplication.

- [x] **Step 2: Map historical indexed handles before hydration deduplication**

Add an optional node list to `hydrateWorkflowEdges()`. Build an ID-to-node lookup, resolve each source Handle against `node.data.outputs` and each target Handle against `node.data.inputs` with the existing `resolvePort()` helper, then use the resolved values in the existing survivor filter. Pass the parsed workflow nodes at the production call site. Unknown or out-of-range indexed Handles must remain unchanged.

- [x] **Step 3: Run legacy Handle regression green**

Run: `npm test -- --run src/pages/WorkspacePage.test.ts`

Expected: PASS; legacy and current edges for one logical endpoint collapse to the latest edge.

- [x] **Step 4: Write and run failing invalid AgentTask UUID API regression**

```python
def test_invalid_task_id_returns_not_found(self):
    response = client.get(
        "/api/orchestration/tasks/not-a-uuid/messages",
        headers=login_headers(),
    )
    self.assertEqual(response.status_code, 404)
```

Run: `python -m unittest tests.test_agents.TestAgentAPI.test_invalid_task_id_returns_not_found -v`

Expected: FAIL with HTTP 500 because `_task_for_user()` calls `uuid.UUID()` without handling malformed input.

- [x] **Step 5: Guard AgentTask UUID parsing at the resource boundary**

```python
def _task_for_user(db, task_id, user):
    try:
        identifier = uuid.UUID(str(task_id))
    except (TypeError, ValueError, AttributeError):
        return None
    task = db.query(AgentTask).filter(AgentTask.id == identifier).first()
```

Keep the existing access-hiding behavior: malformed, absent, and unauthorized tasks all cause routes to return their existing `404` response.

- [x] **Step 6: Run invalid UUID regression green**

Run: `python -m unittest tests.test_agents.TestAgentAPI.test_invalid_task_id_returns_not_found -v`

Expected: PASS with HTTP 404 and no server exception.

- [x] **Step 7: Run focused, full, and documentation checks serially**

Run: `npm test -- --run src/pages/WorkspacePage.test.ts`

Run: `python -m unittest tests.test_agents -v`

Run: `python run_suite.py`

Run: `npm test -- --run`

Run: `npm run build`

Run: `git diff --check`

Run backend and frontend full suites one at a time. Update the bug list, development plan, and reusable experience only with observed results. Do not stage, commit, or modify unrelated user changes.

Observed 2026-07-25: `WorkspacePage.test.ts` 11/11, `tests.test_agents` 9/9, backend `run_suite.py` 84/84 modules, frontend Vitest 31 files/109 tests, backend `compileall`, and frontend production build all passed. Vite reported only its chunk-size warning. `git diff --check` is completed after the documentation updates.
