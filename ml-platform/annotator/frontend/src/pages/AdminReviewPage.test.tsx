import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminReviewPage from './AdminReviewPage'
import { AdminTask, createAdminComment, getAdminTask, listAdminComments, listAdminSamples } from '../api/admin'

vi.mock('../api/admin', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/admin')>()),
  getAdminTask: vi.fn(),
  listAdminSamples: vi.fn(),
  listAdminComments: vi.fn(),
  createAdminComment: vi.fn(),
}))

const pendingTask: AdminTask = {
  id: 'task-1',
  title: '评审任务',
  status: 'returned_pending_acceptance',
  mode: 'manual',
  created_at: '2026-09-19T08:00:00Z',
  instructions: '',
  visible_columns: ['feature'],
  label_schema: {
    columns: [{ machine_key: 'result', display_name: '结果', value_type: 'string', enum_values: ['pass', 'fail'] }],
  },
  sample_scope: { kind: 'ids', sample_count: 2, scope_hash: 'h' },
  pending_return_batch_id: 'batch-1',
  return_state: 'pending',
  return_operation_state: 'completed',
  read_only: true as const,
  task_revision: 3,
}

const samples = [
  { sample_id: 'sample-1', values: { feature: 'weld-001' }, labels: { result: 'pass' }, revision: 3 },
  { sample_id: 'sample-2', values: { feature: 'weld-002' }, labels: {}, revision: null },
]

