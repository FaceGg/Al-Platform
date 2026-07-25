import { create } from "zustand";
import { Node, Edge, applyNodeChanges, applyEdgeChanges, addEdge, Connection, NodeChange, EdgeChange } from "reactflow";
import type { ReactFlowInstance } from "reactflow";
import type { BrowserDirectoryHandle } from "../components/workspace/workflowExport";

export type WorkflowRunStatus = "pending" | "running" | "cancel_requested" | "completed" | "failed" | "cancelled";
export type NodeRunStatus = "pending" | "running" | "completed" | "failed" | "timed_out" | "cancelled" | "skipped";

export interface WorkflowExportDirectory {
  name: string;
  handle: BrowserDirectoryHandle;
}

export interface NodeErrorDetails {
  code: string | null;
  message: string;
  nodeId: string;
  attempt: number | null;
  details?: Record<string, any> | null;
}

export type NodeErrorInput = Partial<NodeErrorDetails> & {
  error?: string | null;
  errorCode?: string | null;
  errorMessage?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  error_details?: Record<string, any> | null;
  node_id?: string | null;
};

/** Convert run/WebSocket error payloads to one stable shape for the canvas. */
export function normalizeNodeError(
  nodeId: string,
  input?: NodeErrorInput | string | null,
): NodeErrorDetails | null {
  if (input == null) return null;
  const payload: NodeErrorInput = typeof input === "string" ? { message: input } : input;
  const code = payload.code ?? payload.errorCode ?? payload.error_code ?? null;
  const message = payload.message ?? payload.errorMessage ?? payload.error_message ?? payload.error ?? "";
  const details = payload.details ?? payload.error_details ?? null;
  if (!code && !message && !details) return null;
  const attemptValue = payload.attempt;
  const attempt = attemptValue == null ? null : Number(attemptValue);
  return {
    code: code ? String(code) : null,
    message: String(message || ""),
    nodeId: String(payload.nodeId ?? payload.node_id ?? nodeId),
    attempt: Number.isFinite(attempt) ? attempt : null,
    ...(details ? { details } : {}),
  };
}

/** Strip the legacy dynamic-slot suffix while preserving the logical handle name. */
export function normalizeWorkflowHandle(handle?: string | null): string | null {
  if (handle == null) return null;
  return String(handle).replace(/__slot_\d+$/, "");
}

function workflowEndpoint(nodeId: string | null | undefined, handle?: string | null): string {
  return `${String(nodeId ?? "")}:${normalizeWorkflowHandle(handle) ?? ""}`;
}

