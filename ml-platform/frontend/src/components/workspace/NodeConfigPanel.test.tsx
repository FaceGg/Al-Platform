import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NodeConfigPanel, { getParamLabel, getPortLabel, NodeResultPanel } from "./NodeConfigPanel";
import { useWorkflowStore } from "../../stores/workflowStore";

const datasetsApi = vi.hoisted(() => ({
  listDatasets: vi.fn(),
  listModelArtifacts: vi.fn(),
  listInferenceDeployments: vi.fn(),
  downloadDatasetArtifact: vi.fn(),
}));

vi.mock("../../api/datasets", () => datasetsApi);
vi.mock("../../api/client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock("./CustomNode", () => ({
  extractColumnsFromResult: vi.fn(() => []),
  isColumnParam: vi.fn(() => false),
}));
vi.mock("./workflowExport", () => ({ isWorkflowExportOperator: vi.fn(() => false) }));
vi.mock("../../i18n", () => ({
  useI18n: () => ({ t: { workspace: {} }, lang: "zh" }),
}));

const visualizationNode = {
  id: "viz-1",
  type: "custom",
  position: { x: 0, y: 0 },
  data: { operatorId: "line_chart", label: "Line chart", category: "visualization" },
};

beforeEach(() => {
  vi.clearAllMocks();
  useWorkflowStore.getState().reset();
  datasetsApi.listDatasets.mockResolvedValue([]);
  datasetsApi.listModelArtifacts.mockResolvedValue([]);
  datasetsApi.listInferenceDeployments.mockResolvedValue([]);
});

describe("operator parameter labels", () => {
  it("localizes join key labels for both supported languages", () => {
    expect(getPortLabel("join", "left_keys", "zh")).toBe("左侧键列（逗号分隔）");
    expect(getPortLabel("join", "right_keys", "en")).toBe("Right Key Columns (comma-separated)");
  });

  it("returns an empty label when a parameter has no special mapping", () => {
    expect(getPortLabel("join", "unknown", "zh")).toBeNull();
  });

  it("localizes closed-loop operator param labels via global and operator maps", () => {
    // 全局参数名映射（闭环算子不再显示英文 ID 标签）
    expect(getParamLabel("retrain_threshold", "retrain_dataset_artifact_id", "zh")).toBe("重训数据集");
    expect(getParamLabel("retrain_threshold", "swap_deployment_id", "zh")).toBe("换模部署");
    expect(getParamLabel("load_model_artifact", "model_artifact_id", "zh")).toBe("模型制品");
    // 算子级映射优先：condition 的 column/value/operator
    expect(getParamLabel("condition", "column", "zh")).toBe("判断列");
    expect(getParamLabel("condition", "operator", "zh")).toBe("比较运算符");
    expect(getParamLabel("notify_admins", "severity", "zh")).toBe("告警级别");
    // 英文回退与未命中
    expect(getParamLabel("retrain_threshold", "threshold_rows", "en")).toBe("Threshold Rows");
    expect(getParamLabel("whatever", "totally_unknown", "zh")).toBeNull();
  });
});

