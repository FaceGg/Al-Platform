import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import * as tasks from '../api/tasks'
import TaskWorkspacePage from './TaskWorkspacePage'
import * as comments from '../api/comments'

vi.mock('../api/tasks', () => ({
  getTask: vi.fn(), listSamples: vi.fn(), saveLabels: vi.fn(),
  confirmTask: vi.fn(), editForReturn: vi.fn(), returnTask: vi.fn(), bulkLabels: vi.fn(),
}))
vi.mock('../api/comments', () => ({
  listComments: vi.fn(), createComment: vi.fn(),
}))

const firstSample = { sample_id: 's-1', values: { feature: 1 }, labels: { category: 'A' }, revision: 3 }
const secondSample = { sample_id: 's-2', values: { feature: 2 }, labels: { category: 'B' }, revision: 1 }
const task = {
  id: 'task-1', title: 'Review set', task_revision: 3, status: 'assigned',
  read_only: false, scope_hash: 'scope-1', instructions: 'Review each measurement.',
  label_schema: { columns: [{ machine_key: 'category', display_name: 'Category', value_type: 'string' as const, required: true }] },
}

async function openWorkspace() {
  render(<TaskWorkspacePage taskId="task-1" />)
  await screen.findByLabelText('category-s-1')
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('TaskWorkspacePage', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(tasks.getTask).mockResolvedValue(task)
    vi.mocked(tasks.listSamples).mockResolvedValue({ items: [firstSample, secondSample] })
    vi.mocked(tasks.saveLabels).mockResolvedValue({ values: { category: 'C' }, revision: 4, task_revision: 3 })
    vi.mocked(tasks.confirmTask).mockResolvedValue({})
    vi.mocked(tasks.editForReturn).mockResolvedValue({})
    vi.mocked(tasks.returnTask).mockResolvedValue({})
    vi.mocked(tasks.bulkLabels).mockResolvedValue({ items: [] })
    vi.mocked(comments.listComments).mockResolvedValue({ items: [] })
    vi.mocked(comments.createComment).mockResolvedValue({ id: 'comment-1', content: '检查焊点', sample_id: 's-1' })
  })

  it('loads and creates a sample-scoped comment', async () => {
    await openWorkspace()
    fireEvent.change(screen.getByLabelText('新增批注'), { target: { value: '检查焊点' } })
    fireEvent.click(screen.getByRole('button', { name: '添加批注' }))
    await waitFor(() => expect(comments.createComment).toHaveBeenCalledWith('task-1', '检查焊点', 's-1'))
    expect(await screen.findByText('检查焊点')).toBeVisible()
  })
  afterEach(() => vi.useRealTimers())
  it('refreshes loaded comment pages on focus without resetting the reply draft', async () => {
    vi.mocked(comments.listComments)
      .mockResolvedValueOnce({ items: [{ id: 'c1', content: 'first note', status: 'open' }], next_cursor: 'c1' })
      .mockResolvedValueOnce({ items: [{ id: 'c2', content: 'later note', status: 'open' }] })
    await openWorkspace()
    fireEvent.click(await screen.findByRole('button', { name: '加载更多批注' }))
    await screen.findByText('later note')
    fireEvent.change(screen.getByLabelText('新增批注'), { target: { value: 'unfinished reply' } })
    vi.mocked(comments.listComments)
      .mockResolvedValueOnce({ items: [{ id: 'c1', content: 'first note', status: 'resolved' }], next_cursor: 'c1' })
      .mockResolvedValueOnce({ items: [{ id: 'c2', content: 'later note', status: 'resolved' }] })
    fireEvent.focus(window)
    await waitFor(() => expect(screen.getAllByText(/任务批注 · 已解决/)).toHaveLength(2))
    expect(comments.listComments).toHaveBeenCalledTimes(4)
    expect(screen.getByLabelText('新增批注')).toHaveValue('unfinished reply')
    expect(screen.getByLabelText('category-s-1')).toHaveValue('A')
    expect(tasks.getTask).toHaveBeenCalledTimes(1)
    expect(tasks.listSamples).toHaveBeenCalledTimes(1)
  })

  it('polls visible comments and stops after unmount', async () => {
    vi.useFakeTimers()
    let view!: ReturnType<typeof render>
    await act(async () => { view = render(<TaskWorkspacePage taskId="task-1" assignmentId="assignment-2" />) })
    expect(comments.listComments).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
    expect(comments.listComments).toHaveBeenCalledTimes(2)
    expect(comments.listComments).toHaveBeenLastCalledWith('task-1', undefined, 'assignment-2')
    view.unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
    expect(comments.listComments).toHaveBeenCalledTimes(2)
  })

  it('keeps comments and drafts on refresh failure and recovers on focus', async () => {
    vi.mocked(comments.listComments).mockResolvedValueOnce({ items: [{ id: 'c1', content: 'existing note' }] })
    await openWorkspace()
    await screen.findByText('existing note')
    fireEvent.change(screen.getByLabelText('新增批注'), { target: { value: 'draft' } })
    vi.mocked(comments.listComments).mockRejectedValueOnce(new Error('refresh offline'))
    fireEvent.focus(window)
    expect(await screen.findByText('refresh offline')).toBeVisible()
    expect(screen.getByText('existing note')).toBeVisible()
    expect(screen.getByLabelText('新增批注')).toHaveValue('draft')
    vi.mocked(comments.listComments).mockResolvedValueOnce({ items: [{ id: 'c1', content: 'existing note', status: 'resolved' }] })
    fireEvent.focus(window)
    await screen.findByText(/任务批注 · 已解决/)
    expect(screen.queryByText('refresh offline')).not.toBeInTheDocument()
  })

  it('suppresses overlapping refreshes and discards an old assignment response', async () => {
    const pending = deferred<{ items: comments.Comment[] }>()
    vi.mocked(comments.listComments).mockResolvedValueOnce({ items: [{ id: 'c1', content: 'old scope' }] })
    const view = render(<TaskWorkspacePage taskId="task-1" assignmentId="assignment-1" />)
    await screen.findByText('old scope')
    vi.mocked(comments.listComments).mockReturnValueOnce(pending.promise)
    fireEvent.focus(window)
    fireEvent.focus(window)
    expect(comments.listComments).toHaveBeenCalledTimes(2)
    vi.mocked(comments.listComments).mockResolvedValueOnce({ items: [{ id: 'c2', content: 'new scope' }] })
    view.rerender(<TaskWorkspacePage taskId="task-1" assignmentId="assignment-2" />)
    await screen.findByText('new scope')
    await act(async () => { pending.resolve({ items: [{ id: 'c1', content: 'stale refresh' }] }) })
    expect(screen.queryByText('stale refresh')).not.toBeInTheDocument()
    expect(screen.getByText('new scope')).toBeVisible()
  })

  it('does not refresh a hidden document and refreshes when visible again', async () => {
    await openWorkspace()
    const visibility = vi.spyOn(document, 'visibilityState', 'get')
    try {
      visibility.mockReturnValue('hidden')
      fireEvent(document, new Event('visibilitychange'))
      fireEvent.focus(window)
      expect(comments.listComments).toHaveBeenCalledTimes(1)
      visibility.mockReturnValue('visible')
      fireEvent(document, new Event('visibilitychange'))
      await waitFor(() => expect(comments.listComments).toHaveBeenCalledTimes(2))
    } finally {
      visibility.mockRestore()
    }
  })

  it('does not let a pending refresh erase a newly submitted comment', async () => {
    const pending = deferred<{ items: comments.Comment[] }>()
    await openWorkspace()
    vi.mocked(comments.listComments).mockReturnValueOnce(pending.promise)
    fireEvent.focus(window)
    fireEvent.change(screen.getByLabelText('新增批注'), { target: { value: '检查焊点' } })
    fireEvent.click(screen.getByRole('button', { name: '添加批注' }))
    await screen.findByText('检查焊点')
    await act(async () => { pending.resolve({ items: [] }) })
    expect(screen.getByText('检查焊点')).toBeVisible()
    expect(screen.queryByText('批注加载中...')).not.toBeInTheDocument()
  })
  it('bulk fills missing labels without overwriting existing legal values', async () => {
    vi.mocked(tasks.listSamples).mockResolvedValue({ items: [firstSample, { ...secondSample, labels: {} }] })
    vi.mocked(tasks.bulkLabels).mockResolvedValue({ items: [{ sample_id: 's-2', values: { category: 'C' }, revision: 2 }] })
    await openWorkspace()
    fireEvent.click(screen.getByLabelText('选择当前页全部样本'))
    fireEvent.change(screen.getByLabelText('批量标签值'), { target: { value: 'C' } })
    fireEvent.click(screen.getByRole('button', { name: '应用到所选样本' }))
    await waitFor(() => expect(tasks.bulkLabels).toHaveBeenCalledWith('task-1', [
      { sample_id: 's-2', values: { category: 'C' }, base_revision: 1 },
    ]))
    expect(screen.getByLabelText('category-s-1')).toHaveValue('A')
    fireEvent.click(screen.getByRole('button', { name: /2\. s-2/ }))
    expect(screen.getByLabelText('category-s-2')).toHaveValue('C')
  })

  it('requires explicit overwrite confirmation and retains selection on batch failure', async () => {
    vi.mocked(tasks.bulkLabels).mockRejectedValueOnce(new Error('batch offline'))
    render(<TaskWorkspacePage taskId="task-1" assignmentId="assignment-2" />)
    await screen.findByLabelText('category-s-1')
    fireEvent.click(screen.getByLabelText('选择样本 s-1'))
    fireEvent.change(screen.getByLabelText('批量标签值'), { target: { value: 'C' } })
    fireEvent.click(screen.getByLabelText('覆盖已有合法标签'))
    fireEvent.click(screen.getByRole('button', { name: '应用到所选样本' }))
    expect(tasks.bulkLabels).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '确认批量覆盖' }))
    expect(await screen.findByText('batch offline')).toBeVisible()
    expect(screen.getByLabelText('选择样本 s-1')).toBeChecked()
    expect(screen.getByLabelText('批量标签值')).toHaveValue('C')
    expect(screen.getByLabelText('category-s-1')).toHaveValue('A')
    expect(tasks.bulkLabels).toHaveBeenCalledWith('task-1', [
      { sample_id: 's-1', values: { category: 'C' }, base_revision: 3 },
    ], 'assignment-2')
  })

  it('blocks edits, navigation and confirmation while the atomic batch is pending', async () => {
    const pending = deferred<{ items: Array<{ sample_id: string; values: Record<string, unknown>; revision: number }> }>()
    vi.mocked(tasks.bulkLabels).mockReturnValueOnce(pending.promise)
    vi.mocked(tasks.listSamples).mockResolvedValue({ items: [{ ...firstSample, labels: {} }], next_cursor: 'next' })
    await openWorkspace()
    fireEvent.click(screen.getByLabelText('选择样本 s-1'))
    fireEvent.change(screen.getByLabelText('批量标签值'), { target: { value: 'C' } })
    fireEvent.click(screen.getByRole('button', { name: '应用到所选样本' }))
    expect(screen.getByLabelText('category-s-1')).toBeDisabled()
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '确认任务' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '返回任务' })).toBeDisabled()
    await act(async () => { pending.resolve({ items: [{ sample_id: 's-1', values: { category: 'C' }, revision: 4 }] }) })
    expect(screen.getByLabelText('category-s-1')).toHaveValue('C')
  })

  it('keeps selections and revision baselines across sample pages', async () => {
    vi.mocked(tasks.listSamples)
      .mockResolvedValueOnce({ items: [firstSample], next_cursor: 'page-2' })
      .mockResolvedValueOnce({ items: [{ ...secondSample, labels: {} }], next_cursor: undefined })
    vi.mocked(tasks.bulkLabels).mockResolvedValueOnce({
      items: [
        { sample_id: 's-1', values: { category: 'C' }, revision: 4 },
        { sample_id: 's-2', values: { category: 'C' }, revision: 2 },
      ],
    })
    render(<TaskWorkspacePage taskId="task-1" assignmentId="assignment-2" />)
    await screen.findByLabelText('category-s-1')
    fireEvent.click(screen.getByLabelText('选择样本 s-1'))
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await screen.findByLabelText('category-s-2')
    fireEvent.click(screen.getByLabelText('选择样本 s-2'))
    fireEvent.change(screen.getByLabelText('批量标签值'), { target: { value: 'C' } })
    fireEvent.click(screen.getByLabelText('覆盖已有合法标签'))
    fireEvent.click(screen.getByRole('button', { name: '应用到所选样本' }))
    fireEvent.click(screen.getByRole('button', { name: '确认批量覆盖' }))
    await waitFor(() => expect(tasks.bulkLabels).toHaveBeenCalledWith('task-1', [
      { sample_id: 's-1', values: { category: 'C' }, base_revision: 3 },
      { sample_id: 's-2', values: { category: 'C' }, base_revision: 1 },
    ], 'assignment-2'))
    expect(screen.getByText('已选择 2 条样本')).toBeVisible()
  })

  it('keeps the selected assignment on reads, saves, confirmation, return and comments', async () => {
    render(<TaskWorkspacePage taskId="task-1" assignmentId="assignment-2" />)
    await screen.findByLabelText('category-s-1')
    expect(tasks.getTask).toHaveBeenCalledWith('task-1', 'assignment-2')
    expect(tasks.listSamples).toHaveBeenCalledWith('task-1', undefined, 'assignment-2')
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'C' } })
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    await waitFor(() => expect(tasks.saveLabels).toHaveBeenCalledWith('task-1', 's-1', { category: 'C' }, 3, 'assignment-2'))
    await waitFor(() => expect(screen.getByRole('button', { name: '确认任务' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '确认任务' }))
    await waitFor(() => expect(tasks.confirmTask).toHaveBeenCalledWith('task-1', 3, 'scope-1', 'assignment-2'))
    await waitFor(() => expect(screen.getByRole('button', { name: '发起回传' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '发起回传' }))
    await waitFor(() => expect(tasks.returnTask).toHaveBeenCalledWith('task-1', 3, 'scope-1', 'assignment-2'))
    fireEvent.change(screen.getByLabelText('新增批注'), { target: { value: 'note' } })
    fireEvent.click(screen.getByRole('button', { name: '添加批注' }))
    await waitFor(() => expect(comments.createComment).toHaveBeenCalledWith('task-1', 'note', 's-1', 'assignment-2'))
  })

  it('loads later comment pages and retries a failed page without losing existing comments', async () => {
    vi.mocked(comments.listComments)
      .mockResolvedValueOnce({ items: [{ id: 'c1', content: 'first note' }], next_cursor: 'c1' })
      .mockRejectedValueOnce(new Error('comment page offline'))
      .mockResolvedValueOnce({ items: [{ id: 'c2', content: 'later note' }] })
    await openWorkspace()
    fireEvent.click(await screen.findByRole('button', { name: '加载更多批注' }))
    expect(await screen.findByText('comment page offline')).toBeVisible()
    expect(screen.getByText('first note')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '加载更多批注' }))
    expect(await screen.findByText('later note')).toBeVisible()
    expect(comments.listComments).toHaveBeenLastCalledWith('task-1', 'c1')
    expect(screen.queryByRole('button', { name: '加载更多批注' })).not.toBeInTheDocument()
  })

  it('creates task-level comments and preserves a failed submission for retry', async () => {
    vi.mocked(comments.createComment).mockRejectedValueOnce(new Error('comment submit offline'))
    await openWorkspace()
    fireEvent.change(screen.getByLabelText('批注范围'), { target: { value: 'task' } })
    fireEvent.change(screen.getByLabelText('新增批注'), { target: { value: 'task note' } })
    fireEvent.click(screen.getByRole('button', { name: '添加批注' }))
    expect(await screen.findByText('comment submit offline')).toBeVisible()
    expect(comments.createComment).toHaveBeenCalledWith('task-1', 'task note', undefined)
    expect(screen.getByLabelText('新增批注')).toHaveValue('task note')
  })

  it('overwrites with the complete local label set without resurrecting cleared optional labels', async () => {
    vi.mocked(tasks.getTask).mockResolvedValue({
      ...task, label_schema: { columns: [
        ...task.label_schema.columns,
        { machine_key: 'note', value_type: 'string', required: false },
      ] },
    } as tasks.Task)
    vi.mocked(tasks.saveLabels).mockRejectedValueOnce(Object.assign(new Error('conflict'), {
      response: { status: 409, data: { detail: {
        code: 'REVISION_CONFLICT', current_revision: 7, current_values: { category: 'server', note: 'server note' },
      } } },
    }))
    await openWorkspace()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'mine' } })
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    await screen.findByRole('dialog', { name: '版本冲突' })
    fireEvent.click(screen.getByRole('checkbox', { name: '我已核对完整标签集合' }))
    fireEvent.click(screen.getByRole('button', { name: '确认并覆盖完整标签' }))
    await waitFor(() => expect(tasks.saveLabels).toHaveBeenLastCalledWith('task-1', 's-1', { category: 'mine' }, 7))
  })

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
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'C' } })
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '确认任务' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '确认任务' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '发起回传' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '发起回传' }))
    await waitFor(() => expect(screen.getByText('回传后只读')).toBeVisible())
    expect(screen.getByRole('button', { name: '发起回传' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '编辑后回传' }))
    expect(screen.getByRole('button', { name: '发起回传' })).toBeDisabled()
  })

  it('renders every frozen schema field for empty labels and saves typed values', async () => {
    vi.mocked(tasks.getTask).mockResolvedValue({
      ...task,
      label_schema: { columns: [
        { machine_key: 'category', display_name: 'Category', value_type: 'string', enum_values: ['A', 'B'], required: true },
        { machine_key: 'count', display_name: 'Count', value_type: 'int', min_value: 0, max_value: 10 },
        { machine_key: 'score', display_name: 'Score', value_type: 'float' },
        { machine_key: 'note', display_name: 'Note', value_type: 'string', max_length: 8 },
      ] },
    } as tasks.Task)
    vi.mocked(tasks.listSamples).mockResolvedValue({ items: [{ ...firstSample, labels: {} }] })
    await openWorkspace()
    expect(screen.getByText('Review each measurement.')).toBeVisible()
    expect(screen.getByRole('combobox', { name: 'category-s-1' })).toBeVisible()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'B' } })
    fireEvent.change(screen.getByLabelText('count-s-1'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('score-s-1'), { target: { value: '1.25' } })
    fireEvent.change(screen.getByLabelText('note-s-1'), { target: { value: 'ok' } })
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    await waitFor(() => expect(tasks.saveLabels).toHaveBeenCalledWith(
      'task-1', 's-1', { category: 'B', count: 2, score: 1.25, note: 'ok' }, 3,
    ))
  })

  it.each(['1.5', '1e2', '-1'])('rejects invalid integer input %s', async (value) => {
    vi.mocked(tasks.getTask).mockResolvedValue({
      ...task, label_schema: { columns: [
        ...task.label_schema.columns,
        { machine_key: 'count', value_type: 'int', min_value: 0 },
      ] },
    } as tasks.Task)
    await openWorkspace()
    fireEvent.change(screen.getByLabelText('count-s-1'), { target: { value } })
    expect(screen.getByRole('button', { name: '保存标签' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '确认任务' })).toBeDisabled()
    expect(tasks.saveLabels).not.toHaveBeenCalled()
  })

  it.each(['   ', 'ééé'])('rejects blank or over-byte-limit strings %s', async (value) => {
    vi.mocked(tasks.getTask).mockResolvedValue({
      ...task, label_schema: { columns: [{ ...task.label_schema.columns[0], max_length: 4 }] },
    } as tasks.Task)
    await openWorkspace()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value } })
    expect(screen.getByRole('button', { name: '保存标签' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '确认任务' })).toBeDisabled()
  })

  it('debounces and serializes writes, retaining edits made during a pending request', async () => {
    await openWorkspace()
    vi.useFakeTimers()
    const pending = deferred<{ values: Record<string, unknown>; revision: number }>()
    vi.mocked(tasks.saveLabels).mockReturnValueOnce(pending.promise)
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'C' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(300) })
    expect(tasks.saveLabels).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'D' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(tasks.saveLabels).toHaveBeenCalledExactlyOnceWith('task-1', 's-1', { category: 'D' }, 3)
    expect(screen.getByRole('button', { name: '确认任务' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'E' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(tasks.saveLabels).toHaveBeenCalledTimes(1)
    await act(async () => { pending.resolve({ values: { category: 'draft one' }, revision: 4 }) })
    expect(screen.getByLabelText('category-s-1')).toHaveValue('E')
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(tasks.saveLabels).toHaveBeenLastCalledWith('task-1', 's-1', { category: 'E' }, 4)
  })

  it('preserves drafts on sample switch and never applies a response to the wrong sample', async () => {
    const pending = deferred<{ values: Record<string, unknown>; revision: number }>()
    vi.mocked(tasks.saveLabels).mockReturnValueOnce(pending.promise)
    await openWorkspace()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'draft one' } })
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    fireEvent.click(screen.getByRole('button', { name: /2\. s-2/ }))
    expect(screen.getByLabelText('category-s-2')).toHaveValue('B')
    fireEvent.change(screen.getByLabelText('category-s-2'), { target: { value: 'draft two' } })
    await act(async () => { pending.resolve({ values: { category: 'D' }, revision: 4 }) })
    expect(screen.getByLabelText('category-s-2')).toHaveValue('draft two')
    fireEvent.click(screen.getByRole('button', { name: /1\. s-1/ }))
    expect(screen.getByLabelText('category-s-1')).toHaveValue('D')
    expect(screen.getByRole('button', { name: '确认任务' })).toBeDisabled()
  })

  it('retains failed drafts and stops autosave until an explicit retry', async () => {
    vi.mocked(tasks.saveLabels).mockRejectedValueOnce(new Error('offline'))
    await openWorkspace()
    vi.useFakeTimers()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'C' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(screen.getByText('offline')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: /2\. s-2/ }))
    expect(screen.getByRole('button', { name: '确认任务' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /1\. s-1/ }))
    expect(screen.getByLabelText('category-s-1')).toHaveValue('C')
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(tasks.saveLabels).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    await act(async () => {})
    expect(tasks.saveLabels).toHaveBeenCalledTimes(2)
  })

  it('keeps conflicts blocking after dialog dismissal and requires explicit overwrite', async () => {
    vi.mocked(tasks.saveLabels).mockRejectedValueOnce(Object.assign(new Error('conflict'), {
      response: { status: 409, data: { detail: { code: 'REVISION_CONFLICT', current_revision: 7, current_values: { category: 'server' } } } },
    }))
    await openWorkspace()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'mine' } })
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    expect(await screen.findByRole('dialog', { name: '版本冲突' })).toBeVisible()
    expect(screen.getByRole('button', { name: '确认并覆盖完整标签' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.getByRole('button', { name: '确认任务' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    fireEvent.click(screen.getByRole('checkbox', { name: '我已核对完整标签集合' }))
    fireEvent.click(screen.getByRole('button', { name: '确认并覆盖完整标签' }))
    await waitFor(() => expect(tasks.saveLabels).toHaveBeenLastCalledWith('task-1', 's-1', { category: 'mine' }, 7))
  })

  it('uses the saved assignment revision for confirmation and invalidates confirmation on edit', async () => {
    await openWorkspace()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'C' } })
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '确认任务' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '确认任务' }))
    await waitFor(() => expect(tasks.confirmTask).toHaveBeenCalledWith('task-1', 3, 'scope-1'))
    await waitFor(() => expect(screen.getByRole('button', { name: '发起回传' })).toBeEnabled())
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'D' } })
    expect(screen.getByRole('button', { name: '发起回传' })).toBeDisabled()
  })

  it('requires a successful new edit and confirmation after edit-for-return', async () => {
    vi.mocked(tasks.getTask).mockResolvedValue({ ...task, read_only: true })
    const unlocking = deferred<unknown>()
    vi.mocked(tasks.editForReturn).mockReturnValueOnce(unlocking.promise)
    await openWorkspace()
    fireEvent.click(screen.getByRole('button', { name: '编辑后回传' }))
    expect(screen.getByLabelText('category-s-1')).toBeDisabled()
    expect(screen.getByRole('button', { name: '发起回传' })).toBeDisabled()
    await act(async () => { unlocking.resolve({ task_revision: 3 }) })
    expect(screen.getByRole('button', { name: '确认任务' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'C' } })
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '确认任务' })).toBeEnabled())
    expect(screen.getByRole('button', { name: '发起回传' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '确认任务' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '发起回传' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '发起回传' }))
    await waitFor(() => expect(screen.getByText('回传后只读')).toBeVisible())
  })

  it('replaces pages via next_cursor and retains only a bounded page of samples', async () => {
    vi.mocked(tasks.listSamples)
      .mockResolvedValueOnce({ items: [firstSample], next_cursor: 's-1' })
      .mockResolvedValueOnce({ items: [secondSample], next_cursor: undefined })
      .mockResolvedValueOnce({ items: [firstSample], next_cursor: 's-1' })
    await openWorkspace()
    expect(screen.getByRole('button', { name: '上一页' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await screen.findByLabelText('category-s-2')
    expect(tasks.listSamples).toHaveBeenNthCalledWith(2, 'task-1', 's-1')
    expect(screen.queryByRole('button', { name: /s-1/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '上一页' }))
    await screen.findByLabelText('category-s-1')
    expect(tasks.listSamples).toHaveBeenNthCalledWith(3, 'task-1', undefined)
  })

  it('blocks page navigation and leaving the task while drafts are dirty', async () => {
    vi.mocked(tasks.listSamples).mockResolvedValue({ items: [firstSample], next_cursor: 's-1' })
    await openWorkspace()
    fireEvent.change(screen.getByLabelText('category-s-1'), { target: { value: 'pending' } })
    expect(screen.getByRole('button', { name: '下一页' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '返回任务' })).toBeDisabled()
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })
})
