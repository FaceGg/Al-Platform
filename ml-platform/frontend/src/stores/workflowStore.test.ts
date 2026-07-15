import { describe, it, expect, beforeEach } from "vitest";
import { useWorkflowStore } from "./workflowStore";

describe("workflowStore", () => {
  beforeEach(() => {
    useWorkflowStore.setState({
      nodes: [],
      edges: [],
      selectedNode: null,
      isRunning: false,
      currentRunId: null,
      workflowStatus: "pending",
      nodeStatuses: {},
      nodeResults: {},
      nodeProgress: {},
    });
  });

  it("initial state is empty", () => {
    const state = useWorkflowStore.getState();
    expect(state.nodes).toEqual([]);
    expect(state.edges).toEqual([]);
    expect(state.selectedNode).toBeNull();
    expect(state.isRunning).toBe(false);
  });

  it("addNode adds a node to the store", () => {
    useWorkflowStore.getState().addNode("csv_import", { x: 100, y: 200 }, { operatorId: "csv_import", label: "CSV Import", status: "idle" });
    const state = useWorkflowStore.getState();
    expect(state.nodes).toHaveLength(1);
    expect(state.nodes[0].data?.operatorId).toBe("csv_import");
  });

  it("selectNode updates selected node", () => {
    const node = { id: "node-123", type: "custom", position: { x: 0, y: 0 }, data: { operatorId: "test", label: "Test" } };
    useWorkflowStore.getState().selectNode(node);
    expect(useWorkflowStore.getState().selectedNode?.id).toBe("node-123");
  });

  it("selectNode with null clears selection", () => {
    const node = { id: "node-456", type: "custom", position: { x: 0, y: 0 }, data: { operatorId: "test", label: "Test" } };
    useWorkflowStore.getState().selectNode(node);
    useWorkflowStore.getState().selectNode(null);
    expect(useWorkflowStore.getState().selectedNode).toBeNull();
  });

  it("setNodeStatus changes a node status", () => {
    useWorkflowStore.getState().setNodeStatus("n1", "running");
    expect(useWorkflowStore.getState().nodeStatuses["n1"]).toBe("running");
  });

  it("setIsRunning updates running state", () => {
    useWorkflowStore.getState().setIsRunning(true);
    expect(useWorkflowStore.getState().isRunning).toBe(true);
  });

  it("tracks current run and cooperative cancellation state", () => {
    useWorkflowStore.getState().setCurrentRunId("run-123");
    useWorkflowStore.getState().setWorkflowStatus("cancel_requested");
    expect(useWorkflowStore.getState().currentRunId).toBe("run-123");
    expect(useWorkflowStore.getState().workflowStatus).toBe("cancel_requested");
  });

  it("resetExecution clears previous run state", () => {
    useWorkflowStore.getState().setCurrentRunId("run-123");
    useWorkflowStore.getState().setWorkflowStatus("failed");
    useWorkflowStore.getState().setNodeStatus("n1", "timed_out");
    useWorkflowStore.getState().resetExecution();
    const state = useWorkflowStore.getState();
    expect(state.currentRunId).toBeNull();
    expect(state.workflowStatus).toBe("pending");
    expect(state.nodeStatuses).toEqual({});
  });

  it("reset clears state", () => {
    useWorkflowStore.getState().addNode("test", { x: 0, y: 0 }, { operatorId: "test", label: "Test" });
    useWorkflowStore.getState().setNodeStatus("n1", "running");
    expect(useWorkflowStore.getState().isRunning).toBe(false);
  });
});
