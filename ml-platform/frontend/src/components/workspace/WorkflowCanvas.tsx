import { useCallback, useMemo } from "react";
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
  } = useWorkflowStore();

  const onInit = useCallback(
    (instance: ReactFlowInstance) => setReactFlowInstance(instance),
    [setReactFlowInstance]
  );

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

  // Compute connection counts per node for dynamic port display
  const inputCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of edges) {
      counts[e.target] = (counts[e.target] || 0) + 1;
    }
    return counts;
  }, [edges]);

  const outputCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const e of edges) {
      counts[e.source] = (counts[e.source] || 0) + 1;
    }
    return counts;
  }, [edges]);

  const nodesWithStatus = nodes.map((n) => {
    const opId = n.data.operatorId as string || "";
    const meta = opMeta[opId] || { inputs: [], outputs: [], category: "utility" };

    // Prefer operator metadata for inputs/outputs, fall back to data
    const totalInputs = (n.data.inputs as any[])?.length ? (n.data.inputs as any[]) : meta.inputs;
    const totalOutputs = (n.data.outputs as any[])?.length ? (n.data.outputs as any[]) : meta.outputs;
    const usedInputs = inputCounts[n.id] || 0;
    const usedOutputs = outputCounts[n.id] || 0;

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
        // Show 1 + usedPorts, capped by total available
        visibleInputs: Math.min(totalInputs.length, Math.max(1, usedInputs + (totalInputs.length > 0 ? 1 : 0))),
        visibleOutputs: Math.min(totalOutputs.length, Math.max(1, usedOutputs + (totalOutputs.length > 0 ? 1 : 0))),
        totalInputs: totalInputs.length,
        totalOutputs: totalOutputs.length,
      },
    };
  });

  // Convert edges to custom type
  const edgesWithType = edges.map((e) => ({ ...e, type: e.type || "custom" }));

  return (
    <div style={{ width: "100%", height: "100%" }}>
      <ReactFlow
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
          style: { stroke: "#b1b1b7", strokeWidth: 2 },
          animated: false,
        }}
      >
        <Background color="#e8e8e8" gap={20} />
        <Controls style={{ borderRadius: 8 }} />
        <MiniMap
          nodeStrokeWidth={3}
          style={{ borderRadius: 8 }}
          maskColor="rgba(0,0,0,0.08)"
        />
      </ReactFlow>
    </div>
  );
}
