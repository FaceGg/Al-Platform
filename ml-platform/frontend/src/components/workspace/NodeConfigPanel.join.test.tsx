import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import NodeConfigPanel from "./NodeConfigPanel";
import { useWorkflowStore } from "../../stores/workflowStore";

describe("NodeConfigPanel Join configuration", () => {
  beforeEach(() => {
    useWorkflowStore.getState().reset();
    const selectedNode = {
      id: "join-1",
      type: "custom",
      position: { x: 0, y: 0 },
      data: {
        operatorId: "join",
        label: "Join",
        params: { left_keys: "plant", right_keys: "site" },
      },
    } as any;
    useWorkflowStore.setState({
      nodes: [selectedNode],
      selectedNode,
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

  it("keeps a newly added blank key pair visible and persisted", () => {
    render(<NodeConfigPanel />);

    fireEvent.click(screen.getByRole("button", { name: "添加键对" }));

    expect(screen.getAllByText("左侧键列")).toHaveLength(2);
    expect(useWorkflowStore.getState().nodes[0].data.params).toMatchObject({
      left_keys: "plant,",
      right_keys: "site,",
    });
  });

  it("accepts manual key names before upstream results exist", () => {
    const selectedNode = {
      id: "join-1",
      type: "custom",
      position: { x: 0, y: 0 },
      data: { operatorId: "join", label: "Join", params: {} },
    } as any;
    useWorkflowStore.setState({
      nodes: [selectedNode],
      selectedNode,
      nodeResults: {},
    });
    render(<NodeConfigPanel />);

    fireEvent.change(screen.getByRole("textbox", { name: "左侧键列" }), {
      target: { value: "plant" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "右侧键列" }), {
      target: { value: "site" },
    });

    expect(useWorkflowStore.getState().nodes[0].data.params).toMatchObject({
      left_keys: "plant",
      right_keys: "site",
    });
  });
});
