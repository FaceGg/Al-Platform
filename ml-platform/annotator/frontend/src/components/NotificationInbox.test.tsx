import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import NotificationInbox from './NotificationInbox'
import * as api from '../api/notifications'

vi.mock('../api/notifications', () => ({
  listNotifications: vi.fn(), markNotificationRead: vi.fn(),
}))
const notice = {
  id: 'n1', title: '批注有回复', body: '管理员回复了批注', event_type: 'annotation_comment.replied',
  severity: 'info', created_at: '2026-09-16T08:00:00', read_at: null,
}
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(api.listNotifications).mockResolvedValue({ items: [notice], total: 1, unread_count: 1, next_cursor: null })
  vi.mocked(api.markNotificationRead).mockResolvedValue({ id: 'n1', read_at: '2026-09-16T09:00:00' })
})
afterEach(() => vi.useRealTimers())

it('displays the unread count and marks a notice read after successful persistence', async () => {
  render(<NotificationInbox />)
  fireEvent.click(await screen.findByRole('button', { name: '站内通知（1 条未读）' }))
  expect(screen.getByText('管理员回复了批注')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '标记已读' }))
  await waitFor(() => expect(api.markNotificationRead).toHaveBeenCalledWith('n1'))
  expect(await screen.findByRole('button', { name: '站内通知（0 条未读）' })).toBeVisible()
  expect(screen.getByText('已读')).toBeVisible()
})

it('retains an unread notice on failed persistence and allows retry', async () => {
  vi.mocked(api.markNotificationRead).mockRejectedValueOnce(new Error('read offline'))
  render(<NotificationInbox />)
  fireEvent.click(await screen.findByRole('button', { name: '站内通知（1 条未读）' }))
  fireEvent.click(screen.getByRole('button', { name: '标记已读' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('read offline')
  expect(screen.getByRole('button', { name: '站内通知（1 条未读）' })).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: '标记已读' }))
  await screen.findByText('已读')
})

it('paginates and resets the cursor for unread filtering', async () => {
  vi.mocked(api.listNotifications).mockResolvedValueOnce({ items: [notice], total: 2, unread_count: 2, next_cursor: 'n1' })
  render(<NotificationInbox />)
  fireEvent.click(await screen.findByRole('button', { name: '站内通知（2 条未读）' }))
  vi.mocked(api.listNotifications).mockResolvedValueOnce({
    items: [{ ...notice, id: 'n2', body: 'later notice' }], total: 2, unread_count: 2, next_cursor: null,
  })
  fireEvent.click(screen.getByRole('button', { name: '加载更多通知' }))
  await screen.findByText('later notice')
  expect(api.listNotifications).toHaveBeenLastCalledWith('n1', false)
  fireEvent.click(screen.getByLabelText('仅未读'))
  await waitFor(() => expect(api.listNotifications).toHaveBeenLastCalledWith(undefined, true))
})

it('refreshes the unread badge on a timer and stops after unmount', async () => {
  vi.useFakeTimers()
  let view!: ReturnType<typeof render>
  await act(async () => { view = render(<NotificationInbox />) })
  vi.mocked(api.listNotifications).mockResolvedValue({ items: [], total: 0, unread_count: 0, next_cursor: null })
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
  expect(screen.getByRole('button', { name: '站内通知（0 条未读）' })).toBeInTheDocument()
  expect(api.listNotifications).toHaveBeenCalledTimes(2)
  view.unmount()
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(api.listNotifications).toHaveBeenCalledTimes(2)
})
