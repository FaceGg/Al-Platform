import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import TaskWorkspacePage from './TaskWorkspacePage'

vi.mock('../api/tasks', () => ({
  getTask: vi.fn().mockResolvedValue({ id: 'task-1', title: 'Review set', task_revision: 3, status: 'assigned', read_only: false, scope_hash: 'scope-1', samples: [{ sample_id: 's-1', values: { feature: 1 }, labels: { category: 'A' }, revision: 3 }] }),
  listSamples: vi.fn().mockResolvedValue({ items: [{ sample_id: 's-1', values: { feature: 1 }, labels: { category: 'A' }, revision: 3 }] }),
  saveLabels: vi.fn().mockResolvedValue({ revision: 4 }),
  confirmTask: vi.fn().mockResolvedValue({}),
  editForReturn: vi.fn().mockResolvedValue({}),
  returnTask: vi.fn().mockResolvedValue({}),
}))

describe('TaskWorkspacePage', () => {
  beforeEach(() => vi.clearAllMocks())
  it('requires explicit complete-set confirmation before retrying a revision conflict', async () => {
    const tasks = await import('../api/tasks')
    vi.mocked(tasks.saveLabels).mockRejectedValueOnce(Object.assign(new Error('conflict'), { response: { status: 409, data: { detail: { code: 'REVISION_CONFLICT', current_revision: 4, labels: { category: 'B' } } } } }))
    render(<TaskWorkspacePage taskId="task-1" />)
    await screen.findByText('Review set')
    fireEvent.change(await screen.findByLabelText('category-s-1'), { target: { value: 'C' } })
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    expect(await screen.findByText('版本冲突')).toBeVisible()
    expect(screen.getByRole('button', { name: '确认并覆盖完整标签' })).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: '我已核对完整标签集合' }))
    expect(screen.getByRole('button', { name: '确认并覆盖完整标签' })).toBeEnabled()
  })

  it('locks return until explicit edit-for-return and supports return', async () => {
    render(<TaskWorkspacePage taskId="task-1" />)
    await screen.findByText('Review set')
    fireEvent.click(screen.getByRole('button', { name: '确认任务' }))
    fireEvent.click(await screen.findByRole('button', { name: '发起回传' }))
    await waitFor(() => expect(screen.getByText('回传后只读')).toBeVisible())
    expect(screen.getByRole('button', { name: '发起回传' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '编辑后回传' }))
    expect(screen.getByRole('button', { name: '发起回传' })).toBeEnabled()
  })
})
