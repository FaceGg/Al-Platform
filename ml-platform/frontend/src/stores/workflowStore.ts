import { create } from "zustand";
import { Node, Edge, applyNodeChanges, applyEdgeChanges, addEdge, Connection, NodeChange, EdgeChange } from "reactflow";
import type { ReactFlowInstance } from "reactflow";

export type WorkflowRunStatus = "pending" | "running" | "cancel_requested" | "completed" | "failed" | "cancelled";
export type NodeRunStatus = "pending" | "running" | "completed" | "failed" | "timed_out" | "cancelled" | "skipped";

export interface WorkflowState {
  nodes: Node[];
  edges: Edge[];
  selectedNode: Node | null;
  isRunning: boolean;
  currentRunId: string | null;
  workflowStatus: WorkflowRunStatus;
  nodeStatuses: Record<string, NodeRunStatus>;
  nodeResults: Record<string, any>;
  nodeProgress: Record<string, number>;
  operators: any[];
  reactFlowInstance: ReactFlowInstance | null;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  addNode: (type: string, position: { x: number; y: number }, operatorData: any) => void;
  selectNode: (node: Node | null) => void;
  updateNodeParams: (nodeId: string, params: any) => void;
  setOperators: (ops: any[]) => void;
  setIsRunning: (v: boolean) => void;
  setCurrentRunId: (runId: string | null) => void;
  setWorkflowStatus: (status: WorkflowRunStatus) => void;
  setNodeStatus: (nodeId: string, status: NodeRunStatus) => void;
  setNodeResult: (nodeId: string, result: any) => void;
  setNodeProgress: (nodeId: string, progress: number) => void;
  setReactFlowInstance: (instance: ReactFlowInstance | null) => void;
  removeEdge: (edgeId: string) => void;
  resetExecution: () => void;
  reset: () => void;
}

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNode: null,
  isRunning: false,
  currentRunId: null,
  workflowStatus: "pending",
  nodeStatuses: {},
  nodeResults: {},
  nodeProgress: {},
  operators: [],
  reactFlowInstance: null,

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  onNodesChange: (changes) =>
    set((state) => ({
      nodes: applyNodeChanges(changes, state.nodes),
    })),

  onEdgesChange: (changes) =>
    set((state) => ({
      edges: applyEdgeChanges(changes, state.edges),
    })),

  onConnect: (connection) =>
    set((state) => ({
      edges: addEdge({ ...connection, type: "custom" }, state.edges),
    })),

  addNode: (type, position, operatorData) =>
    set((state) => {
      const newId = "node_" + Date.now() + "_" + Math.random().toString(36).slice(2, 7);

      // Count existing nodes with the same operator type for suffix numbering
      const sameTypeCount = state.nodes.filter((n) => n.data?.operatorId === type).length;
      const suffix = sameTypeCount > 0 ? " (" + (sameTypeCount + 1) + ")" : "";
      const label = (operatorData.name || type) + suffix;

      // Extract port definitions from operator data
      const inputs = operatorData.inputs || [];
      const outputs = operatorData.outputs || [];

      const newNode: Node = {
        id: newId,
        type: "custom",
        position,
        data: {
          operatorId: type,
          label: label,
          category: operatorData.category,
          params: {},
          inputs: inputs,
          outputs: outputs,
        },
      };
      return { nodes: [...state.nodes, newNode] };
    }),

  selectNode: (node) => set({ selectedNode: node }),

  updateNodeParams: (nodeId, params) =>
    set((state) => ({
      nodes: state.nodes.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, params } } : n)),
    })),

  setOperators: (ops) => set({ operators: ops }),
  setIsRunning: (v) => set({ isRunning: v }),
  setCurrentRunId: (runId) => set({ currentRunId: runId }),
  setWorkflowStatus: (status) => set({ workflowStatus: status }),

  setNodeStatus: (nodeId, status) =>
    set((state) => ({
      nodeStatuses: { ...state.nodeStatuses, [nodeId]: status },
    })),

  setNodeResult: (nodeId, result) =>
    set((state) => ({
      nodeResults: { ...state.nodeResults, [nodeId]: result },
    })),

  setNodeProgress: (nodeId, progress) =>
    set((state) => ({
      nodeProgress: { ...state.nodeProgress, [nodeId]: progress },
    })),

  setReactFlowInstance: (instance) => set({ reactFlowInstance: instance }),

  removeEdge: (edgeId) =>
    set((state) => ({
      edges: applyEdgeChanges([{ type: "remove", id: edgeId } as EdgeChange], state.edges),
      isDirty: true,
    })),

  resetExecution: () =>
    set({
      nodeStatuses: {},
      nodeResults: {},
      nodeProgress: {},
      isRunning: false,
      currentRunId: null,
      workflowStatus: "pending",
    }),

  reset: () =>
    set({
      nodes: [],
      edges: [],
      selectedNode: null,
      nodeStatuses: {},
      nodeResults: {},
      nodeProgress: {},
      isRunning: false,
      currentRunId: null,
      workflowStatus: "pending",
    }),
}));
