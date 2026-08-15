# Workflow Port And Results Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `docs/bug列表.txt` 中六项工作流缺陷，使端口连接、原始数据、预览、错误详情、评估算子和可视化结果均可稳定工作。

**Architecture:** ReactFlow 端口只使用算子元数据声明的稳定逻辑端口名，Zustand 在连接时按源端口和目标端口分别淘汰冲突边；历史 `__slot_N` 仅在载入和保存边界归一化。后端在注册表包装处理/融合算子的声明与结果，统一补充原始输出并继续经过 `OperatorResult` 校验。运行状态将节点错误、结果、指标和日志写入同一前端 store，CustomNode 负责轻量交互，NodeConfigPanel 负责详细结果面板。

**Tech Stack:** React 18, TypeScript, ReactFlow, Zustand, Ant Design, Vitest, FastAPI, Python, pandas, scikit-learn, unittest/pytest.

---

### Task 1: Stabilize workflow port contract and edge replacement

**Files:**
- Modify: `ml-platform/frontend/src/stores/workflowStore.ts`
- Modify: `ml-platform/frontend/src/pages/WorkspacePage.tsx`
- Modify: `ml-platform/frontend/src/components/workspace/CustomNode.tsx`
- Modify: `ml-platform/frontend/src/components/workspace/WorkflowCanvas.tsx`
- Test: `ml-platform/frontend/src/stores/workflowStore.test.ts`
- Test: `ml-platform/frontend/src/pages/WorkspacePage.test.ts`
- Test: `ml-platform/frontend/src/components/workspace/CustomNode.test.tsx`

- [ ] **Step 1: Write failing port-contract tests.** Replace dynamic-slot expectations with stable IDs and assert that a new connection removes every edge using the same logical source or target port while preserving unrelated edges:

```ts
it("replaces an existing edge for either logical endpoint", () => {
  const store = useWorkflowStore.getState();
  store.onConnect({ source: "a", sourceHandle: "data", target: "join", targetHandle: "left" });
  store.onConnect({ source: "b", sourceHandle: "data", target: "join", targetHandle: "left" });
  store.onConnect({ source: "b", sourceHandle: "other", target: "join", targetHandle: "right" });
  expect(useWorkflowStore.getState().edges.map((edge) => edge.id)).toHaveLength(2);
  expect(useWorkflowStore.getState().edges).toEqual(expect.arrayContaining([
    expect.objectContaining({ source: "b", sourceHandle: "data", target: "join", targetHandle: "left" }),
    expect.objectContaining({ source: "b", sourceHandle: "other", targetHandle: "right" }),
  ]));
});
```

```ts
it("normalizes legacy slot handles on hydration and save", () => {
  expect(hydrateWorkflowEdges([{ id: "e", source: "a", target: "b", source_port: "data__slot_3", target_port: "in__slot_2" }])[0])
    .toMatchObject({ sourceHandle: "data", targetHandle: "in" });
  expect(resolvePort("data__slot_3", [{ name: "data" }])).toBe("data");
});
```

- [ ] **Step 2: Run focused tests and confirm the old dynamic implementation fails.**

Run: `npm test -- --run src/stores/workflowStore.test.ts src/components/workspace/CustomNode.test.tsx src/pages/WorkspacePage.test.ts`

Expected: FAIL because `onConnect` retains two `left` edges and `CustomNode` renders `__slot_N` handles.

- [ ] **Step 3: Implement stable handles and replacement.** Add one local logical-handle normalizer, filter `state.edges` by normalized `(source, sourceHandle)` or `(target, targetHandle)`, then append the new custom edge. Render exactly one `Handle` per declared input/output with `id={port.name}`. Remove connection-count calculations and make hydration strip legacy suffixes without generating slots; keep `resolvePort` able to translate `in-N`/`out-N` legacy indices.

```ts
function logicalHandle(handle: string | null | undefined): string {
  return String(handle || "").replace(/__slot_\d+$/, "");
}

onConnect: (connection) => set((state) => {
  const next = { ...connection, sourceHandle: logicalHandle(connection.sourceHandle), targetHandle: logicalHandle(connection.targetHandle), type: "custom" };
  const edges = state.edges.filter((edge) =>
    !(edge.source === next.source && logicalHandle(edge.sourceHandle) === next.sourceHandle) &&
    !(edge.target === next.target && logicalHandle(edge.targetHandle) === next.targetHandle),
  );
  return { edges: addEdge(next, edges) };
}),
```

- [ ] **Step 4: Run focused tests and TypeScript compile.**

Run: `npm test -- --run src/stores/workflowStore.test.ts src/components/workspace/CustomNode.test.tsx src/pages/WorkspacePage.test.ts` and `npm run build`.

