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

  it("copies and pastes the selected node with a new identity and offset", () => {
    useWorkflowStore.getState().addNode("join", { x: 100, y: 200 }, { operatorId: "join", name: "Join" });
    const source = useWorkflowStore.getState().nodes[0];
    useWorkflowStore.getState().selectNode(source);
    useWorkflowStore.getState().copySelectedNode();
    useWorkflowStore.getState().pasteNode();
    const nodes = useWorkflowStore.getState().nodes;
    expect(nodes).toHaveLength(2);
    expect(nodes[1].id).not.toBe(source.id);
    expect(nodes[1].position).toEqual({ x: 140, y: 240 });
    expect(nodes[1].data.params).toEqual(source.data.params);
  });

  it("replaces edges sharing a logical source or target endpoint", () => {
    const store = useWorkflowStore.getState();
    store.onConnect({ source: "source-a", sourceHandle: "data", target: "join", targetHandle: "left" });
    store.onConnect({ source: "source-b", sourceHandle: "data", target: "join", targetHandle: "left" });
    store.onConnect({ source: "source-b", sourceHandle: "other", target: "join", targetHandle: "right" });
    store.onConnect({ source: "source-c", sourceHandle: "data", target: "join", targetHandle: "right" });
    store.onConnect({ source: "source-b", sourceHandle: "data", target: "other", targetHandle: "input" });
    const edges = useWorkflowStore.getState().edges;
    expect(edges).toHaveLength(2);
    expect(edges.map((edge) => ({ source: edge.source, sourceHandle: edge.sourceHandle, targetHandle: edge.targetHandle }))).toEqual([
      { source: "source-c", sourceHandle: "data", targetHandle: "right" },
      { source: "source-b", sourceHandle: "data", targetHandle: "input" },
    ]);
  });

  it("normalizes legacy slot suffixes when connecting", () => {
    useWorkflowStore.getState().onConnect({
      source: "source",
      sourceHandle: "data__slot_3",
      target: "target",
      targetHandle: "input__slot_2",
    });
    expect(useWorkflowStore.getState().edges[0]).toMatchObject({
      sourceHandle: "data",
      targetHandle: "input",
    });
  });
});
