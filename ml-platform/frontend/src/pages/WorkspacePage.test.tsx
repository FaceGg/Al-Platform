import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App as AntApp, ConfigProvider } from "antd";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import WorkspacePage, { hydrateWorkflowEdges, resolvePort } from "./WorkspacePage";
import { isVisualizationResultNode } from "../components/workspace/workflowVisualization";
import { LangProvider } from "../i18n";
import { useWorkflowStore } from "../stores/workflowStore";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("../api/client", () => ({
  default: apiClientMock,
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../components/workspace/OperatorPanel", () => ({ default: () => null }));
vi.mock("../components/workspace/ExecutionProgress", () => ({ default: () => null }));
vi.mock("../components/workspace/NodeConfigPanel", () => ({
  default: () => null,
  NodeResultPanel: () => null,
}));
vi.mock("../components/workspace/WorkflowCanvas", () => ({ default: () => null }));

class TestWebSocket {
  static instances: TestWebSocket[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  close = vi.fn();

  constructor(readonly url: string) {
    TestWebSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.(new Event("open"));
  }

  message(payload: unknown): void {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(payload) }));
  }
}

function renderWorkspacePage(): void {
  render(
    <ConfigProvider>
      <AntApp>
        <LangProvider>
          <MemoryRouter initialEntries={["/workspace/workflow-1"]}>
            <Routes>
              <Route path="/workspace/:workflowId" element={<WorkspacePage />} />
            </Routes>
          </MemoryRouter>
        </LangProvider>
      </AntApp>
    </ConfigProvider>,
  );
}

beforeEach(() => {
  useWorkflowStore.getState().reset();
  TestWebSocket.instances = [];
  vi.stubGlobal("WebSocket", TestWebSocket);
  apiClientMock.get.mockReset().mockImplementation((url: string) => {
    if (url === "/operators") {
      return Promise.resolve({ data: [{ id: "csv_export", category: "utility", inputs: [], outputs: [{ name: "data" }] }] });
    }
    if (url === "/workflows/workflow-1") {
      return Promise.resolve({
        data: {
          name: "Export workflow",
          nodes: [{
            id: "export-1",
            operator_id: "csv_export",
            label: "CSV export",
            params: {},
            position_x: 0,
            position_y: 0,
          }],
          edges: [],
        },
      });
    }
    if (url === "/runs/run-1") {
      return Promise.resolve({
        data: {
          status: "completed",
          node_runs: [{
            node_id: "export-1",
            status: "completed",
            result: {
              data: [{ id: 1, status: "ok" }],
              artifacts: [{ artifact_id: "artifact-1", name: "export.csv", format: "csv" }],
            },
            metrics: null,
            logs: [],
          }],
        },
      });
    }
    return Promise.reject(new Error(`Unexpected GET ${url}`));
  });
  apiClientMock.put.mockReset().mockResolvedValue({ data: {} });
  apiClientMock.post.mockReset().mockResolvedValue({ data: { run_id: "run-1", status: "pending" } });
  apiClientMock.delete.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("workspace port persistence", () => {
  const ports = [{ name: "data" }, { name: "predictions" }];

  it("resolves indexed ReactFlow handles to operator port names", () => {
    expect(resolvePort("out-1", ports)).toBe("predictions");
    expect(resolvePort("in-0", ports)).toBe("data");
  });

  it("preserves named and unknown handles", () => {
    expect(resolvePort("model", ports)).toBe("model");
    expect(resolvePort("out-9", ports)).toBe("out-9");
  });

  it("maps dynamic handle slots back to their logical port", () => {
    expect(resolvePort("data__slot_2", ports)).toBe("data");
  });

  it("normalizes legacy slot handles during hydration", () => {
    expect(hydrateWorkflowEdges([
      {
        id: "e",
        source: "a",
        target: "b",
        source_port: "data__slot_3",
        target_port: "in__slot_2",
      },
    ])[0]).toMatchObject({
      source: "a",
      target: "b",
      sourceHandle: "data",
      targetHandle: "in",
    });
  });

  it("maps indexed legacy handles to named ports before deduplicating", () => {
    const hydrateWithNodes = hydrateWorkflowEdges as unknown as (edges: any[], nodes: any[]) => any[];

    expect(hydrateWithNodes([
      {
        id: "legacy",
        source: "source",
        target: "target",
        source_port: "out-0",
        target_port: "in-0",
      },
      {
        id: "replacement",
        source: "source",
        target: "target",
        source_port: "data",
        target_port: "input",
      },
    ], [
      { id: "source", data: { outputs: [{ name: "data" }] } },
      { id: "target", data: { inputs: [{ name: "input" }] } },
    ])).toEqual([
      expect.objectContaining({
        id: "replacement",
        sourceHandle: "data",
        targetHandle: "input",
      }),
    ]);
  });

  it("keeps only the latest edge for each normalized source or target endpoint", () => {
    expect(hydrateWorkflowEdges([
      {
        id: "source-first",
        source: "source-a",
        target: "target-a",
        source_port: "data__slot_0",
        target_port: "input__slot_0",
      },
      {
        id: "source-latest",
        source: "source-a",
        target: "target-b",
        source_port: "data__slot_1",
        target_port: "input__slot_0",
      },
      {
        id: "target-first",
        source: "source-c",
        target: "target-c",
        source_port: "data__slot_0",
        target_port: "input__slot_0",
      },
      {
        id: "target-latest",
        source: "source-d",
        target: "target-c",
        source_port: "data__slot_0",
        target_port: "input__slot_1",
      },
    ])).toEqual([
      {
        id: "source-latest",
        source: "source-a",
        target: "target-b",
        sourceHandle: "data",
        targetHandle: "input",
      },
      {
        id: "target-latest",
        source: "source-d",
        target: "target-c",
        sourceHandle: "data",
        targetHandle: "input",
      },
    ]);
  });
});

describe("visualization result click gating", () => {
  const node = {
    id: "viz-1",
    data: { operatorId: "line_chart", category: "visualization" },
  };

  it("allows canvas result opening only for completed visualization nodes", () => {
    expect(isVisualizationResultNode(node, "completed")).toBe(true);
    expect(isVisualizationResultNode(node, "running")).toBe(false);
    expect(isVisualizationResultNode({ ...node, data: { ...node.data, category: "processing" } }, "completed")).toBe(false);
  });

  it("falls back to operator metadata when a node has no category", () => {
    expect(isVisualizationResultNode({ id: "viz-2", data: { operatorId: "line_chart" } }, "completed", [
      { id: "line_chart", category: "visualization" },
    ])).toBe(true);
  });
});

describe("workflow socket recovery", () => {
  it("stores the completed export artifact without starting an automatic download", async () => {
    renderWorkspacePage();

    await waitFor(() => expect(screen.getByRole("button", { name: /运行/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /运行/ }));

    await waitFor(() => expect(TestWebSocket.instances).toHaveLength(1));
    TestWebSocket.instances[0].open();

    await waitFor(() => expect(useWorkflowStore.getState().nodeResults["export-1"]?.artifacts).toEqual([
      { artifact_id: "artifact-1", name: "export.csv", format: "csv" },
    ]));
    TestWebSocket.instances[0].message({
      type: "node_status",
      node_id: "export-1",
      status: "completed",
      result: {
        data: [{ id: 1, status: "ok" }],
        artifacts: [{ artifact_id: "artifact-1", name: "export.csv", format: "csv" }],
      },
    });

    await Promise.resolve();
    expect(useWorkflowStore.getState().nodeResults["export-1"]?.artifacts).toHaveLength(1);
  });
});
