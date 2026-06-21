import { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'

function CustomNode({ data, selected }: NodeProps) {
  const statusColors: Record<string, string> = {
    completed: '#52c41a',
    running: '#1890ff',
    failed: '#ff4d4f',
    pending: '#d9d9d9',
  }
  const borderColor = selected ? '#1890ff' : (statusColors[data.status] || '#d9d9d9')

  return (
    <div style={{
      padding: '8px 14px',
      borderRadius: 8,
      border: `2px solid ${borderColor}`,
      background: '#fff',
      minWidth: 130,
      boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
      fontSize: 13,
    }}>
      <Handle type="target" position={Position.Left} style={{ width: 10, height: 10 }} />
      <div style={{ fontWeight: 600, marginBottom: 2 }}>{data.label || data.operatorId}</div>
      <div style={{ fontSize: 11, color: '#888' }}>{data.category}</div>
      <Handle type="source" position={Position.Right} style={{ width: 10, height: 10 }} />
    </div>
  )
}

export default memo(CustomNode)