export interface WorkflowState {
  nodes: Node[];
  edges: Edge[];
  selectedNode: Node | null;
  copiedNode: Node | null;
  resultPanelNodeId: string | null;
  isRunning: boolean;
  currentRunId: string | null;
  workflowStatus: WorkflowRunStatus;
  nodeStatuses: Record<string, NodeRunStatus>;
  nodeResults: Record<string, any>;
  nodeErrors: Record<string, NodeErrorDetails>;
  nodeProgress: Record<string, number>;
  exportDirectories: Record<string, WorkflowExportDirectory>;
  operators: any[];
  reactFlowInstance: ReactFlowInstance | null;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  addNode: (type: string, position: { x: number; y: number }, operatorData: any) => void;
  selectNode: (node: Node | null) => void;
  openNodeResult: (nodeId: string) => void;
  closeNodeResult: () => void;
  updateNodeParams: (nodeId: string, params: any) => void;
  setOperators: (ops: any[]) => void;
  setIsRunning: (v: boolean) => void;
  setCurrentRunId: (runId: string | null) => void;
  setWorkflowStatus: (status: WorkflowRunStatus) => void;
  setNodeStatus: (nodeId: string, status: NodeRunStatus) => void;
  setNodeResult: (nodeId: string, result: any) => void;
  setNodeError: (nodeId: string, error: NodeErrorInput | string | null) => void;
  setNodeProgress: (nodeId: string, progress: number) => void;
  setExportDirectory: (nodeId: string, directory: WorkflowExportDirectory) => void;
  setReactFlowInstance: (instance: ReactFlowInstance | null) => void;
  removeEdge: (edgeId: string) => void;
  copySelectedNode: () => void;
  pasteNode: () => void;
  resetExecution: () => void;
  reset: () => void;
}

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNode: null,
  isRunning: false,
  resultPanelNodeId: null,
  currentRunId: null,
  workflowStatus: "pending",
  nodeStatuses: {},
  nodeResults: {},
  nodeErrors: {},
  nodeProgress: {},
  exportDirectories: {},
  operators: [],
  reactFlowInstance: null,
  copiedNode: null as Node | null,

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
    set((state) => {
      const normalizedConnection = {
        ...connection,
        sourceHandle: normalizeWorkflowHandle(connection.sourceHandle),
        targetHandle: normalizeWorkflowHandle(connection.targetHandle),
        type: "custom",
      };
      const sourceEndpoint = workflowEndpoint(connection.source, normalizedConnection.sourceHandle);
      const targetEndpoint = workflowEndpoint(connection.target, normalizedConnection.targetHandle);
      const remainingEdges = state.edges.filter((edge) =>
        workflowEndpoint(edge.source, edge.sourceHandle) !== sourceEndpoint &&
        workflowEndpoint(edge.target, edge.targetHandle) !== targetEndpoint
      );
      return { edges: addEdge(normalizedConnection, remainingEdges) };
    }),

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

  openNodeResult: (nodeId) =>
    set((state) => {
      const node = state.nodes.find((candidate) => candidate.id === nodeId);
      if (!node || state.nodeStatuses[nodeId] !== "completed") return {};
      const operator = state.operators.find((candidate: any) => candidate.id === node.data?.operatorId);
      const category = node.data?.category || operator?.category;
      if (category !== "visualization") return {};
      return { resultPanelNodeId: nodeId };
    }),

  closeNodeResult: () => set({ resultPanelNodeId: null }),

  updateNodeParams: (nodeId, params) =>
    set((state) => ({
      nodes: state.nodes.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, params } } : n)),
      selectedNode: state.selectedNode?.id === nodeId
        ? { ...state.selectedNode, data: { ...state.selectedNode.data, params } }
        : state.selectedNode,
    })),

  setOperators: (ops) => set({ operators: ops }),
  setIsRunning: (v) => set({ isRunning: v }),
  setCurrentRunId: (runId) => set({ currentRunId: runId }),
  setWorkflowStatus: (status) => set({ workflowStatus: status }),

  setNodeStatus: (nodeId, status) =>
    set((state) => ({
      nodeStatuses: { ...state.nodeStatuses, [nodeId]: status },
      ...(state.resultPanelNodeId === nodeId && status !== "completed"
        ? { resultPanelNodeId: null }
        : {}),
    })),

  setNodeResult: (nodeId, result) =>
    set((state) => ({
      nodeResults: { ...state.nodeResults, [nodeId]: result },
    })),

  setNodeError: (nodeId, error) =>
    set((state) => {
      const normalized = normalizeNodeError(nodeId, error);
      if (!normalized) {
        const nodeErrors = { ...state.nodeErrors };
        delete nodeErrors[nodeId];
        return { nodeErrors };
      }
      return { nodeErrors: { ...state.nodeErrors, [nodeId]: normalized } };
    }),

  setNodeProgress: (nodeId, progress) =>
    set((state) => ({
      nodeProgress: { ...state.nodeProgress, [nodeId]: progress },
    })),

  setExportDirectory: (nodeId, directory) =>
    set((state) => ({
      exportDirectories: { ...state.exportDirectories, [nodeId]: directory },
    })),

  setReactFlowInstance: (instance) => set({ reactFlowInstance: instance }),

  removeEdge: (edgeId) =>
    set((state) => ({
      edges: applyEdgeChanges([{ type: "remove", id: edgeId } as EdgeChange], state.edges),
      isDirty: true,
    })),

  copySelectedNode: () => set((state) => ({
    copiedNode: state.selectedNode ? structuredClone(state.selectedNode) : null,
  })),

  pasteNode: () => set((state) => {
    if (!state.copiedNode) return {};
    const source = state.copiedNode;
    const node: Node = {
      ...source,
      id: "node_" + Date.now() + "_" + Math.random().toString(36).slice(2, 7),
      position: { x: source.position.x + 40, y: source.position.y + 40 },
      selected: true,
      data: structuredClone(source.data),
    };
    return { nodes: [...state.nodes, node], selectedNode: node };
  }),

  resetExecution: () =>
    set({
      nodeStatuses: {},
      nodeResults: {},
      nodeErrors: {},
      nodeProgress: {},
      resultPanelNodeId: null,
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
      nodeErrors: {},
      nodeProgress: {},
      exportDirectories: {},
      resultPanelNodeId: null,
      isRunning: false,
      currentRunId: null,
      workflowStatus: "pending",
    }),
}));
