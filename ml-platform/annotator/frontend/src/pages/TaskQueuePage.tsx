import { useEffect, useRef, useState } from 'react'
import { listTasks, Task, TaskQueueQuery } from '../api/tasks'
import './TaskQueuePage.css'

export default function TaskQueuePage({ onOpenTask, onLogout }: { onOpenTask: (id: string, assignmentId?: string) => void; onLogout: () => void }) {
  const [tasks, setTasks] = useState<Task[]>([])
  const [total, setTotal] = useState(0)
  const [error, setError] = useState('')
  const [query, setQuery] = useState<TaskQueueQuery>({ sort: 'due_at', direction: 'asc' })
  const [search, setSearch] = useState('')
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [previousCursors, setPreviousCursors] = useState<Array<string | undefined>>([])
  const generation = useRef(0)

  const load = (nextQuery: TaskQueueQuery = query) => {
    const current = ++generation.current
    setError('')
    setLoading(true)
    setTasks([])
    setNextCursor(null)
    listTasks(nextQuery)
      .then(data => {
        if (current !== generation.current) return
        setTasks(data.items ?? [])
        setTotal(data.total ?? 0)
        setNextCursor(data.next_cursor ?? null)
      })
      .catch(err => { if (current === generation.current) setError(err instanceof Error ? err.message : '任务加载失败') })
      .finally(() => { if (current === generation.current) setLoading(false) })
  }

  useEffect(() => { load(); return () => { generation.current += 1 } }, [])

  const updateQuery = (patch: Partial<TaskQueueQuery>) => {
    const next = { ...query, ...patch, cursor: undefined }
    setPreviousCursors([])
    setQuery(next)
    load(next)
  }

  const applySearch = () => updateQuery({ search: search.trim() || undefined, cursor: undefined })
  const loadNext = () => {
    if (!nextCursor || loading) return
    setPreviousCursors(previous => [...previous, query.cursor])
    const next = { ...query, cursor: nextCursor }
    setQuery(next)
    load(next)
  }
  const loadPrevious = () => {
    if (!previousCursors.length || loading) return
    const next = { ...query, cursor: previousCursors[previousCursors.length - 1] }
    setPreviousCursors(previous => previous.slice(0, -1))
    setQuery(next)
    load(next)
  }

  return <main className="portal-page">
    <header className="topbar"><div><p className="eyebrow">ANNOTATOR PORTAL</p><h1>我的任务</h1></div><button type="button" onClick={onLogout}>退出</button></header>
    <section className="queue">
      <div className="section-heading"><div><h2>已分派任务</h2><p className="muted">仅显示当前账号被授权的任务。</p></div><span className="count">{total}</span></div>
      <div className="queue-controls" aria-label="任务筛选">
        <input aria-label="搜索任务" placeholder="搜索任务 ID" value={search} onChange={event => setSearch(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') applySearch() }} />
        <button type="button" onClick={applySearch}>搜索</button>
        <select aria-label="任务状态" value={query.status ?? ''} onChange={event => updateQuery({ status: event.target.value || undefined })}>
          <option value="">全部任务状态</option><option value="awaiting_annotation">待标注</option><option value="in_progress">进行中</option><option value="awaiting_return">待回传</option><option value="returned_pending_acceptance">待验收</option><option value="completed">已完成</option><option value="failed">失败</option><option value="cancelled">已取消</option>
        </select>
        <select aria-label="指派状态" value={query.assignment_state ?? ''} onChange={event => updateQuery({ assignment_state: event.target.value || undefined })}>
          <option value="">全部指派状态</option><option value="pending">待处理</option><option value="paused">已暂停</option><option value="returned_pending_acceptance">已回传</option><option value="edit_for_return">重新编辑中</option>
        </select>
        <select aria-label="任务排序" value={`${query.sort ?? 'created_at'}:${query.direction ?? 'desc'}`} onChange={event => {
          const [sort, direction] = event.target.value.split(':') as [TaskQueueQuery['sort'], TaskQueueQuery['direction']]
          updateQuery({ sort, direction, cursor: undefined })
        }}>
          <option value="due_at:asc">截止时间优先</option><option value="created_at:desc">最新分派</option><option value="status:asc">按任务状态</option>
        </select>
      </div>
      {error && <div role="alert" className="error">{error}<button type="button" onClick={() => load()}>重试</button></div>}
      {loading && <p role="status">正在加载任务...</p>}
      {tasks.length === 0 && !error && !loading && <p className="empty">暂无已分派任务</p>}
      <div className="task-list">{tasks.map(task => <article className="task-row" key={task.assignment_id ?? task.id}><div><h3>{task.title}</h3><p className="muted">状态：{task.status} · {task.completed_samples ?? 0}/{task.total_samples ?? 0} 条样本</p>{task.assignment_id && <p className="muted">指派 {task.assignment_id}</p>}</div><div className="task-actions"><span className="due">{task.due_at ? new Date(task.due_at).toLocaleDateString() : '未设置截止时间'}</span><button className="primary" onClick={() => onOpenTask(task.id, ...(task.assignment_id ? [task.assignment_id] as const : []))}>打开工作区</button></div></article>)}</div>
      <nav className="queue-controls" aria-label="任务分页">
        <button type="button" disabled={loading || previousCursors.length === 0} onClick={loadPrevious}>上一页</button>
        <button type="button" disabled={loading || !nextCursor} onClick={loadNext}>下一页</button>
      </nav>
    </section>
  </main>
}
