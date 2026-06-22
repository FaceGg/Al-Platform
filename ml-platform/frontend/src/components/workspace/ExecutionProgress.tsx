import { Progress, Tag } from 'antd'
import { useI18n } from '../../i18n'
import { useWorkflowStore } from '../../stores/workflowStore'

export default function ExecutionProgress() {
  const { t } = useI18n()
  const { isRunning, nodeStatuses, nodes } = useWorkflowStore()

  // Filter out internal markers like __wf__
  const nodeEntries = Object.entries(nodeStatuses).filter(([id]) => !id.startsWith('__'))
  const realTotal = nodes.length  // Actual nodes on canvas

  if (nodeEntries.length === 0 && !isRunning) return null

  const completed = nodeEntries.filter(([, s]) => s === 'completed').length
  const running = nodeEntries.filter(([, s]) => s === 'running').length
  const failed = nodeEntries.filter(([, s]) => s === 'failed').length
  const total = realTotal || nodeEntries.length
  const percent = total > 0 ? Math.round(((completed + failed) / total) * 100) : 0

  return (
    <div style={{
      position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)',
      background: '#fff', padding: '8px 16px', borderRadius: 8, boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
      zIndex: 10, minWidth: 300,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12 }}>{t.workspace.run_progress || '执行进度'}</span>
        <span style={{ fontSize: 12 }}>{completed + failed}/{total} 节点</span>
      </div>
      <Progress
        percent={percent}
        size="small"
        status={failed > 0 && !isRunning ? 'exception' : isRunning ? 'active' : 'success'}
      />
      {running > 0 && (
        <div style={{ fontSize: 11, color: '#1890ff', marginTop: 2 }}>
          运行中: {running} 个节点
        </div>
      )}
      <div style={{ marginTop: 4 }}>
        {nodeEntries.slice(0, 5).map(([id, status]) => (
          <Tag key={id} color={
            status === 'completed' ? 'success' :
            status === 'running' ? 'processing' :
            status === 'failed' ? 'error' : 'default'
          }>
            {id.slice(0, 8)}
          </Tag>
        ))}
      </div>
    </div>
  )
}
