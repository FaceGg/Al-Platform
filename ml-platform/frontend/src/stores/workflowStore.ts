import { create } from 'zustand'
import { Node, Edge, applyNodeChanges, applyEdgeChanges, addEdge, Connection, NodeChange, EdgeChange } from 'reactflow'
import type { ReactFlowInstance } from 'reactflow'

export interface WorkflowState {
  nodes: Node[]
  edges: Edge[]
  selectedNode: Node | null
  isRunning: boolean
  nodeStatuses: Record<string, string>
  nodeResults: Record<string, any>
  operators: any[]
  reactFlowInstance: ReactFlowInstance | null
  setNodes: (nodes: Node[]) => void
  setEdges: (edges: Edge[]) => void
  onNodesChange: (changes: NodeChange[]) => void
  onEdgesChange: (changes: EdgeChange[]) => void
  onConnect: (connection: Connection) => void
  addNode: (type: string, position: { x: number; y: number }, operatorData: any) => void
  selectNode: (node: Node | null) => void
  updateNodeParams: (nodeId: string, params: any) => void
  setOperators: (ops: any[]) => void
  setIsRunning: (v: boolean) => void
  setNodeStatus: (nodeId: string, status: string) => void
  setNodeResult: (nodeId: string, result: any) => void
  setReactFlowInstance: (instance: ReactFlowInstance | null) => void
  reset: () => void
}

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNode: null,
  isRunning: false,
  nodeStatuses: {},
  nodeResults: {},
  operators: [],
  reactFlowInstance: null,

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  onNodesChange: (changes) => set((state) => ({
    nodes: applyNodeChanges(changes, state.nodes),
  })),

  onEdgesChange: (changes) => set((state) => ({
    edges: applyEdgeChanges(changes, state.edges),
  })),

  onConnect: (connection) => set((state) => ({
    edges: addEdge(connection, state.edges),
  })),

  addNode: (type, position, operatorData) => set((state) => {
    const newId = `node_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
    const newNode: Node = {
      id: newId,
      type: 'custom',
      position,
      data: { operatorId: type, label: operatorData.name, category: operatorData.category, params: {} },
    }
    return { nodes: [...state.nodes, newNode] }
  }),

  selectNode: (node) => set({ selectedNode: node }),

  updateNodeParams: (nodeId, params) => set((state) => ({
    nodes: state.nodes.map((n) =>
      n.id === nodeId ? { ...n, data: { ...n.data, params } } : n
    ),
  })),

  setOperators: (ops) => set({ operators: ops }),
  setIsRunning: (v) => set({ isRunning: v }),

  setNodeStatus: (nodeId, status) => set((state) => ({
    nodeStatuses: { ...state.nodeStatuses, [nodeId]: status },
  })),

  setNodeResult: (nodeId, result) => set((state) => ({
    nodeResults: { ...state.nodeResults, [nodeId]: result },
  })),

  setReactFlowInstance: (instance) => set({ reactFlowInstance: instance }),

  reset: () => set({
    nodes: [], edges: [], selectedNode: null,
    nodeStatuses: {}, nodeResults: {}, isRunning: false,
  }),
}))