Expected: focused tests and build pass; no `__slot_N` handles are rendered for newly created nodes.

- [ ] **Step 5: Commit the task.**

```bash
git add ml-platform/frontend/src/stores/workflowStore.ts ml-platform/frontend/src/pages/WorkspacePage.tsx ml-platform/frontend/src/components/workspace/CustomNode.tsx ml-platform/frontend/src/components/workspace/WorkflowCanvas.tsx ml-platform/frontend/src/stores/workflowStore.test.ts ml-platform/frontend/src/pages/WorkspacePage.test.ts ml-platform/frontend/src/components/workspace/CustomNode.test.tsx
git commit -m "fix: enforce single workflow port connections"
```

### Task 2: Add raw outputs for processing and blending operators

**Files:**
- Modify: `ml-platform/backend/app/engine/registry.py`
- Modify: `ml-platform/backend/app/engine/base_operator.py`
- Modify: `ml-platform/backend/app/engine/dag_executor.py` only if the wrapper must be applied at execution boundary
- Test: `ml-platform/backend/tests/test_operator_raw_outputs.py`

- [ ] **Step 1: Write failing registry/execute tests.** Assert every `processing` operator has `raw_data` output, every `blending` input has `raw_<input>` output, and an execution result contains untouched copies as well as declared processed outputs:

```python
def test_processing_and_blending_metadata_exposes_raw_ports():
    processing = OperatorRegistry.get("missing_value_handler")
    join = OperatorRegistry.get("join")
    assert "raw_data" in {port.name for port in processing.outputs}
    assert {"raw_left", "raw_right"}.issubset({port.name for port in join.outputs})

def test_processing_result_preserves_input_before_transform():
    result = execute_operator(OperatorRegistry.get("missing_value_handler"), {"data": [{"x": None}]}, {"strategy": "drop"})
    assert result["raw_data"] == [{"x": None}]
    assert result["data"] == []
```

- [ ] **Step 2: Run the new tests to verify failure.**

Run: `python -m pytest backend/tests/test_operator_raw_outputs.py -q` from `ml-platform`.

Expected: FAIL because metadata only declares `data` and the executor returns no raw ports.

- [ ] **Step 3: Implement a registry wrapper with deep-copy semantics.** At registration, clone each operator's port list, append `raw_data` for `processing`, append one `raw_<input.name>` port per input for `blending`, and wrap `execute` so it snapshots input values before invocation and merges raw values into the returned `OperatorResult`. Do not mutate caller inputs; preserve artifacts, metrics, logs, and reject duplicate names.

```python
def _with_raw_outputs(op: BaseOperator) -> BaseOperator:
    if op.category not in {"processing", "blending"}:
        return op
    original_execute = op.execute
    op.inputs = list(op.inputs)
    op.outputs = list(op.outputs)
    raw_names = (["raw_data"] if op.category == "processing" else [f"raw_{port.name}" for port in op.inputs])
    op.outputs.extend(PortSpec(name, "DataTable", "Raw input") for name in raw_names if name not in {p.name for p in op.outputs})
    def execute(context, inputs, params):
        snapshot = copy.deepcopy(inputs)
        result = original_execute(context, inputs, params)
        raw = {"raw_data": snapshot.get("data", [])} if op.category == "processing" else {f"raw_{name}": snapshot.get(name, []) for name in (p.name for p in op.inputs)}
        return OperatorResult(outputs={**result.outputs, **raw}, metrics=result.metrics, artifacts=result.artifacts, logs=result.logs)
    op.execute = execute
    return op
```

- [ ] **Step 4: Run raw-output tests and operator contract tests.**

Run: `python -m pytest backend/tests/test_operator_raw_outputs.py backend/tests/test_operator_contract.py -q`.

Expected: PASS and `validate_operator_result` accepts all declared raw ports.

- [ ] **Step 5: Commit the task.**

```bash
git add ml-platform/backend/app/engine/registry.py ml-platform/backend/app/engine/base_operator.py ml-platform/backend/tests/test_operator_raw_outputs.py
git commit -m "feat: expose raw processing outputs"
```

### Task 3: Make every evaluation operator executable under its declared task

**Files:**
- Modify: `ml-platform/backend/app/operators/evaluation.py`
- Test: `ml-platform/backend/tests/test_evaluation_operator_execution.py`
- Modify: `ml-platform/backend/tests/week_manifest.py` if the repository manifest requires test registration

- [ ] **Step 1: Write a parameterized minimal execution regression.** Enumerate all operators in category `evaluation`, build valid small classification and regression fixtures, invoke `execute_operator`, and assert every declared output exists. Include `cross_validation` for `decision_tree` and `logistic_regression` with `task="regression"`.

