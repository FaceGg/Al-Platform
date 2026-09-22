import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { me } from './api/auth'

vi.mock('./api/auth', () => ({
  login: vi.fn(),
  logout: vi.fn().mockResolvedValue(undefined),
  me: vi.fn(),
}))
vi.mock('./api/tasks', () => ({
  listTasks: vi.fn().mockResolvedValue({ items: [], total: 0, next_cursor: null }),
}))
vi.mock('./api/notifications', () => ({
  listNotifications: vi.fn().mockResolvedValue({ items: [], total: 0, unread_count: 0, next_cursor: null }),
  markNotificationRead: vi.fn().mockResolvedValue({}),
}))
vi.mock('./api/admin', () => ({
  listAdminTasks: vi.fn().mockResolvedValue({ items: [], total: 0, next_cursor: null }),
  getAdminTask: vi.fn().mockRejectedValue(new Error('Request failed (404)')),
  listAdminSamples: vi.fn().mockRejectedValue(new Error('Request failed (404)')),
  listAdminComments: vi.fn().mockRejectedValue(new Error('Request failed (404)')),
  createAdminComment: vi.fn(),
  acceptAdminTask: vi.fn(),
  returnAdminTask: vi.fn(),
}))

describe('App session restore', () => {
  afterEach(() => {
    vi.mocked(me).mockReset()
    window.history.replaceState({}, '', '/')
  })

  it('restores the queue view after a page refresh while the portal session cookie is valid', async () => {
    vi.mocked(me).mockResolvedValue({ subject_id: 'subject-1', username: 'jingms' })
    render(<App />)
    expect(await screen.findByText('我的任务')).toBeVisible()
    expect(screen.getByText('jingms')).toBeVisible()
    expect(screen.queryByRole('button', { name: '登录到任务中心' })).not.toBeInTheDocument()
  })

  it('falls back to the login page when no valid session exists', async () => {
    vi.mocked(me).mockRejectedValue(new Error('Request failed (401)'))
    render(<App />)
    expect(await screen.findByRole('button', { name: '登录到任务中心' })).toBeVisible()
    expect(screen.queryByText('我的任务')).not.toBeInTheDocument()
  })

  it('routes platform admins to the admin review queue without the notification inbox', async () => {
    vi.mocked(me).mockResolvedValue({ subject_id: null, username: 'admin-a', kind: 'admin', user_id: 'user-1' })
    render(<App />)
    expect(await screen.findByRole('heading', { name: '评审任务' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: '我的任务' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '评审任务' })).toBeVisible()
    expect(screen.queryByLabelText(/站内通知/)).not.toBeInTheDocument()
  })

  it('deep links admins straight into the review workspace', async () => {
    window.history.replaceState({}, '', '/?task=task-9')
    vi.mocked(me).mockResolvedValue({ subject_id: null, username: 'admin-a', kind: 'admin', user_id: 'user-1' })
    render(<App />)
    expect(await screen.findByRole('button', { name: '返回任务列表' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '评审工作区' })).toBeVisible()
  })
})
