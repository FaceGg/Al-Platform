import { useEffect, useRef, useState } from 'react'
import { acceptAdminTask, AdminTaskListItem, listAdminTasks, returnAdminTask } from '../api/admin'

const statusLabels: Record<string, string> = {
  awaiting_annotation: '待标注',
  in_progress: '进行中',
  awaiting_return: '待回传',
  returned_pending_acceptance: '待验收',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  assigned: '已分派',
}

const returnStateLabels: Record<string, string> = {
  pending: '待验收',
  accepted: '已验收',
  returned_for_changes: '已退回',
}

function returnReviewState(task: AdminTaskListItem): { label: string; className: string; reviewable: boolean; disabledReason: string } {
  if (!task.pending_return_batch_id) {
    return {
      label: task.return_state ? (returnStateLabels[task.return_state] ?? task.return_state) : '未回传',
      className: task.return_state ? `is-${task.return_state}` : 'is-none',
      reviewable: false,
      disabledReason: '任务未回传，不能验收/退回/批注',
    }
  }
  if (task.return_operation_state === 'completed') {
    return { label: '待验收', className: 'is-pending', reviewable: true, disabledReason: '' }
  }
  if (task.return_operation_state === 'failed') {
    const suffix = task.return_operation_error_code ? `（${task.return_operation_error_code}）` : ''
    return {
      label: '回传校验失败',
      className: 'is-failed',
      reviewable: false,
      disabledReason: `回传校验失败${suffix}，不能验收/退回/批注`,
    }
  }
  return {
    label: '回传校验中',
    className: 'is-processing',
    reviewable: false,
    disabledReason: '回传校验尚未完成，不能验收/退回/批注',
  }
}

const modeLabels: Record<string, string> = {
  manual: '人工标注',
  auto: '自动标注',
}

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

type User = { username: string }

