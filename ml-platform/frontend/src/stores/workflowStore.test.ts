import { describe, it, expect, beforeEach } from "vitest";
import { normalizeNodeError, useWorkflowStore } from "./workflowStore";

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
      nodeErrors: {},
      nodeProgress: {},
      exportDirectories: {},
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

  it("opens and closes a completed visualization node result", () => {
    useWorkflowStore.setState({
      nodes: [{
        id: "viz-1",
        type: "custom",
        position: { x: 0, y: 0 },
        data: { operatorId: "line_chart", category: "visualization" },
      } as any],
      nodeStatuses: { "viz-1": "completed" },
      nodeResults: { "viz-1": { chart: "iVBORw0KGgo=" } },
    });

    useWorkflowStore.getState().openNodeResult("viz-1");
    expect(useWorkflowStore.getState().resultPanelNodeId).toBe("viz-1");
    useWorkflowStore.getState().closeNodeResult();
    expect(useWorkflowStore.getState().resultPanelNodeId).toBeNull();

    useWorkflowStore.getState().openNodeResult("viz-1");
    useWorkflowStore.getState().setNodeStatus("viz-1", "running");
    expect(useWorkflowStore.getState().resultPanelNodeId).toBeNull();
  });

  it("stores node errors without overwriting status or result", () => {
    useWorkflowStore.getState().setNodeStatus("n1", "failed");
    useWorkflowStore.getState().setNodeResult("n1", { data: [{ id: 1 }] });
    useWorkflowStore.getState().setNodeError("n1", {
      code: "NODE_EXECUTION_FAILED",
      message: "operator failed",
      nodeId: "n1",
      attempt: 2,
    });

    const state = useWorkflowStore.getState();
    expect(state.nodeStatuses["n1"]).toBe("failed");
    expect(state.nodeResults["n1"]).toEqual({ data: [{ id: 1 }] });
    expect(state.nodeErrors["n1"]).toEqual({
      code: "NODE_EXECUTION_FAILED",
      message: "operator failed",
      nodeId: "n1",
      attempt: 2,
    });
  });

  it("normalizes persisted and websocket error fields", () => {
    expect(normalizeNodeError("n1", {
      error_code: "NODE_TIMED_OUT",
      error_message: "deadline exceeded",
      error_details: { node_id: "n1" },
      attempt: 3,
    })).toEqual({
      code: "NODE_TIMED_OUT",
      message: "deadline exceeded",
      nodeId: "n1",
      attempt: 3,
      details: { node_id: "n1" },
    });
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

  it("retains the selected export directory when a new run resets execution state", () => {
    const directory = {
      name: "exports",
      getFileHandle: async () => ({
        createWritable: async () => ({ write: async () => {}, close: async () => {} }),
      }),
    };
    useWorkflowStore.getState().setExportDirectory("export-1", { name: directory.name, handle: directory });

    useWorkflowStore.getState().resetExecution();

    expect(useWorkflowStore.getState().exportDirectories["export-1"]).toEqual({
      name: "exports",
      handle: directory,
    });
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

  it("replaces legacy slot edges at normalized source and target endpoints", () => {
    useWorkflowStore.setState({
      edges: [
        {
          id: "legacy-source",
          source: "source",
          sourceHandle: "data__slot_4",
          target: "old-target",
          targetHandle: "input",
        },
        {
          id: "legacy-target",
          source: "old-source",
          sourceHandle: "other",
          target: "target",
          targetHandle: "data__slot_9",
        },
        {
          id: "unrelated",
          source: "other-source",
          sourceHandle: "data",
          target: "other-target",
          targetHandle: "input",
        },
      ],
    });

    useWorkflowStore.getState().onConnect({
      source: "source",
      sourceHandle: "data",
      target: "target",
      targetHandle: "data",
    });

    expect(useWorkflowStore.getState().edges).toEqual([
      expect.objectContaining({ id: "unrelated" }),
      expect.objectContaining({
        source: "source",
        sourceHandle: "data",
        target: "target",
        targetHandle: "data",
      }),
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