```python
@pytest.mark.parametrize("model_type", ["random_forest", "decision_tree", "logistic_regression", "svm"])
def test_cross_validation_regression_uses_regressor(model_type):
    result = execute_operator(OperatorRegistry.get("cross_validation"), {"data": regression_records()}, {
        "target_column": "target", "task": "regression", "model_type": model_type, "n_folds": 3,
    })
    assert len(result["fold_metrics"]) == 3
    assert "rmse" in result["avg_metrics"]
```

- [ ] **Step 2: Run the focused evaluation suite and capture the current failure.**

Run: `python -m pytest backend/tests/test_evaluation_operator_execution.py -q`.

Expected: FAIL for regression `decision_tree`/`logistic_regression` with `Unknown label type: continuous` or missing regressor.

- [ ] **Step 3: Fix model mapping and contract edge cases.** Supply `DecisionTreeRegressor` and `LinearRegression` regression variants for the selectable tree and logistic model types, clone a fresh model per fold, and keep classification metrics separate from regression metrics. For each registered evaluation operator, compare `inputs` and `outputs` with its `execute` method and add explicit empty/error output values so `validate_operator_result` receives every declared port on every supported fixture.

- [ ] **Step 4: Run all evaluation and operator tests.**

Run: `python -m pytest backend/tests/test_evaluation_operator_execution.py backend/tests/test_operators_extended.py backend/tests/test_operators_visualization_execution.py -q`.

Expected: PASS; all evaluation operators register and execute at least once.

- [ ] **Step 5: Commit the task.**

```bash
git add ml-platform/backend/app/operators/evaluation.py ml-platform/backend/tests/test_evaluation_operator_execution.py ml-platform/backend/tests/week_manifest.py
git commit -m "fix: execute all evaluation operators"
```

### Task 4: Add endpoint preview and clickable node error details

**Files:**
- Modify: `ml-platform/frontend/src/stores/workflowStore.ts`
- Modify: `ml-platform/frontend/src/components/workspace/CustomNode.tsx`
- Modify: `ml-platform/frontend/src/pages/WorkspacePage.tsx`
- Modify: `ml-platform/frontend/src/styles/global.css`
- Test: `ml-platform/frontend/src/components/workspace/CustomNode.test.tsx`
- Test: `ml-platform/frontend/src/stores/workflowStore.test.ts`

- [ ] **Step 1: Write failing interaction tests.** Assert hovering a handle exposes port type/format/preview, clicking the same handle hides it, and clicking a failed status/error label opens an Ant Design error modal containing code, message, node ID, and attempt.

