import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";
import { beforeEach, describe, expect, it } from "vitest";
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

describe("CustomNode dynamic port slots", () => {
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

  it("renders one distinct handle for every connected slot and the next available slot", () => {
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

    expect(screen.getByTestId("port-in-left__slot_0")).toBeInTheDocument();
    expect(screen.getByTestId("port-in-left__slot_1")).toBeInTheDocument();
    expect(screen.getByTestId("port-in-left__slot_2")).toBeInTheDocument();
    expect(screen.getByTestId("port-out-data__slot_0")).toBeInTheDocument();
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
    expect(screen.getByTestId("port-in-source__slot_0")).toBeInTheDocument();
    expect(screen.getByTestId("port-out-data__slot_0")).toBeInTheDocument();
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