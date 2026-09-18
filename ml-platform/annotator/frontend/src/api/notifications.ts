import { request } from './client'

export type Notification = {
  id: string
  title: string
  body: string
  event_type: string
  severity: string
  created_at: string
  read_at: string | null
  target?: { task_id: string; assignment_id: string } | null
}
export type NotificationPage = {
  items: Notification[]
  total: number
  unread_count: number
  next_cursor: string | null
}
export const listNotifications = (cursor?: string, unreadOnly = false) =>
  request<NotificationPage>('/portal/notifications', {
    query: { cursor, unread_only: String(unreadOnly), limit: 50 },
  })
export const markNotificationRead = (id: string) =>
  request<{ id: string; read_at: string }>(`/portal/notifications/${encodeURIComponent(id)}/read`, { method: 'POST' })
