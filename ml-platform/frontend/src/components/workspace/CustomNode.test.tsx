import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CustomNode, { abbreviatePortName } from "./CustomNode";
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

  it("renders one stable named handle for every port on a multi-port node", () => {
    render(
      <ReactFlowProvider>
        <CustomNode
          id="multi-port-1"
          type="custom"
          selected={false}
          dragging={false}
          zIndex={0}
          isConnectable
          xPos={0}
          yPos={0}
          data={{
            nodeId: "multi-port-1",
            operatorId: "join",
            label: "Join",
            inputs: [
              { name: "left", label: "Left", type: "ExampleSet" },
              { name: "right", label: "Right", type: "ExampleSet" },
              { name: "weights", label: "Weights", type: "ExampleSet" },
            ],
            outputs: [
              { name: "data", label: "Data", type: "ExampleSet" },
              { name: "metrics", label: "Metrics", type: "Json" },
            ],
          }}
        />
      </ReactFlowProvider>,
    );

    for (const portName of ["left", "right", "weights"]) {
      const handles = screen.getAllByTestId(`port-in-${portName}`);
      expect(handles).toHaveLength(1);
      expect(handles[0]).toHaveAttribute("data-handleid", portName);
    }
    for (const portName of ["data", "metrics"]) {
      const handles = screen.getAllByTestId(`port-out-${portName}`);
      expect(handles).toHaveLength(1);
      expect(handles[0]).toHaveAttribute("data-handleid", portName);
    }
    expect(screen.queryAllByTestId(/__slot_/)).toHaveLength(0);
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

  it("abbreviates port names into three uppercase logical characters", () => {
    expect(abbreviatePortName("source_data")).toBe("SOU");
    expect(abbreviatePortName("🧪Data")).toBe("🧪DA");
  });

  it("renders an abbreviated label beside every declared input and output handle", () => {
    render(
      <ReactFlowProvider>
        <CustomNode
          id="node-port-labels"
          type="custom"
          selected={false}
          dragging={false}
          zIndex={0}
          isConnectable
          xPos={0}
          yPos={0}
          data={{
            nodeId: "node-port-labels",
            operatorId: "join",
            inputs: [
              { name: "left", type: "ExampleSet" },
              { name: "configuration", type: "Config" },
            ],
            outputs: [
              { name: "predictions", type: "ExampleSet" },
              { name: "summary", type: "Summary" },
            ],
          }}
        />
      </ReactFlowProvider>,
    );

    expect(screen.getByTestId("port-label-in-left")).toHaveTextContent("LEF");
    expect(screen.getByTestId("port-label-in-configuration")).toHaveTextContent("CON");
    expect(screen.getByTestId("port-label-out-predictions")).toHaveTextContent("PRE");
    expect(screen.getByTestId("port-label-out-summary")).toHaveTextContent("SUM");
    expect(screen.getByTestId("port-in-left")).toHaveAttribute("data-handleid", "left");
  });

  it("anchors compact semi-circle handles to the outer node edges without aggregate counts", () => {
    render(
      <ReactFlowProvider>
        <CustomNode
          id="node-port-geometry"
          type="custom"
          selected={false}
          dragging={false}
          zIndex={0}
          isConnectable
          xPos={0}
          yPos={0}
          data={{
            nodeId: "node-port-geometry",
            operatorId: "join",
            inputs: [{ name: "left", type: "ExampleSet" }],
            outputs: [{ name: "data", type: "ExampleSet" }],
          }}
        />
      </ReactFlowProvider>,
    );

    expect(screen.getByTestId("port-in-left")).toHaveStyle({ left: "-20px" });
    expect(screen.getByTestId("port-out-data")).toHaveStyle({ right: "-20px" });
    expect(screen.queryByText("IN 1")).not.toBeInTheDocument();
    expect(screen.queryByText("OUT 1")).not.toBeInTheDocument();
    expect(cssRule(".workflow-node-handle.react-flow__handle")).toContain("width: 20px !important;");
    expect(cssRule(".workflow-node-handle.react-flow__handle")).toContain("height: 28px !important;");
    expect(cssRule(".workflow-node-handle--input.react-flow__handle")).toContain("border-right: 0 !important;");
    expect(cssRule(".workflow-node-handle--input.react-flow__handle")).toContain("border-radius: 14px 0 0 14px !important;");
    expect(cssRule(".workflow-node-handle--output.react-flow__handle")).toContain("border-left: 0 !important;");
    expect(cssRule(".workflow-node-handle--output.react-flow__handle")).toContain("border-radius: 0 14px 14px 0 !important;");
  });
});
describe("CustomNode visual density", () => {
  it("uses a rounded square tile with centered operator identity and no count strip", () => {
    expect(cssRule(".workflow-node")).toContain("width: 176px;");
    expect(cssRule(".workflow-node")).toContain("min-height: 176px;");
    expect(cssRule(".workflow-node")).toContain("aspect-ratio: 1;");
    expect(cssRule(".workflow-node")).toContain("padding: 12px 28px;");
    expect(cssRule(".workflow-node__header")).toContain("grid-template-columns: 26px minmax(0, 1fr);");
    expect(cssRule(".workflow-node__header")).toContain("grid-template-rows: 26px minmax(0, 1fr);");
    expect(cssRule(".workflow-node__header")).toContain("flex: 1;");
    expect(cssRule(".workflow-node__category")).toContain("grid-column: 1;");
    expect(cssRule(".workflow-node__category")).toContain("grid-row: 1;");
    expect(cssRule(".workflow-node__identity")).toContain("grid-column: 1 / -1;");
    expect(cssRule(".workflow-node__identity")).toContain("grid-row: 2;");
    expect(cssRule(".workflow-node__identity")).toContain("justify-items: center;");
    expect(cssRule(".workflow-node__identity")).toContain("text-align: center;");
    expect(cssRule(".workflow-node__status")).toContain("grid-column: 2;");
    expect(cssRule(".workflow-node__status")).toContain("grid-row: 1;");
    expect(cssRule(".workflow-node__status")).toContain("justify-self: end;");
    expect(cssRule(".workflow-node__title")).toContain("font-size: 14px;");
    expect(cssRule(".workflow-node__operator-id")).toContain("font-size: 11px;");
    expect(cssRule(".workflow-node__status")).toContain("font-size: 11px;");
    expect(cssRule(".workflow-node__port-label")).toContain("width: 22px;");
    expect(workflowStyles).not.toContain(".workflow-node__signals {");
  });

  it("uses the core node treatment without a central ring", () => {
    expect(cssRule(".workflow-node")).toContain("border-radius: 30px;");
    expect(cssRule(".workflow-node")).toContain("position: relative;");
    expect(cssRule(".workflow-node::before")).toContain("content: none;");
    expect(cssRule(".workflow-node::after")).toContain("inset: 8px;");
    expect(cssRule(".workflow-node::after")).toContain("border-radius: 22px;");
    expect(cssRule(".workflow-node__category")).toContain("border-radius: 50%;");
    expect(cssRule(".workflow-node__category")).toContain("var(--workflow-node-accent)");
    expect(cssRule(".workflow-node__status")).toContain("min-width: 28px;");
    expect(cssRule(".workflow-node__status")).toContain("justify-content: center;");
    expect(cssRule(".workflow-node__identity")).toContain("gap: 4px;");
    expect(cssRule(".workflow-node__port-label")).toContain("opacity: 0.7;");
    expect(cssRule(".workflow-flow")).toContain("--workflow-edge: color-mix(in srgb, var(--accent-secondary)");
  });
});
