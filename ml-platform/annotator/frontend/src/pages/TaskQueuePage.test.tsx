import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TaskQueuePage from './TaskQueuePage'
import { listTasks } from '../api/tasks'

vi.mock('../api/tasks', () => ({
  listTasks: vi.fn().mockResolvedValue({ items: [{ id: 'task-1', title: 'Review set', due_at: '2026-09-10T10:00:00Z', status: 'assigned', completed_samples: 2, total_samples: 5 }] }),
}))
vi.mock('../api/notifications', () => ({
  listNotifications: vi.fn().mockResolvedValue({ items: [], total: 0, unread_count: 0, next_cursor: null }),
  markNotificationRead: vi.fn().mockResolvedValue({}),
}))

describe('TaskQueuePage', () => {
  beforeEach(() => {
    vi.mocked(listTasks).mockReset()
    vi.mocked(listTasks).mockResolvedValue({
      items: [{ id: 'task-1', title: 'Review set', status: 'assigned', task_revision: 0, scope_hash: 'hash' }],
      total: 1, next_cursor: null,
    })
  })
  it('shows only assigned work and opens the workspace', async () => {
    const openTask = vi.fn()
    render(<TaskQueuePage onOpenTask={openTask} />)
    expect(await screen.findByText('Review set')).toBeVisible()
    expect(screen.queryByText('项目选择')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '继续标注' }))
    expect(openTask).toHaveBeenCalledWith('task-1')
  })

  it('sends search and filters to the server and resets pagination', async () => {
    vi.mocked(listTasks).mockResolvedValue({
      items: [{ id: 'task-1', title: 'Review set', status: 'assigned', task_revision: 0, scope_hash: 'hash' }],
      total: 20, next_cursor: 'page-2',
    })
    render(<TaskQueuePage onOpenTask={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: '下一页' }))
    await waitFor(() => expect(listTasks).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: 'page-2' })))
    fireEvent.change(screen.getByLabelText('搜索任务'), { target: { value: ' task-1 ' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    await waitFor(() => expect(listTasks).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'task-1', cursor: undefined })))
    fireEvent.change(screen.getByLabelText('任务状态'), { target: { value: 'in_progress' } })
    await waitFor(() => expect(listTasks).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'in_progress', cursor: undefined })))
    fireEvent.change(screen.getByLabelText('任务排序'), { target: { value: 'created_at:desc' } })
    await waitFor(() => expect(listTasks).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'created_at', direction: 'desc' })))
  })

  it('opens the selected assignment when two rows refer to the same task', async () => {
    const openTask = vi.fn()
    vi.mocked(listTasks).mockResolvedValue({
      items: ['assignment-1', 'assignment-2'].map(assignment_id => ({
        id: 'task-1', assignment_id, title: 'Shared task', status: 'assigned', task_revision: 3, scope_hash: assignment_id,
      })),
      total: 2,
    })
    render(<TaskQueuePage onOpenTask={openTask} />)
    await screen.findAllByText('Shared task')
    fireEvent.click(screen.getAllByRole('button', { name: '继续标注' })[1])
    expect(openTask).toHaveBeenCalledWith('task-1', 'assignment-2')
  })

  it('offers retry after a request fails without showing an empty-success state', async () => {
    vi.mocked(listTasks).mockRejectedValueOnce(new Error('offline'))
    render(<TaskQueuePage onOpenTask={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(screen.queryByText('暂无已分派任务')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('Review set')).toBeVisible()
  })

  it('ignores an older request that finishes after a new filter', async () => {
    let resolveOld!: (value: Awaited<ReturnType<typeof listTasks>>) => void
    vi.mocked(listTasks).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    render(<TaskQueuePage onOpenTask={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('任务状态'), { target: { value: 'in_progress' } })
    expect(await screen.findByText('Review set')).toBeVisible()
    resolveOld({ items: [], total: 0, next_cursor: null })
    await waitFor(() => expect(screen.getByText('Review set')).toBeVisible())
  })

  it('shows a feedback banner for returned work and highlights the located card', async () => {
    vi.mocked(listTasks).mockResolvedValue({
      items: [
        { id: 'task-1', title: '正常任务', status: 'in_progress', state: 'pending', task_revision: 0, scope_hash: 'h' },
        { id: 'task-2', assignment_id: 'assignment-2', title: '退回任务', status: 'in_progress', state: 'edit_for_return', task_revision: 0, scope_hash: 'h' },
      ],
      total: 2, next_cursor: null,
    })
    render(<TaskQueuePage onOpenTask={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('有 1 条反馈待处理')
    expect(screen.getByText('需重做')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '查看反馈任务' }))
    expect(screen.getByText('退回任务').closest('article')).toHaveClass('highlighted')
    expect(screen.getByText('正常任务').closest('article')).not.toHaveClass('highlighted')
  })

  it('hides the feedback banner when no assignment is returned for rework', async () => {
    render(<TaskQueuePage onOpenTask={vi.fn()} />)
    await screen.findByText('Review set')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not show quality feedback for a task awaiting acceptance review', async () => {
    // 标注员回传后（含审核退回后修改并重新回传）任务处于待验收，
    // 不属于质检反馈，不应显示横幅或需重做徽章。
    vi.mocked(listTasks).mockResolvedValue({
      items: [{
        id: 'task-1', assignment_id: 'assignment-1', title: '已回传任务',
        status: 'returned_pending_acceptance', state: 'returned_pending_acceptance',
        task_revision: 0, scope_hash: 'h',
      }],
      total: 1, next_cursor: null,
    })
    render(<TaskQueuePage onOpenTask={vi.fn()} />)
    expect(await screen.findByText('待验收')).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('需重做')).not.toBeInTheDocument()
  })

  it('shows accepted tasks as accepted without the quality feedback banner', async () => {
    vi.mocked(listTasks).mockResolvedValue({
      items: [{
        id: 'task-1', title: '已验收任务', status: 'accepted', state: 'returned_pending_acceptance',
        task_revision: 0, scope_hash: 'h', due_at: '2020-01-01T00:00:00Z',
      }],
      total: 1, next_cursor: null,
    })
    render(<TaskQueuePage onOpenTask={vi.fn()} />)
    expect(await screen.findByText('已验收')).toBeVisible()
    // 已验收任务不提示质检反馈、不显示需重做、不计入逾期
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('需重做')).not.toBeInTheDocument()
    // 已验收任务不计入逾期（due_at 已过期）
    const overdueCard = screen.getByText('已逾期').closest('.stat-card') as HTMLElement
    expect(within(overdueCard).getByText('0')).toBeVisible()
  })

})
