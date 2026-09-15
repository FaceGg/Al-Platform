import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import * as tasks from '../api/tasks'
import TaskWorkspacePage from './TaskWorkspacePage'

vi.mock('../api/tasks', () => ({
  getTask: vi.fn(), listSamples: vi.fn(), saveLabels: vi.fn(),
  confirmTask: vi.fn(), editForReturn: vi.fn(), returnTask: vi.fn(),
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
    vi.mocked(tasks.saveLabels).mockResolvedValue({ values: { category: 'C' }, revision: 4, task_revision: 4 })
    vi.mocked(tasks.confirmTask).mockResolvedValue({})
    vi.mocked(tasks.editForReturn).mockResolvedValue({})
    vi.mocked(tasks.returnTask).mockResolvedValue({})
  })
  afterEach(() => vi.useRealTimers())
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
    await waitFor(() => expect(tasks.confirmTask).toHaveBeenCalledWith('task-1', 4, 'scope-1'))
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
