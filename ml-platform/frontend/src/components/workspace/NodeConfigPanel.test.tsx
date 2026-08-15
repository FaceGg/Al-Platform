import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { getPortLabel, NodeResultPanel } from "./NodeConfigPanel";
import { useWorkflowStore } from "../../stores/workflowStore";

const visualizationNode = {
  id: "viz-1",
  type: "custom",
  position: { x: 0, y: 0 },
  data: { operatorId: "line_chart", label: "Line chart", category: "visualization" },
};

beforeEach(() => {
  useWorkflowStore.getState().reset();
  useWorkflowStore.setState({ nodes: [visualizationNode as any] });
});

describe("operator parameter labels", () => {
  it("localizes join key labels for both supported languages", () => {
    expect(getPortLabel("join", "left_keys", "zh")).toBe("左侧键列（逗号分隔）");
    expect(getPortLabel("join", "right_keys", "en")).toBe("Right Key Columns (comma-separated)");
  });

  it("returns an empty label when a parameter has no special mapping", () => {
    expect(getPortLabel("join", "unknown", "zh")).toBeNull();
  });
});

describe("visualization result panel", () => {
  it("opens for a completed visualization node and renders chart, table, JSON, metrics, and logs", () => {
    useWorkflowStore.setState({
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
    expect(screen.getByText("r2")).toBeInTheDocument();
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
