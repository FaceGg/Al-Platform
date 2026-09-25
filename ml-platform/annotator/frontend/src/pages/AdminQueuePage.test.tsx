import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AdminQueuePage from './AdminQueuePage'
import { acceptAdminTask, listAdminTasks, returnAdminTask } from '../api/admin'

vi.mock('../api/admin', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/admin')>()),
  listAdminTasks: vi.fn(),
  acceptAdminTask: vi.fn(),
  returnAdminTask: vi.fn(),
}))

const returnedTask = {
  id: 'task-returned',
  title: '已回传任务',
  status: 'returned_pending_acceptance',
  mode: 'manual',
  created_at: '2026-09-19T08:00:00Z',
  task_revision: 3,
  pending_return_batch_id: 'batch-1',
  return_state: 'pending',
  return_operation_state: 'completed',
  return_validated_row_count: 12,
  sample_count: 12,
  completed_samples: 12,
  annotator_name: 'annotator-a',
  project_name: '项目甲',
}

const freshTask = {
  id: 'task-fresh',
  title: '未回传任务',
  status: 'in_progress',
  mode: 'auto',
  created_at: '2026-09-18T08:00:00Z',
  task_revision: 2,
  pending_return_batch_id: null,
  return_state: null,
  sample_count: 8,
  completed_samples: 3,
  annotator_name: null,
  project_name: null,
}

function cardOf(title: string) {
  return screen.getByText(title).closest('article')!
}

describe('AdminQueuePage', () => {
  beforeEach(() => {
    vi.mocked(listAdminTasks).mockReset()
    vi.mocked(acceptAdminTask).mockReset()
    vi.mocked(returnAdminTask).mockReset()
    vi.mocked(listAdminTasks).mockResolvedValue({
      items: [returnedTask, freshTask],
      total: 2,
      next_cursor: null,
    })
  })

  it('renders owned tasks with return states and annotators', async () => {
    render(<AdminQueuePage onOpenTask={vi.fn()} />)
    expect(await screen.findByText('已回传任务')).toBeVisible()
    expect(screen.getAllByText('待验收').length).toBe(2)
    expect(screen.getByText('未回传')).toBeVisible()
    expect(screen.getByText('标注员 annotator-a')).toBeVisible()
    expect(screen.getByText('样本 12')).toBeVisible()
    expect(screen.getByText('进度 12/12')).toBeVisible()
    expect(screen.getByText('项目 项目甲')).toBeVisible()
    expect(screen.getByText('进度 3/8')).toBeVisible()
  })

  it('gates review actions on a pending return batch', async () => {
    render(<AdminQueuePage onOpenTask={vi.fn()} />)
    await screen.findByText('已回传任务')
    const disabledReason = '任务未回传，不能验收/退回/批注'
    const returnedCard = cardOf('已回传任务')
    const freshCard = cardOf('未回传任务')

    for (const name of ['合格验收', '退回修改', '批注']) {
      expect(within(returnedCard).getByRole('button', { name })).toBeEnabled()
    }
    const disabledButtons = within(freshCard).getAllByTitle(disabledReason)
    expect(disabledButtons.map((button) => button.textContent)).toEqual(['合格验收', '退回修改', '批注'])
    disabledButtons.forEach((button) => expect(button).toBeDisabled())
    expect(within(returnedCard).queryAllByTitle(disabledReason)).toHaveLength(0)
  })

  it('keeps review actions disabled while return validation is running', async () => {
    vi.mocked(listAdminTasks).mockResolvedValueOnce({
      items: [{ ...returnedTask, return_operation_state: 'running' }, freshTask],
      total: 2,
      next_cursor: null,
    })
    render(<AdminQueuePage onOpenTask={vi.fn()} />)
    await screen.findByText('已回传任务')
    const returnedCard = cardOf('已回传任务')

    expect(within(returnedCard).getByText('回传校验中')).toBeVisible()
    expect(within(returnedCard).getAllByTitle('回传校验尚未完成，不能验收/退回/批注')).toHaveLength(3)
    within(returnedCard)
      .getAllByTitle('回传校验尚未完成，不能验收/退回/批注')
      .forEach((button) => expect(button).toBeDisabled())
  })

  it('opens the review workspace via the comment action', async () => {
    const openTask = vi.fn()
    render(<AdminQueuePage onOpenTask={openTask} />)
    await screen.findByText('已回传任务')
    fireEvent.click(within(cardOf('已回传任务')).getByRole('button', { name: '批注' }))
    expect(openTask).toHaveBeenCalledWith('task-returned')
  })

  it('accepts a returned batch after confirmation and refreshes the list', async () => {
    vi.mocked(acceptAdminTask).mockResolvedValue({
      dataset_version_id: 'version-1',
      status: 'completed',
      version: 3,
    })
    render(<AdminQueuePage onOpenTask={vi.fn()} />)
    await screen.findByText('已回传任务')
    fireEvent.click(within(cardOf('已回传任务')).getByRole('button', { name: '合格验收' }))
    expect(screen.getByRole('dialog', { name: '确认合格验收' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '确认验收' }))
    await waitFor(() => expect(acceptAdminTask).toHaveBeenCalledWith('task-returned'))
    expect(await screen.findByText(/已验收「已回传任务」，生成数据版本 v3/)).toBeVisible()
    await waitFor(() => expect(listAdminTasks).toHaveBeenCalledTimes(2))
  })

  it('requires a reason before returning a batch', async () => {
    vi.mocked(returnAdminTask).mockResolvedValue({
      return_batch_id: 'batch-1',
      state: 'returned_for_changes',
    })
    render(<AdminQueuePage onOpenTask={vi.fn()} />)
    await screen.findByText('已回传任务')
    fireEvent.click(within(cardOf('已回传任务')).getByRole('button', { name: '退回修改' }))
    const dialog = screen.getByRole('dialog', { name: '退回修改' })
    const confirm = within(dialog).getByRole('button', { name: '确认退回' })
    expect(confirm).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('退回原因'), {
      target: { value: '  请补充缺失的标签  ' },
    })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    await waitFor(() => expect(returnAdminTask).toHaveBeenCalledWith('task-returned', '请补充缺失的标签'))
    expect(await screen.findByText(/已退回「已回传任务」/)).toBeVisible()
  })

  it('surfaces accept failures without closing the dialog', async () => {
    vi.mocked(acceptAdminTask).mockRejectedValueOnce(new Error('RETURN_BATCH_NOT_READY'))
    render(<AdminQueuePage onOpenTask={vi.fn()} />)
    await screen.findByText('已回传任务')
    fireEvent.click(within(cardOf('已回传任务')).getByRole('button', { name: '合格验收' }))
    fireEvent.click(screen.getByRole('button', { name: '确认验收' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('RETURN_BATCH_NOT_READY')
    expect(screen.getByRole('dialog', { name: '确认合格验收' })).toBeVisible()
  })

  it('forwards the search keyword to the server', async () => {
    render(<AdminQueuePage onOpenTask={vi.fn()} />)
    await screen.findByText('已回传任务')
    fireEvent.change(screen.getByLabelText('搜索任务'), { target: { value: ' 已回传 ' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    await waitFor(() => expect(listAdminTasks).toHaveBeenLastCalledWith(expect.objectContaining({ search: '已回传' })))
  })
})
