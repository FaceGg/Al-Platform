import { useEffect, useState } from 'react'
import { listTasks, Task } from '../api/tasks'

export default function TaskQueuePage({ onOpenTask, onLogout }: { onOpenTask: (id: string) => void; onLogout: () => void }) {
  const [tasks, setTasks] = useState<Task[]>([]); const [error, setError] = useState('')
  useEffect(() => { listTasks().then(data => setTasks(data.items ?? [])).catch(err => setError(err instanceof Error ? err.message : '任务加载失败')) }, [])
  return <main className="portal-page"><header className="topbar"><div><p className="eyebrow">ANNOTATOR PORTAL</p><h1>我的任务</h1></div><button type="button" onClick={onLogout}>退出</button></header><section className="queue"><div className="section-heading"><div><h2>已分派任务</h2><p className="muted">仅显示当前账号被授权的任务。</p></div><span className="count">{tasks.length}</span></div>{error && <p className="error">{error}</p>}{tasks.length === 0 && !error && <p className="empty">暂无已分派任务</p>}<div className="task-list">{tasks.map(task => <article className="task-row" key={task.id}><div><h3>{task.title}</h3><p className="muted">状态：{task.status} · {(task as Task & { completed_samples?: number }).completed_samples ?? 0}/{(task as Task & { total_samples?: number }).total_samples ?? 0} 条样本</p></div><div className="task-actions"><span className="due">{task.due_at ? new Date(task.due_at).toLocaleDateString() : '未设置截止时间'}</span><button className="primary" onClick={() => onOpenTask(task.id)}>打开工作区</button></div></article>)}</div></section></main>
}
