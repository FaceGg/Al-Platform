import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CustomNode from "./CustomNode";
import { useWorkflowStore } from "../../stores/workflowStore";

const workflowStyles = readFileSync(
  resolve(process.cwd(), "src/styles/global.css"),
  "utf8",
);

function cssRule(selector: string): string {
  const start = workflowStyles.indexOf(`${selector} {`);
  const end = workflowStyles.indexOf("}", start);
  return start === -1 || end === -1 ? "" : workflowStyles.slice(start, end + 1);
}

describe("CustomNode stable logical port handles", () => {
  beforeEach(() => {
    useWorkflowStore.getState().reset();
    useWorkflowStore.setState({
      edges: [
        {
          id: "edge-1",
          source: "source-1",
          sourceHandle: "data__slot_0",
          target: "join-1",
          targetHandle: "left__slot_0",
        },
        {
          id: "edge-2",
          source: "source-2",
          sourceHandle: "data__slot_0",
          target: "join-1",
          targetHandle: "left__slot_1",
        },
      ],
    });
  });

  it("renders exactly one stable handle for every declared port", () => {
    render(
      <ReactFlowProvider>
        <CustomNode
          id="join-1"
          type="custom"
          selected={false}
          dragging={false}
          zIndex={0}
          isConnectable
          xPos={0}
          yPos={0}
          data={{
            nodeId: "join-1",
            operatorId: "join",
            label: "Join",
            inputs: [{ name: "left", label: "Left", type: "ExampleSet" }],
            outputs: [{ name: "data", label: "Data", type: "ExampleSet" }],
          }}
        />
      </ReactFlowProvider>,
    );

    expect(screen.getByTestId("port-in-left")).toBeInTheDocument();
    expect(screen.getByTestId("port-out-data")).toBeInTheDocument();
    expect(screen.queryByTestId("port-in-left__slot_0")).not.toBeInTheDocument();
    expect(screen.queryByTestId("port-in-left__slot_1")).not.toBeInTheDocument();
  });
});

describe("CustomNode visual structure", () => {
  beforeEach(() => {
    useWorkflowStore.getState().reset();
  });

  it("renders its status and category markers without changing port slots", () => {
    render(
      <ReactFlowProvider>
        <CustomNode
          id="node-visual"
          type="custom"
          selected={false}
          dragging={false}
          zIndex={0}
          isConnectable
          xPos={0}
          yPos={0}
          data={{
            nodeId: "node-visual",
            operatorId: "csv_import",
            label: "CSV Import",
            category: "data_io",
            inputs: [{ name: "source", label: "Source", type: "File" }],
            outputs: [{ name: "data", label: "Data", type: "ExampleSet" }],
          }}
        />
      </ReactFlowProvider>,
    );

    expect(screen.getByTestId("workflow-node")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-node-category")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-node-status")).toBeInTheDocument();
    expect(screen.getByTestId("port-in-source")).toBeInTheDocument();
    expect(screen.getByTestId("port-out-data")).toBeInTheDocument();
  });

  it("shows endpoint metadata and data preview, hides on click, and reopens after re-hover", async () => {
    useWorkflowStore.setState({
      nodeResults: { "node-preview": { data: [{ id: 1, value: "ok" }] } },
      edges: [],
    });

    render(
      <ReactFlowProvider>
        <CustomNode
          id="node-preview"
          type="custom"
          selected={false}
          dragging={false}
          zIndex={0}
          isConnectable
          xPos={0}
          yPos={0}
          data={{
            nodeId: "node-preview",
            operatorId: "csv_import",
            label: "CSV Import",
            outputs: [{ name: "data", label: "Data", type: "DataTable", format: "records" }],
            inputs: [],
          }}
        />
      </ReactFlowProvider>,
    );

    const endpoint = screen.getByTestId("port-out-data");
    fireEvent.mouseEnter(endpoint);
    expect(await screen.findByText("DataTable")).toBeInTheDocument();
    expect(screen.getByText("records")).toBeInTheDocument();
    expect(screen.getByText(/2 列 × 1 行/)).toBeInTheDocument();
    expect(screen.getAllByText(/id/).length).toBeGreaterThan(0);

    fireEvent.mouseDown(endpoint);
    await waitFor(() => expect(screen.queryByText("DataTable")).not.toBeInTheDocument());

    fireEvent.mouseLeave(endpoint);
    fireEvent.mouseEnter(endpoint);
    expect(await screen.findByText("DataTable")).toBeInTheDocument();
  });

  it("clears preview on pointer down without intercepting Handle click propagation", async () => {
    const parentClick = vi.fn();
    render(
      <div onClick={parentClick}>
        <ReactFlowProvider>
          <CustomNode
            id="node-connect"
            type="custom"
            selected={false}
            dragging={false}
            zIndex={0}
            isConnectable
            xPos={0}
            yPos={0}
            data={{
              nodeId: "node-connect",
              operatorId: "csv_import",
              outputs: [{ name: "data", label: "Data", type: "DataTable", format: "records" }],
              inputs: [],
            }}
          />
        </ReactFlowProvider>
      </div>,
    );

    const endpoint = screen.getByTestId("port-out-data");
    fireEvent.mouseEnter(endpoint);
    expect(await screen.findByText("DataTable")).toBeInTheDocument();
    fireEvent.mouseDown(endpoint);
    await waitFor(() => expect(screen.queryByText("DataTable")).not.toBeInTheDocument());
    fireEvent.click(endpoint);
    expect(parentClick).toHaveBeenCalled();
  });

  it("opens failed node error details from the status label", async () => {
    useWorkflowStore.setState({
      nodeErrors: {
        "node-failed": {
          code: "NODE_EXECUTION_FAILED",
          message: "operator failed",
          nodeId: "node-failed",
          attempt: 2,
        },
      },
    });

    render(
      <ReactFlowProvider>
        <CustomNode
          id="node-failed"
          type="custom"
          selected={false}
          dragging={false}
          zIndex={0}
          isConnectable
          xPos={0}
          yPos={0}
          data={{
            nodeId: "node-failed",
            operatorId: "csv_import",
            label: "CSV Import",
            status: "failed",
            outputs: [],
            inputs: [],
          }}
        />
      </ReactFlowProvider>,
    );

    fireEvent.click(screen.getByTestId("workflow-node-status"));
    expect(await screen.findByText("NODE_EXECUTION_FAILED")).toBeInTheDocument();
    expect(screen.getAllByText("operator failed").length).toBeGreaterThan(0);
    expect(screen.getByText("node-failed")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
describe("CustomNode visual density", () => {
  it("keeps operator copy readable while using a compact node shell", () => {
    expect(cssRule(".workflow-node")).toContain("min-height: 128px;");
    expect(cssRule(".workflow-node")).toContain("padding: 10px 14px 10px;");
    expect(cssRule(".workflow-node__title")).toContain("font-size: 14px;");
    expect(cssRule(".workflow-node__operator-id")).toContain("font-size: 11px;");
    expect(cssRule(".workflow-node__status")).toContain("font-size: 11px;");
    expect(cssRule(".workflow-node__signals")).toContain("margin-top: 9px;");
    expect(cssRule(".workflow-node__signals")).toContain("padding-top: 7px;");
    expect(cssRule(".workflow-node__signals")).toContain("font-size: 11px;");
  });
});
