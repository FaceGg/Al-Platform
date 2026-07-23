import { useCallback, useEffect, useMemo } from "react";
import ReactFlow, { Background, Controls, MiniMap } from "reactflow";
import type { ReactFlowInstance } from "reactflow";
import "reactflow/dist/style.css";
import CustomNode from "./CustomNode";
import CustomEdge from "./CustomEdge";
import { useWorkflowStore } from "../../stores/workflowStore";

const nodeTypes = { custom: CustomNode };
const edgeTypes = { custom: CustomEdge };

export default function WorkflowCanvas() {
  const {
    nodes, edges, onNodesChange, onEdgesChange, onConnect,
    selectNode, setReactFlowInstance, nodeStatuses, nodeProgress,
    operators,
    copySelectedNode, pasteNode,
  } = useWorkflowStore();

  const onInit = useCallback(
    (instance: ReactFlowInstance) => setReactFlowInstance(instance),
    [setReactFlowInstance]
  );

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, [contenteditable='true']")) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c") {
        event.preventDefault();
        copySelectedNode();
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") {
        event.preventDefault();
        pasteNode();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [copySelectedNode, pasteNode]);

  // ── Operator metadata lookup (guarantees ports even when data.inputs is empty) ──
  const opMeta = useMemo(() => {
    const map: Record<string, { inputs: any[]; outputs: any[]; category: string }> = {};
    for (const op of operators) {
      map[op.id] = {
        inputs: op.inputs || [],
        outputs: op.outputs || [],
        category: op.category || "utility",
      };
    }
    return map;
  }, [operators]);

  const nodesWithStatus = nodes.map((n) => {
    const opId = n.data.operatorId as string || "";
    const meta = opMeta[opId] || { inputs: [], outputs: [], category: "utility" };

    // Prefer operator metadata for inputs/outputs, fall back to data
    const totalInputs = (n.data.inputs as any[])?.length ? (n.data.inputs as any[]) : meta.inputs;
    const totalOutputs = (n.data.outputs as any[])?.length ? (n.data.outputs as any[]) : meta.outputs;
    return {
      ...n,
      data: {
        ...n.data,
        status: nodeStatuses[n.id] || "pending",
        progress: nodeProgress[n.id],
        nodeId: n.id,
        category: n.data.category || meta.category,
        // Use operator metadata for port definitions
        inputs: totalInputs,
        outputs: totalOutputs,
        totalInputs: totalInputs.length,
        totalOutputs: totalOutputs.length,
      },
    };
  });

  // Convert edges to custom type
  const edgesWithType = edges.map((e) => ({ ...e, type: e.type || "custom" }));

  return (
    <div className="workflow-canvas-surface">
      <ReactFlow
        className="workflow-flow"
        nodes={nodesWithStatus}
        edges={edgesWithType}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, node) => selectNode(node)}
        onPaneClick={() => selectNode(null)}
        onInit={onInit}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        deleteKeyCode={["Backspace", "Delete"]}
        snapToGrid
        snapGrid={[15, 15]}
        defaultEdgeOptions={{
          style: { stroke: "var(--workflow-edge)", strokeWidth: 2 },
          animated: false,
        }}
      >
        <Background color="var(--workflow-grid)" gap={24} />
        <Controls className="workflow-flow__controls" />
        <MiniMap
          className="workflow-flow__minimap"
          nodeStrokeWidth={2}
          maskColor="var(--workflow-minimap-mask)"
        />
      </ReactFlow>
    </div>
  );
}
