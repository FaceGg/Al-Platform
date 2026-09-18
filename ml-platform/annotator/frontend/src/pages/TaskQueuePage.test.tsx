import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TaskQueuePage from './TaskQueuePage'
import { listTasks } from '../api/tasks'

vi.mock('../api/tasks', () => ({
  listTasks: vi.fn().mockResolvedValue({ items: [{ id: 'task-1', title: 'Review set', due_at: '2026-09-10T10:00:00Z', status: 'assigned', completed_samples: 2, total_samples: 5 }] }),
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
    render(<TaskQueuePage onOpenTask={openTask} onLogout={vi.fn()} />)
    expect(await screen.findByText('Review set')).toBeVisible()
    expect(screen.queryByText('项目选择')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '打开工作区' }))
    expect(openTask).toHaveBeenCalledWith('task-1')
  })

  it('sends search and filters to the server and resets pagination', async () => {
    vi.mocked(listTasks).mockResolvedValue({
      items: [], total: 20, next_cursor: 'page-2',
    })
    render(<TaskQueuePage onOpenTask={vi.fn()} onLogout={vi.fn()} />)
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
    render(<TaskQueuePage onOpenTask={openTask} onLogout={vi.fn()} />)
    await screen.findAllByText('Shared task')
    fireEvent.click(screen.getAllByRole('button', { name: '打开工作区' })[1])
    expect(openTask).toHaveBeenCalledWith('task-1', 'assignment-2')
  })

  it('offers retry after a request fails without showing an empty-success state', async () => {
    vi.mocked(listTasks).mockRejectedValueOnce(new Error('offline'))
    render(<TaskQueuePage onOpenTask={vi.fn()} onLogout={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    expect(screen.queryByText('暂无已分派任务')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('Review set')).toBeVisible()
  })

  it('ignores an older request that finishes after a new filter', async () => {
    let resolveOld!: (value: Awaited<ReturnType<typeof listTasks>>) => void
    vi.mocked(listTasks).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    render(<TaskQueuePage onOpenTask={vi.fn()} onLogout={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('任务状态'), { target: { value: 'in_progress' } })
    expect(await screen.findByText('Review set')).toBeVisible()
    resolveOld({ items: [], total: 0, next_cursor: null })
    await waitFor(() => expect(screen.getByText('Review set')).toBeVisible())
  })
})
