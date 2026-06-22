import { memo } from 'react'
import { Handle, Position, NodeProps } from 'reactflow'
import { Progress, Tag } from 'antd'
import { LoadingOutlined, CheckCircleFilled, CloseCircleFilled, PlayCircleOutlined } from '@ant-design/icons'

const STATUS_CONFIG: Record<string, { bg: string; border: string; icon: React.ReactNode; label: string; tagColor: string }> = {
  pending:  { bg: '#fff7e6', border: '#fa8c16', icon: <PlayCircleOutlined style={{ color: '#fa8c16' }} />, label: '待运行', tagColor: 'orange' },
  running:  { bg: '#e6f7ff', border: '#1890ff', icon: <LoadingOutlined style={{ color: '#1890ff' }} spin />, label: '运行中', tagColor: 'processing' },
  completed:{ bg: '#f6ffed', border: '#52c41a', icon: <CheckCircleFilled style={{ color: '#52c41a' }} />, label: '已完成', tagColor: 'success' },
  failed:   { bg: '#fff2f0', border: '#ff4d4f', icon: <CloseCircleFilled style={{ color: '#ff4d4f' }} />, label: '失败', tagColor: 'error' },
}

function CustomNode({ data, selected }: NodeProps) {
  const status = (data.status as string) || 'pending'
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending

  return (
    <div style={{
      padding: '6px 14px 8px',
      borderRadius: 8,
      border: `2px solid ${selected ? '#1890ff' : cfg.border}`,
      background: cfg.bg,
      minWidth: 150,
      maxWidth: 200,
      boxShadow: selected ? '0 0 0 2px rgba(24,144,255,0.3)' : '0 1px 3px rgba(0,0,0,0.1)',
      fontSize: 13,
      transition: 'all 0.2s ease',
    }}>
      <Handle type="target" position={Position.Left} style={{ width: 10, height: 10, background: cfg.border }} />

      {/* Header: icon + label */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span style={{ fontSize: 14 }}>{cfg.icon}</span>
        <span style={{ fontWeight: 600, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {data.label || data.operatorId}
        </span>
      </div>

      {/* Status tag */}
      <Tag color={cfg.tagColor} style={{ fontSize: 10, lineHeight: '14px', marginBottom: 4 }}>
        {cfg.label}
      </Tag>

      {/* Progress bar when running */}
      {status === 'running' && (
        <Progress percent={50} size="small" status="active" showInfo={false} style={{ marginTop: 2 }} />
      )}

      <Handle type="source" position={Position.Right} style={{ width: 10, height: 10, background: cfg.border }} />
    </div>
  )
}

export default memo(CustomNode)
