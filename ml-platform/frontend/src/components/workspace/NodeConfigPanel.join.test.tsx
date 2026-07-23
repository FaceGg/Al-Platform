import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import NodeConfigPanel from "./NodeConfigPanel";
import { useWorkflowStore } from "../../stores/workflowStore";

describe("NodeConfigPanel Join configuration", () => {
  beforeEach(() => {
    useWorkflowStore.getState().reset();
    useWorkflowStore.setState({
      selectedNode: {
        id: "join-1",
        type: "custom",
        position: { x: 0, y: 0 },
        data: {
          operatorId: "join",
          label: "Join",
          params: { left_keys: "plant", right_keys: "site" },
        },
      },
      operators: [{
        id: "join",
        parameters: [
          { name: "join_type", type: "select", default: "inner", options: ["inner"] },
          { name: "left_keys", type: "str", default: "" },
          { name: "right_keys", type: "str", default: "" },
        ],
      }],
      edges: [
        { id: "left-edge", source: "source-left", sourceHandle: "data", target: "join-1", targetHandle: "left__slot_0" },
        { id: "right-edge", source: "source-right", sourceHandle: "data", target: "join-1", targetHandle: "right__slot_0" },
      ],
      nodeResults: {
        "source-left": { data: [{ plant: "A", part: "P1" }] },
        "source-right": { data: [{ site: "A", part_id: "P1" }] },
      },
    });
  });

  it("edits Join keys as explicit left/right pairs", () => {
    render(<NodeConfigPanel />);

    expect(screen.getByRole("button", { name: "添加键对" })).toBeInTheDocument();
    expect(screen.getByText("左侧键列")).toBeInTheDocument();
    expect(screen.getByText("右侧键列")).toBeInTheDocument();
  });
});
