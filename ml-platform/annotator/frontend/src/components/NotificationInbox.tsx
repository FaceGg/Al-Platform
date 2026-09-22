import { useCallback, useEffect, useRef, useState } from 'react'
import { listNotifications, markNotificationRead, Notification } from '../api/notifications'
import './NotificationInbox.css'

const titles: Record<string, string> = {
  'annotation_comment.replied': '批注有新回复',
  'annotation_comment.status_changed': '批注处理状态更新',
  'annotation_return.accepted': '回传已通过验收',
  'annotation_return.returned_for_changes': '回传已退回修改',
}

export default function NotificationInbox({ onOpenTask }: { onOpenTask?: (taskId: string, assignmentId: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [items, setItems] = useState<Notification[]>([])
  const [unread, setUnread] = useState(0)
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const busy = useRef(false)
  const generation = useRef(0)
  const pages = useRef(1)

  const load = useCallback(async (next?: string, refresh = false) => {
    if (busy.current) return
    busy.current = true
    const current = ++generation.current
    setLoading(true)
    setError('')
    try {
      let pageCursor = next
      let loaded = 0
      const rows: Notification[] = []
      let count = 0
      do {
        const result = await listNotifications(pageCursor, unreadOnly)
        if (current !== generation.current) return
        rows.push(...result.items)
        count = result.unread_count
        pageCursor = result.next_cursor ?? undefined
        loaded += 1
      } while (refresh && pageCursor && loaded < pages.current)
      setItems(previous => Array.from(new Map(
        [...(next ? previous : []), ...rows].map(item => [item.id, item]),
      ).values()))
      setUnread(count)
      setCursor(pageCursor ?? null)
      pages.current = next ? pages.current + 1 : loaded
    } catch (err) {
      if (current === generation.current) setError(err instanceof Error ? err.message : '通知加载失败')
    } finally {
      if (current === generation.current) {
        busy.current = false
        setLoading(false)
      }
    }
  }, [unreadOnly])

  useEffect(() => {
    busy.current = false
    pages.current = 1
    setItems([])
    setCursor(null)
    void load()
    const refresh = () => {
      if (document.visibilityState !== 'hidden') void load(undefined, true)
    }
    const timer = window.setInterval(refresh, 30_000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      generation.current += 1
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [load])

  async function markRead(item: Notification) {
    if (busy.current || item.read_at) return
    busy.current = true
    const current = ++generation.current
    setLoading(true)
    setError('')
    try {
      const result = await markNotificationRead(item.id)
      if (current !== generation.current) return
      setItems(previous => previous.map(row => row.id === item.id ? { ...row, read_at: result.read_at } : row))
      setUnread(value => Math.max(0, value - 1))
      if (unreadOnly) {
        // Restart a filtered page because its cursor might now be read.
        busy.current = false
        await load()
      }
    } catch (err) {
      if (current === generation.current) setError(err instanceof Error ? err.message : '标记已读失败')
    } finally {
      if (current === generation.current) {
        busy.current = false
        setLoading(false)
      }
    }
  }

  return <section className="notification-inbox" aria-label="站内通知">
    <button type="button" className="notify-bell" aria-expanded={expanded} aria-controls="portal-notices"
      aria-label={`站内通知（${unread} 条未读）`} onClick={() => setExpanded(value => !value)}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 0 1-3.46 0" />
      </svg>
      {unread > 0 && <span className="notify-badge" aria-hidden="true">{unread}</span>}
    </button>
    {expanded && <div id="portal-notices" className="notify-dropdown">
      <div className="notification-controls">
        <h2>站内通知</h2>
        <label className="check"><input type="checkbox" checked={unreadOnly} onChange={event => setUnreadOnly(event.target.checked)} />仅未读</label>
        <button type="button" disabled={loading} onClick={() => { void load(undefined, true) }}>刷新通知</button>
      </div>
      {error && <p role="alert" className="error">{error}<button type="button" disabled={loading} onClick={() => { void load(undefined, true) }}>重试加载通知</button></p>}
      {loading && <p role="status">通知加载中...</p>}
      {!loading && !error && !items.length && <p>暂无通知</p>}
      <ul className="notification-list">
        {items.map(item => <li key={item.id}>
          <div><h3>{titles[item.event_type] ?? item.title}</h3><p>{item.body}</p>
            <time dateTime={item.created_at}>{new Date(item.created_at.endsWith('Z') ? item.created_at : `${item.created_at}Z`).toLocaleString()}</time>
          </div>
          <div className="notification-actions">
            {item.target && onOpenTask && <button type="button" onClick={() => onOpenTask(item.target!.task_id, item.target!.assignment_id)}>打开任务</button>}
            {item.read_at ? <span className="muted">已读</span>
              : <button type="button" disabled={loading} onClick={() => { void markRead(item) }}>标记已读</button>}
          </div>
        </li>)}
      </ul>
      {cursor && <button type="button" disabled={loading} onClick={() => { void load(cursor) }}>加载更多通知</button>}
    </div>}
  </section>
}
