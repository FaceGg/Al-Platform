import { Progress, Tag } from 'antd'
import { useI18n } from '../../i18n'
import { useWorkflowStore } from '../../stores/workflowStore'

export default function ExecutionProgress() {
  const { t } = useI18n()
  const { isRunning, nodeStatuses } = useWorkflowStore()
  const entries = Object.entries(nodeStatuses)

  if (entries.length === 0 && !isRunning) return null

  const completed = entries.filter(([_, s]) => s === 'completed').length
  const total = entries.length
  const percent = total > 0 ? Math.round((completed / total) * 100) : 0

  return (
    <div style={{
      position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)',
      background: '#fff', padding: '8px 16px', borderRadius: 8, boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
      zIndex: 10, minWidth: 300,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 12 }}>{t.workspace.run_progress || '执行进度'}</span>
        <span style={{ fontSize: 12 }}>{completed}/{total} {t.workspace.nodes || '节点'}</span>
      </div>
      <Progress percent={percent} size='small' status={isRunning ? 'active' : 'success'} />
      <div style={{ marginTop: 4 }}>
        {entries.slice(0, 5).map(([id, status]) => (
          <Tag key={id} color={status === 'completed' ? 'success' : status === 'running' ? 'processing' : status === 'failed' ? 'error' : 'default'}>
            {id.slice(0, 8)}
          </Tag>
        ))}
      </div>
    </div>
  )
}