import { useEffect, useRef, useState } from 'react'
import { listTasks, Task, TaskQueueQuery } from '../api/tasks'
import FeedbackBanner from '../components/FeedbackBanner'
import TaskCard, { isFeedbackTask } from '../components/TaskCard'

type User = { subject_id?: string | null; username: string }

export default function TaskQueuePage({
  user,
  onOpenTask,
}: {
  user?: User
  onOpenTask: (id: string, assignmentId?: string) => void
}) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [query, setQuery] = useState<TaskQueueQuery>({ sort: 'due_at', direction: 'asc' })
  const [search, setSearch] = useState('')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [previousCursors, setPreviousCursors] = useState<Array<string | undefined>>([])
  const [highlightKey, setHighlightKey] = useState('')
  const generation = useRef(0)

  const load = (nextQuery: TaskQueueQuery = query) => {
    const current = ++generation.current
    setError('')
    setLoading(true)
    setTasks([])
    setNextCursor(null)
    listTasks(nextQuery)
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
  }, [])

  const updateQuery = (patch: Partial<TaskQueueQuery>) => {
    const next = { ...query, ...patch, cursor: undefined }
    setPreviousCursors([])
    setQuery(next)
    load(next)
  }

  const applySearch = () =>
    updateQuery({ search: search.trim() || undefined, cursor: undefined })

  const loadNext = () => {
    if (!nextCursor || loading) return
    setPreviousCursors((previous) => [...previous, query.cursor])
    const next = { ...query, cursor: nextCursor }
    setQuery(next)
    load(next)
  }

  const loadPrevious = () => {
    if (!previousCursors.length || loading) return
    const next = { ...query, cursor: previousCursors[previousCursors.length - 1] }
    setPreviousCursors((previous) => previous.slice(0, -1))
    setQuery(next)
    load(next)
  }

  const feedbackTasks = tasks.filter(isFeedbackTask)

  const locateFeedback = () => {
    const first = feedbackTasks[0]
    if (!first) return
    const key = first.assignment_id ?? first.id
    setHighlightKey(key)
    document
      .getElementById(`task-card-${key}`)
      ?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  }

  // Compute stat counts from visible tasks
  const awaitingCount = tasks.filter(
    (t) => t.status === 'awaiting_annotation' || t.status === 'assigned',
  ).length
  const inProgressCount = tasks.filter((t) => t.status === 'in_progress').length
  const returnCount = tasks.filter(
    (t) =>
      t.status === 'awaiting_return' ||
      t.status === 'returned_pending_acceptance' ||
      t.state === 'edit_for_return',
  ).length
  const overdueCount = tasks.filter((t) => {
    if (!t.due_at) return false
    const due = new Date(t.due_at)
    return due < new Date() && !['completed', 'cancelled', 'accepted', 'archived'].includes(t.status)
  }).length

  const displayName = user?.username ?? '用户'

  return (
    <main className="app-main">
      <div className="queue-header">
        <h2>我的任务</h2>
        <p className="muted">你好，{displayName}。以下是当前分配给你的标注任务。</p>
      </div>

      <div className="queue-stats">
        <div className="stat-card awaiting">
          <div className="stat-label">待标注</div>
          <div className="stat-value">{awaitingCount}</div>
          <div className="stat-delta">等待开始</div>
        </div>
        <div className="stat-card progress">
          <div className="stat-label">进行中</div>
          <div className="stat-value">{inProgressCount}</div>
          <div className="stat-delta">当前活跃任务</div>
        </div>
        <div className="stat-card return">
          <div className="stat-label">待回传</div>
          <div className="stat-value">{returnCount}</div>
          <div className="stat-delta">需提交审核</div>
        </div>
        <div className="stat-card overdue">
          <div className="stat-label">已逾期</div>
          <div className="stat-value">{overdueCount}</div>
          <div className="stat-delta down">请优先处理</div>
        </div>
      </div>

      <FeedbackBanner count={feedbackTasks.length} onLocate={locateFeedback} />

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
            placeholder="搜索任务名称、批次号或项目..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') applySearch()
            }}
          />
        </div>
        <button type="button" onClick={applySearch}>搜索</button>
        <select
          aria-label="任务状态"
          value={query.status ?? ''}
          onChange={(event) =>
            updateQuery({ status: event.target.value || undefined })
          }
        >
          <option value="">全部状态</option>
          <option value="awaiting_annotation">待标注</option>
          <option value="in_progress">进行中</option>
          <option value="awaiting_return">待回传</option>
          <option value="returned_pending_acceptance">待验收</option>
          <option value="accepted">已验收</option>
          <option value="completed">已完成</option>
          <option value="failed">失败</option>
          <option value="cancelled">已取消</option>
        </select>
        <select
          aria-label="指派状态"
          value={query.assignment_state ?? ''}
          onChange={(event) =>
            updateQuery({ assignment_state: event.target.value || undefined })
          }
        >
          <option value="">全部指派状态</option>
          <option value="pending">待处理</option>
          <option value="paused">已暂停</option>
          <option value="returned_pending_acceptance">已回传</option>
          <option value="edit_for_return">重新编辑中</option>
        </select>
        <select
          aria-label="任务排序"
          value={`${query.sort ?? 'created_at'}:${query.direction ?? 'desc'}`}
          onChange={(event) => {
            const [sort, direction] = event.target.value.split(':') as [
              TaskQueueQuery['sort'],
              TaskQueueQuery['direction'],
            ]
            updateQuery({ sort, direction, cursor: undefined })
          }}
        >
          <option value="due_at:asc">截止时间优先</option>
          <option value="created_at:desc">最新分派</option>
          <option value="status:asc">按任务状态</option>
        </select>
      </div>

      {error && (
        <div role="alert" className="error">
          {error}
          <button type="button" onClick={() => load()}>
            重试
          </button>
        </div>
      )}
      {loading && (
        <p role="status" className="muted">
          正在加载任务...
        </p>
      )}
      {tasks.length === 0 && !error && !loading && (
        <div className="empty-state">暂无已分派任务</div>
      )}

      <div className="queue-list">
        {tasks.map((task) => {
          const key = task.assignment_id ?? task.id
          return (
            <TaskCard
              key={key}
              task={task}
              cardId={`task-card-${key}`}
              highlighted={highlightKey === key}
              onOpenTask={onOpenTask}
            />
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
    </main>
  )
}