```tsx
it("toggles port preview on click", async () => {
  const user = userEvent.setup();
  render(<ReactFlowProvider><CustomNode id="n" type="custom" selected={false} dragging={false} zIndex={0} isConnectable xPos={0} yPos={0} data={{ nodeId: "n", inputs: [{ name: "data", type: "DataTable", label: "Data" }], outputs: [] }} /></ReactFlowProvider>);
  await user.hover(screen.getByTestId("port-in-data"));
  expect(await screen.findByText(/DataTable/)).toBeInTheDocument();
  await user.click(screen.getByTestId("port-in-data"));
  expect(screen.queryByText(/DataTable/)).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run focused tests to verify failure.**

Run: `npm test -- --run src/components/workspace/CustomNode.test.tsx src/stores/workflowStore.test.ts`.

Expected: FAIL because Ant Design `Tooltip` is hover-only and node errors are plain non-clickable text.

- [ ] **Step 3: Implement preview/error state.** Add `nodeErrors` and `setNodeError` to the store; hydrate/reconcile/WebSocket node status messages into that map. In `CustomNode`, keep one `activePreview` state, render a clickable handle wrapper that opens the tooltip on hover and clears it on click, and render a button-like failed label with `onClick` opening `Modal.error` or a callback passed through node data. Include error code/message/node ID/attempt in the details text.

- [ ] **Step 4: Run focused tests, build, and verify the existing run status path.**

Run: `npm test -- --run src/components/workspace/CustomNode.test.tsx src/stores/workflowStore.test.ts src/pages/WorkspacePage.test.ts` and `npm run build`.

Expected: PASS; run reconciliation and WebSocket events preserve node results and errors.

- [ ] **Step 5: Commit the task.**

```bash
git add ml-platform/frontend/src/stores/workflowStore.ts ml-platform/frontend/src/components/workspace/CustomNode.tsx ml-platform/frontend/src/pages/WorkspacePage.tsx ml-platform/frontend/src/styles/global.css ml-platform/frontend/src/components/workspace/CustomNode.test.tsx ml-platform/frontend/src/stores/workflowStore.test.ts
git commit -m "feat: show workflow port previews and errors"
```

### Task 5: Show independent visualization result panel

**Files:**
- Modify: `ml-platform/frontend/src/stores/workflowStore.ts`
- Modify: `ml-platform/frontend/src/components/workspace/CustomNode.tsx`
- Modify: `ml-platform/frontend/src/components/workspace/NodeConfigPanel.tsx`
- Modify: `ml-platform/frontend/src/pages/WorkspacePage.tsx`
- Modify: `ml-platform/frontend/src/styles/global.css`
- Test: `ml-platform/frontend/src/components/workspace/NodeConfigPanel.test.tsx`
- Test: `ml-platform/frontend/src/components/workspace/CustomNode.test.tsx`

- [ ] **Step 1: Write failing visualization result tests.** Put a completed visualization node result containing `chart`, `metrics`, `logs`, and a JSON/table output into the store; click the node and assert a visible panel renders those sections and chart/table/JSON fallbacks.

```tsx
it("opens visualization result panel after completed node click", async () => {
  const user = userEvent.setup();
  useWorkflowStore.setState({ nodeStatuses: { "viz-1": "completed" }, nodeResults: { "viz-1": { chart: "iVBORw0KGgo=", metrics: { r2: 0.9 }, logs: [{ message: "ok" }], rows: [{ x: 1 }] } } });
  render(<NodeConfigPanel />);
  await user.click(screen.getByRole("button", { name: /open result/i }));
  expect(screen.getByText(/r2/)).toBeInTheDocument();
  expect(screen.getByText(/ok/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test and confirm the missing panel failure.**

Run: `npm test -- --run src/components/workspace/NodeConfigPanel.test.tsx src/components/workspace/CustomNode.test.tsx`.

Expected: FAIL because completed visualization nodes currently expose no result action or panel.

- [ ] **Step 3: Implement a dedicated result panel.** Add selected-result state to the store, expose `openNodeResult`/`closeNodeResult`, make only completed `visualization` nodes clickable, and render an Ant Design `Drawer`/`Modal` independent of the configuration form. Decode chart base64 as an image, render arrays as a compact table, and render remaining values as bounded JSON with metrics and logs sections.

- [ ] **Step 4: Run focused tests and production build.**

Run: `npm test -- --run src/components/workspace/NodeConfigPanel.test.tsx src/components/workspace/CustomNode.test.tsx src/pages/WorkspacePage.test.ts` and `npm run build`.

Expected: PASS; non-visualization and incomplete nodes do not show the result action.

- [ ] **Step 5: Commit the task.**

```bash
git add ml-platform/frontend/src/stores/workflowStore.ts ml-platform/frontend/src/components/workspace/CustomNode.tsx ml-platform/frontend/src/components/workspace/NodeConfigPanel.tsx ml-platform/frontend/src/pages/WorkspacePage.tsx ml-platform/frontend/src/styles/global.css ml-platform/frontend/src/components/workspace/NodeConfigPanel.test.tsx ml-platform/frontend/src/components/workspace/CustomNode.test.tsx
git commit -m "feat: open visualization node results"
```

### Task 6: Full verification, browser acceptance, and development records

**Files:**
- Modify: `DEVELOPMENT_PLAN.md` (append status, problems, verification, unfinished work)
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md` (append reusable project experience)
- Preserve: `docs/bug列表.txt` (do not edit or revert)

- [ ] **Step 1: Run backend focused and full suites.**

Run from `ml-platform`: `python -m pytest backend/tests/test_operator_raw_outputs.py backend/tests/test_evaluation_operator_execution.py backend/tests/test_operators_extended.py backend/tests/test_operators_visualization_execution.py -q`; then `python backend/run_suite.py` if the project baseline requires it.

- [ ] **Step 2: Run frontend focused and full suites.**

Run from `ml-platform/frontend`: `npm test -- --run src/stores/workflowStore.test.ts src/components/workspace/CustomNode.test.tsx src/components/workspace/NodeConfigPanel.test.tsx src/pages/WorkspacePage.test.ts`; then `npm test -- --run` and `npm run build`.

- [ ] **Step 3: Run static checks.**

Run: `python -m compileall backend/app backend/tests` and `git diff --check`.

- [ ] **Step 4: Perform browser acceptance with live frontend/backend.** Verify one-port replacement, handle hover/click dismissal, failed-node details, and visualization result panel at desktop and narrow viewport. Capture any service startup or proxy failure separately from application failures.

- [ ] **Step 5: Append records.** Record observed behavior, verified root cause, solution, verification, prevention, and any remaining evaluation/data-format limitations in both development documents. Do not mark the plan complete until code, tests, docs, build, and browser checks pass.
