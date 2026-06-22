import { useCallback } from 'react'
import ReactFlow, { Background, Controls, MiniMap } from 'reactflow'
import type { ReactFlowInstance } from 'reactflow'
import 'reactflow/dist/style.css'
import CustomNode from './CustomNode'
import { useWorkflowStore } from '../../stores/workflowStore'

const nodeTypes = { custom: CustomNode }

export default function WorkflowCanvas() {
  const { nodes, edges, onNodesChange, onEdgesChange, onConnect, selectNode, setReactFlowInstance, nodeStatuses } = useWorkflowStore()

  const onInit = useCallback((instance: ReactFlowInstance) => {
    setReactFlowInstance(instance)
  }, [setReactFlowInstance])

  // Inject status into node data for rendering
  const nodesWithStatus = nodes.map((n) => ({
    ...n,
    data: { ...n.data, status: nodeStatuses[n.id] || 'pending' },
  }))

  return (
    <div style={{ width: '100%', height: '100%' }}>
      <ReactFlow
        nodes={nodesWithStatus}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, node) => selectNode(node)}
        onPaneClick={() => selectNode(null)}
        onInit={onInit}
        nodeTypes={nodeTypes}
        fitView
        deleteKeyCode={['Backspace', 'Delete']}
      >
        <Background />
        <Controls />
        <MiniMap nodeStrokeWidth={3} />
      </ReactFlow>
    </div>
  )
}