describe("closed-loop operator id params render pickers", () => {
  const operators = [
    {
      id: "retrain_threshold",
      name: "Retrain Threshold",
      category: "control",
      parameters: [
        { name: "dataset_artifact_id", type: "str", label: "Dataset" },
        { name: "retrain_dataset_artifact_id", type: "str", label: "Retrain DS" },
        { name: "retrain_target_column", type: "str", label: "Target" },
        { name: "threshold_rows", type: "int", label: "Threshold", default: 3 },
        { name: "swap_deployment_id", type: "str", label: "Deployment" },
      ],
      inputs: [],
      outputs: [],
    },
    {
      id: "load_model_artifact",
      name: "Load Model Artifact",
      category: "ml",
      parameters: [{ name: "model_artifact_id", type: "str", label: "Model" }],
      inputs: [],
      outputs: [],
    },
  ];

  function selectOperator(operatorId: string) {
    const node = {
      id: "n-1", type: "custom", position: { x: 0, y: 0 },
      data: { operatorId, label: operatorId, params: {} },
    };
    useWorkflowStore.setState({
      operators: operators as any,
      nodes: [node as any],
      selectedNode: node as any,
    });
  }

  it("retrain_threshold renders dataset/deployment pickers instead of raw id inputs", async () => {
    datasetsApi.listDatasets.mockResolvedValue([
      { artifact_id: "ds-1", name: "labeled_fea.csv", format: "csv", row_count: 46 },
      { artifact_id: "ds-2", name: "photo.png", format: "png" },
    ]);
    datasetsApi.listInferenceDeployments.mockResolvedValue([
      { id: "dep-1", name: "自动化测试", observed_state: "running" },
    ]);
    selectOperator("retrain_threshold");
    render(<NodeConfigPanel projectId="p1" />);

    await waitFor(() => expect(datasetsApi.listDatasets).toHaveBeenCalledWith("p1"));
    await waitFor(() => expect(datasetsApi.listInferenceDeployments).toHaveBeenCalledWith("p1"));

    const combos = screen.getAllByRole("combobox");
    expect(combos.length).toBeGreaterThanOrEqual(3);
    combos[0].dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    await waitFor(() => {
      const opts = Array.from(document.querySelectorAll(".ant-select-item-option")).map(o => o.textContent);
      expect(opts.some(t => t.includes("labeled_fea.csv"))).toBe(true);
      expect(opts.some(t => t.includes("photo.png"))).toBe(false);
    });
  });

  it("load_model_artifact renders a model artifact picker", async () => {
    datasetsApi.listModelArtifacts.mockResolvedValue([
      { id: "ma-1", name: "自动模型.joblib", format: "joblib" },
    ]);
    selectOperator("load_model_artifact");
    render(<NodeConfigPanel projectId="p1" />);

    await waitFor(() => expect(datasetsApi.listModelArtifacts).toHaveBeenCalledWith("p1"));
    const combo = screen.getByRole("combobox");
    combo.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    await waitFor(() => {
      const opts = Array.from(document.querySelectorAll(".ant-select-item-option")).map(o => o.textContent);
      expect(opts.some(t => t.includes("自动模型.joblib"))).toBe(true);
    });
  });
});

describe("visualization result panel", () => {
  it("opens for a completed visualization node and renders chart, table, JSON, metrics, and logs", () => {
    useWorkflowStore.setState({
      nodes: [visualizationNode as any],
      nodeStatuses: { "viz-1": "completed" },
      nodeResults: {
        "viz-1": {
          chart: "iVBORw0KGgo=",
          rows: [{ x: 1, label: "ok" }],
          notes: { source: "test", veryLong: "x".repeat(6000) },
          metrics: { r2: 0.9 },
          logs: [{ level: "info", message: "ok" }],
        },
      },
    });

    useWorkflowStore.getState().openNodeResult("viz-1");
    render(<NodeResultPanel />);

    expect(screen.getByTestId("node-result-panel")).toBeInTheDocument();
    expect(screen.getByTestId("node-result-chart")).toHaveAttribute(
      "src",
      "data:image/png;base64,iVBORw0KGgo=",
    );
    expect(screen.getByTestId("node-result-table")).toBeInTheDocument();
    expect(screen.getByText("ok", { selector: "td" })).toBeInTheDocument();
    // zh 环境下指标名中文化：r2 → R² (决定系数)
    expect(screen.getByText("R² (决定系数)")).toBeInTheDocument();
    expect(screen.getByText("0.9")).toBeInTheDocument();
    expect(screen.getByText("ok", { selector: "pre" })).toBeInTheDocument();
    const json = screen.getByTestId("node-result-json");
    expect(json.textContent).toContain('"source": "test"');
    expect(json.textContent?.length).toBeLessThan(5200);
  });

  it("does not open for incomplete or non-visualization nodes", () => {
    useWorkflowStore.setState({
      nodeStatuses: { "viz-1": "running" },
      nodeResults: { "viz-1": { chart: "iVBORw0KGgo=" } },
    });
    useWorkflowStore.getState().openNodeResult("viz-1");
    expect(useWorkflowStore.getState().resultPanelNodeId).toBeNull();

    useWorkflowStore.setState({
      nodes: [{ ...visualizationNode, data: { ...visualizationNode.data, category: "processing" } } as any],
      nodeStatuses: { "viz-1": "completed" },
    });
    useWorkflowStore.getState().openNodeResult("viz-1");
    expect(useWorkflowStore.getState().resultPanelNodeId).toBeNull();
  });
});
