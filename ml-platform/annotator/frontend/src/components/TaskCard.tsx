import { Task } from '../api/tasks'

const statusLabels: Record<string, string> = {
  awaiting_annotation: '待标注',
  in_progress: '进行中',
  awaiting_return: '待回传',
  returned_pending_acceptance: '待验收',
  accepted: '已验收',
  completed: '已完成',
  archived: '已归档',
  failed: '失败',
  cancelled: '已取消',
  assigned: '已分派',
}

export const FEEDBACK_STATES = ['returned_pending_acceptance', 'edit_for_return']

// 终态任务（已验收/已归档/已完成/已取消/失败）不再属于质检反馈：验收或归档后
// assignment.state 会停留在 returned_pending_acceptance，但任务已锁定，不应提示重做。
export const TERMINAL_STATUSES = ['accepted', 'completed', 'archived', 'cancelled', 'failed']

export const isFeedbackTask = (task: Task) =>
  !TERMINAL_STATUSES.includes(task.status) &&
  (FEEDBACK_STATES.includes(task.state ?? '') || task.status === 'returned_pending_acceptance')

export default function TaskCard({
  task,
  highlighted = false,
  cardId,
  onOpenTask,
}: {
  task: Task
  highlighted?: boolean
  cardId?: string
  onOpenTask: (id: string, assignmentId?: string) => void
}) {
  const hasProgress = task.completed_samples !== undefined && task.total_samples !== undefined && task.total_samples > 0
  const viewOnly = ['accepted', 'archived'].includes(task.status)
  const rework = !TERMINAL_STATUSES.includes(task.status) && FEEDBACK_STATES.includes(task.state ?? '')

  return (
    <article className={`task-card${highlighted ? ' highlighted' : ''}`} id={cardId}>
      <div className="task-main">
        <div className="task-title">
          <span className="task-name">{task.title}</span>
          <span className={`tag tag-${task.status}`}>{statusLabels[task.status] ?? task.status}</span>
          {rework && <span className="rework-badge">需重做</span>}
        </div>
        <div className="task-meta">
          {hasProgress && <span>我的进度 {task.completed_samples}/{task.total_samples}</span>}
          <span className="due">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
            {task.due_at ? `截止 ${new Date(task.due_at).toLocaleDateString()}` : '未设置截止时间'}
          </span>
          {task.assignment_id && <span className="muted">指派编号 {task.assignment_id}</span>}
        </div>
      </div>
      <div className="task-actions">
        <button className="primary" onClick={() => onOpenTask(task.id, ...(task.assignment_id ? [task.assignment_id] as const : []))}>{viewOnly ? '查看任务' : '继续标注'}</button>
      </div>
    </article>
  )
}