describe('AdminReviewPage', () => {
  beforeEach(() => {
    vi.mocked(getAdminTask).mockReset()
    vi.mocked(listAdminSamples).mockReset()
    vi.mocked(listAdminComments).mockReset()
    vi.mocked(createAdminComment).mockReset()
    vi.mocked(getAdminTask).mockResolvedValue(pendingTask)
    vi.mocked(listAdminSamples).mockResolvedValue({ items: samples, total: 2, next_cursor: null })
    vi.mocked(listAdminComments).mockResolvedValue({
      items: [
        {
          id: 'comment-1',
          sample_id: 'sample-1',
          parent_id: null,
          author_name: 'admin-a',
          content: '已有批注',
          status: 'open',
          created_at: '2026-09-19T09:00:00Z',
        },
      ],
      total: 1,
    })
    vi.mocked(createAdminComment).mockImplementation(async (_taskId, _sampleId, content) => ({
      id: 'comment-new',
      task_id: _taskId,
      sample_id: _sampleId,
      parent_id: null,
      author_name: 'admin-a',
      content,
      status: 'open',
      created_at: '2026-09-19T10:00:00Z',
    }))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders sample data, read-only labels and comments', async () => {
    render(<AdminReviewPage taskId="task-1" onBack={vi.fn()} />)
    expect(await screen.findByText('weld-001')).toBeVisible()
    expect(screen.getByText('feature')).toBeVisible()
    expect(screen.getByText('结果')).toBeVisible()
    expect(screen.getByText('pass')).toBeVisible()
    expect(screen.getByText('标注结果（只读）')).toBeVisible()
    expect(await screen.findByText('已有批注')).toBeVisible()
    expect(screen.getByText('admin-a')).toBeVisible()
    expect(screen.getByText('样本 1 / 2')).toBeVisible()
  })

  it('navigates between samples with buttons and arrow keys', async () => {
    render(<AdminReviewPage taskId="task-1" onBack={vi.fn()} />)
    await screen.findByText('weld-001')
    fireEvent.click(screen.getByRole('button', { name: '下一条' }))
    await waitFor(() => expect(listAdminComments).toHaveBeenLastCalledWith('task-1', 'sample-2'))
    expect(await screen.findByText('weld-002')).toBeVisible()
    expect(screen.getByText('样本 2 / 2')).toBeVisible()
    expect(screen.getByText('未标注')).toBeVisible()

    fireEvent.keyDown(window, { key: 'ArrowLeft' })
    await waitFor(() => expect(screen.getByText('weld-001')).toBeVisible())
    expect(screen.getByText('样本 1 / 2')).toBeVisible()
  })

  it('autosaves a comment 800ms after typing pauses', async () => {
    render(<AdminReviewPage taskId="task-1" onBack={vi.fn()} />)
    await screen.findByText('weld-001')
    vi.useFakeTimers()
    fireEvent.change(screen.getByLabelText('批注内容'), { target: { value: '  新批注内容  ' } })
    await vi.advanceTimersByTimeAsync(800)
    vi.useRealTimers()
    await waitFor(() => expect(createAdminComment).toHaveBeenCalledWith('task-1', 'sample-1', '新批注内容'))
    expect(await screen.findByText('新批注内容')).toBeVisible()
    expect(screen.getByLabelText('批注内容')).toHaveValue('')
    expect(screen.getByText('已保存')).toBeVisible()
  })

  it('does not repost identical comment content', async () => {
    render(<AdminReviewPage taskId="task-1" onBack={vi.fn()} />)
    await screen.findByText('weld-001')
    vi.useFakeTimers()
    fireEvent.change(screen.getByLabelText('批注内容'), { target: { value: '重复批注' } })
    await vi.advanceTimersByTimeAsync(800)
    vi.useRealTimers()
    await waitFor(() => expect(createAdminComment).toHaveBeenCalledTimes(1))
    fireEvent.change(screen.getByLabelText('批注内容'), { target: { value: '重复批注' } })
    vi.useFakeTimers()
    await vi.advanceTimersByTimeAsync(1000)
    vi.useRealTimers()
    await waitFor(() => expect(screen.getByLabelText('批注内容')).toHaveValue('重复批注'))
    expect(createAdminComment).toHaveBeenCalledTimes(1)
  })

  it('saves immediately via the manual button', async () => {
    render(<AdminReviewPage taskId="task-1" onBack={vi.fn()} />)
    await screen.findByText('weld-001')
    fireEvent.change(screen.getByLabelText('批注内容'), { target: { value: '手动批注' } })
    fireEvent.click(screen.getByRole('button', { name: '添加批注' }))
    await waitFor(() => expect(createAdminComment).toHaveBeenCalledWith('task-1', 'sample-1', '手动批注'))
    expect(await screen.findByText('手动批注')).toBeVisible()
  })

  it('disables commenting when the task has no pending return batch', async () => {
    vi.mocked(getAdminTask).mockResolvedValue({ ...pendingTask, pending_return_batch_id: null, return_state: 'accepted' })
    render(<AdminReviewPage taskId="task-1" onBack={vi.fn()} />)
    await screen.findByText('weld-001')
    expect(screen.getByLabelText('批注内容')).toBeDisabled()
    expect(screen.getByRole('button', { name: '添加批注' })).toBeDisabled()
    expect(screen.getAllByText('任务未回传，无法批注').length).toBeGreaterThan(0)
  })

  it('restores an unsaved draft when navigating back after a failed autosave', async () => {
    vi.mocked(createAdminComment).mockRejectedValue(new Error('ADMIN_COMMENT_SAVE_FAILED'))
    render(<AdminReviewPage taskId="task-1" onBack={vi.fn()} />)
    await screen.findByText('weld-001')
    vi.useFakeTimers()
    fireEvent.change(screen.getByLabelText('批注内容'), { target: { value: '失败草稿' } })
    await vi.advanceTimersByTimeAsync(800)
    vi.useRealTimers()
    await waitFor(() => expect(createAdminComment).toHaveBeenCalledTimes(1))

    // Navigate away (background retry also fails) then back.
    fireEvent.click(screen.getByRole('button', { name: '下一条' }))
    await screen.findByText('weld-002')
    await waitFor(() => expect(createAdminComment).toHaveBeenCalledTimes(2))
    fireEvent.click(screen.getByRole('button', { name: '上一条' }))
    await screen.findByText('weld-001')
    expect(screen.getByLabelText('批注内容')).toHaveValue('失败草稿')

    // The restored draft can be saved manually once the backend recovers.
    vi.mocked(createAdminComment).mockImplementationOnce(async (_taskId, _sampleId, content) => ({
      id: 'comment-retry',
      task_id: _taskId,
      sample_id: _sampleId,
      parent_id: null,
      author_name: 'admin-a',
      content,
      status: 'open',
      created_at: '2026-09-19T11:00:00Z',
    }))
    fireEvent.click(screen.getByRole('button', { name: '添加批注' }))
    await waitFor(() => expect(createAdminComment).toHaveBeenCalledTimes(3))
    expect(await screen.findByText('失败草稿')).toBeVisible()
  })

  it('keeps a pending draft when switching samples before the debounce fires', async () => {
    render(<AdminReviewPage taskId="task-1" onBack={vi.fn()} />)
    await screen.findByText('weld-001')
    fireEvent.change(screen.getByLabelText('批注内容'), { target: { value: '未到期的草稿' } })
    fireEvent.click(screen.getByRole('button', { name: '下一条' }))
    // flushArmed saves the sample-1 draft silently.
    await waitFor(() => expect(createAdminComment).toHaveBeenCalledWith('task-1', 'sample-1', '未到期的草稿'))
    await screen.findByText('weld-002')
    expect(screen.getByLabelText('批注内容')).toHaveValue('')
    fireEvent.click(screen.getByRole('button', { name: '上一条' }))
    await screen.findByText('weld-001')
    // The silent save persisted exactly once, so no draft is restored.
    expect(createAdminComment).toHaveBeenCalledTimes(1)
    expect(screen.getByLabelText('批注内容')).toHaveValue('')
    expect(screen.getByText('停止输入后自动保存')).toBeVisible()
  })

  it('shows an error state when the task cannot be loaded', async () => {
    vi.mocked(getAdminTask).mockRejectedValue(new Error('ANNOTATION_TASK_NOT_FOUND'))
    vi.mocked(listAdminSamples).mockRejectedValue(new Error('ANNOTATION_TASK_NOT_FOUND'))
    render(<AdminReviewPage taskId="task-1" onBack={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('ANNOTATION_TASK_NOT_FOUND')
    fireEvent.click(screen.getByRole('button', { name: '返回任务列表' }))
  })
})