export default function AdminQueuePage({
  user,
  onOpenTask,
}: {
  user?: User
  onOpenTask: (id: string) => void
}) {
  const [tasks, setTasks] = useState<AdminTaskListItem[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [previousCursors, setPreviousCursors] = useState<Array<string | undefined>>([])
  const [acceptTarget, setAcceptTarget] = useState<AdminTaskListItem | null>(null)
  const [accepting, setAccepting] = useState(false)
  const [returnTarget, setReturnTarget] = useState<AdminTaskListItem | null>(null)
  const [returnReason, setReturnReason] = useState('')
  const [returning, setReturning] = useState(false)
  const generation = useRef(0)

  const load = (cursor?: string) => {
    const current = ++generation.current
    setError('')
    setLoading(true)
    setTasks([])
    setNextCursor(null)
    listAdminTasks({ cursor, search: appliedSearch || undefined })
      .then((data) => {
        if (current !== generation.current) return
        setTasks(data.items ?? [])
        setTotal(data.total ?? 0)
        setNextCursor(data.next_cursor ?? null)
      })
      .catch((err) => {
        if (current === generation.current)
          setError(err instanceof Error ? err.message : '任务加载失败')
      })
      .finally(() => {
        if (current === generation.current) setLoading(false)
      })
  }

  useEffect(() => {
    load()
    return () => {
      generation.current += 1
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedSearch])

  const applySearch = () => setAppliedSearch(search.trim())

  const loadNext = () => {
    if (!nextCursor || loading) return
    setPreviousCursors((previous) => [...previous, undefined])
    load(nextCursor)
  }

  const loadPrevious = () => {
    if (!previousCursors.length || loading) return
    const cursor = previousCursors[previousCursors.length - 1]
    setPreviousCursors((previous) => previous.slice(0, -1))
    load(cursor)
  }

  const confirmAccept = async () => {
    if (!acceptTarget || accepting) return
    setAccepting(true)
    setError('')
    try {
      const result = await acceptAdminTask(acceptTarget.id)
      setMessage(`已验收「${acceptTarget.title}」，生成数据版本 v${result.version}`)
      setAcceptTarget(null)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '验收失败')
    } finally {
      setAccepting(false)
    }
  }

  const confirmReturn = async () => {
    if (!returnTarget || returning) return
    const reason = returnReason.trim()
    if (!reason) return
    setReturning(true)
    setError('')
    try {
      await returnAdminTask(returnTarget.id, reason)
      setMessage(`已退回「${returnTarget.title}」，等待标注员修改后重新回传`)
      setReturnTarget(null)
      setReturnReason('')
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '退回失败')
    } finally {
      setReturning(false)
    }
  }

  const displayName = user?.username ?? '管理员'

  return (
    <main className="app-main">
      <div className="queue-header">
        <h2>评审任务</h2>
        <p className="muted">你好，{displayName}。以下是你创建的标注任务，可对已回传的任务进行验收、退回或批注。</p>
      </div>

      <div className="queue-toolbar" aria-label="任务筛选">
        <div className="search-wrap">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            type="search"
            aria-label="搜索任务"
            placeholder="搜索任务名称或任务 ID..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') applySearch()
            }}
          />
        </div>
        <button type="button" onClick={applySearch}>搜索</button>
      </div>

      {message && (
        <p role="status" className="success-note">{message}</p>
      )}
      {error && (
        <div role="alert" className="error">
          {error}
          <button type="button" onClick={() => load()}>重试</button>
        </div>
      )}
      {loading && (
        <p role="status" className="muted">正在加载任务...</p>
      )}
      {tasks.length === 0 && !error && !loading && (
        <div className="empty-state">暂无创建的标注任务</div>
      )}

      <div className="queue-list">
        {tasks.map((task) => {
          const review = returnReviewState(task)
          return (
            <article className="task-card admin-task-card" key={task.id} id={`admin-task-${task.id}`}>
              <div className="task-main">
                <div className="task-title">
                  <span className="task-name">{task.title}</span>
                  <span className={`tag tag-${task.status}`}>{statusLabels[task.status] ?? task.status}</span>
                  <span className={`admin-return-tag ${review.className}`}>
                    {review.label}
                  </span>
                </div>
                <div className="task-meta">
                  <span>{modeLabels[task.mode] ?? task.mode}</span>
                  <span>样本 {task.sample_count}</span>
                  {typeof task.completed_samples === 'number' && (
                    <span>进度 {task.completed_samples}/{task.sample_count}</span>
                  )}
                  <span>创建于 {formatDateTime(task.created_at)}</span>
                  {task.project_name && <span className="muted">项目 {task.project_name}</span>}
                  {task.annotator_name && <span className="muted">标注员 {task.annotator_name}</span>}
                </div>
              </div>
              <div className="task-actions admin-task-actions">
                <button
                  type="button"
                  className="primary"
                  disabled={!review.reviewable}
                  title={review.reviewable ? '验收该回传批次并生成数据版本' : review.disabledReason}
                  onClick={() => setAcceptTarget(task)}
                >
                  合格验收
                </button>
                <button
                  type="button"
                  disabled={!review.reviewable}
                  title={review.reviewable ? '退回该回传批次，要求标注员修改' : review.disabledReason}
                  onClick={() => {
                    setReturnReason('')
                    setReturnTarget(task)
                  }}
                >
                  退回修改
                </button>
                <button
                  type="button"
                  disabled={!review.reviewable}
                  title={review.reviewable ? '逐条浏览样本与标注结果并添加批注' : review.disabledReason}
                  onClick={() => onOpenTask(task.id)}
                >
                  批注
                </button>
              </div>
            </article>
          )
        })}
      </div>

      {total > 0 && (
        <div className="queue-toolbar" style={{ justifyContent: 'center', marginTop: '16px' }}>
          <button
            type="button"
            disabled={loading || previousCursors.length === 0}
            onClick={loadPrevious}
          >
            上一页
          </button>
          <span className="muted">共 {total} 条</span>
          <button type="button" disabled={loading || !nextCursor} onClick={loadNext}>
            下一页
          </button>
        </div>
      )}

      {acceptTarget && (
        <div className="dialog" role="presentation" onClick={() => { if (!accepting) setAcceptTarget(null) }}>
          <section role="dialog" aria-modal="true" aria-labelledby="admin-accept-title" onClick={(event) => event.stopPropagation()}>
            <h2 id="admin-accept-title">确认合格验收</h2>
            <p className="muted">
              将验收「{acceptTarget.title}」的回传批次，合并生成新的数据版本。该操作完成后任务进入已完成状态。
            </p>
            <div className="dialog-actions">
              <button type="button" disabled={accepting} onClick={() => setAcceptTarget(null)}>取消</button>
              <button type="button" className="primary" disabled={accepting} onClick={() => { void confirmAccept() }}>
                {accepting ? '验收中...' : '确认验收'}
              </button>
            </div>
          </section>
        </div>
      )}

      {returnTarget && (
        <div className="dialog" role="presentation" onClick={() => { if (!returning) setReturnTarget(null) }}>
          <section role="dialog" aria-modal="true" aria-labelledby="admin-return-title" onClick={(event) => event.stopPropagation()}>
            <h2 id="admin-return-title">退回修改</h2>
            <p className="muted">将「{returnTarget.title}」的回传批次退回，标注员需修改后重新回传。</p>
            <label className="admin-return-reason">
              退回原因（必填）
              <textarea
                aria-label="退回原因"
                required
                rows={4}
                maxLength={2000}
                placeholder="请说明需要修改的内容..."
                value={returnReason}
                onChange={(event) => setReturnReason(event.target.value)}
              />
            </label>
            <div className="dialog-actions">
              <button type="button" disabled={returning} onClick={() => setReturnTarget(null)}>取消</button>
              <button
                type="button"
                className="primary"
                disabled={returning || !returnReason.trim()}
                onClick={() => { void confirmReturn() }}
              >
                {returning ? '退回中...' : '确认退回'}
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  )
}
