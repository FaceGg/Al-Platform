import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import SampleStream from './SampleStream'
import { LabelColumn, Sample } from '../api/tasks'

const sample: Sample = { sample_id: 's-1', values: { feature: 1, note: '焊点' }, labels: { category: 'A' }, revision: 3 }
const columns: LabelColumn[] = [
  { machine_key: 'category', display_name: '类别', value_type: 'string', required: true, enum_values: ['A', 'B'] },
  { machine_key: 'count', value_type: 'int' },
]
const numberedOptions = [
  { column: columns[0], value: 'A', index: 1 },
  { column: columns[0], value: 'B', index: 2 },
]

function renderStream(overrides: Partial<Parameters<typeof SampleStream>[0]> = {}) {
  const props = {
    sample, columns, draft: { category: 'A' }, visibleColumns: ['feature'], numberedOptions,
    disabled: false, saveDisabled: false, saveState: 'clean' as const,
    position: 1, total: 3, completed: 0, summaryOpen: false,
    onDraftChange: vi.fn(), onToggleOption: vi.fn(), onSave: vi.fn(), onSaveAndNext: vi.fn(),
    onSkip: vi.fn(), onPrev: vi.fn(), onNext: vi.fn(), onOpenSamples: vi.fn(), onRestart: vi.fn(),
    ...overrides,
  }
  render(<SampleStream {...props} />)
  return props
}

describe('SampleStream', () => {
  it('shows the current sample with highlighted annotation fields and grouped other fields', () => {
    renderStream()
    expect(screen.getByText('当前样本 s-1')).toBeVisible()
    expect(screen.getByText('标注字段')).toBeVisible()
    expect(screen.getByText('其他字段')).toBeVisible()
    expect(screen.getByText('feature')).toBeVisible()
    expect(screen.getByText('焊点')).toBeVisible()
  })

  it('shows number badges on enum options and forwards toggles', () => {
    const props = renderStream()
    expect(screen.getByRole('button', { name: '快捷选项 1 A' })).toBeVisible()
    expect(screen.getByRole('button', { name: '快捷选项 2 B' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '快捷选项 2 B' }))
    expect(props.onToggleOption).toHaveBeenCalledWith(columns[0], 'B')
  })

  it('renders the progress footer and stream actions', () => {
    const props = renderStream()
    expect(screen.getByText('第 1/3 条')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '← 上一条' }))
    expect(props.onPrev).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '下一条 →' }))
    expect(props.onNext).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '跳过' }))
    expect(props.onSkip).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '保存并下一样本' }))
    expect(props.onSaveAndNext).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '保存标签' }))
    expect(props.onSave).toHaveBeenCalledOnce()
  })

  it('shows the completion summary instead of the sample at the end of the queue', () => {
    const props = renderStream({ summaryOpen: true, completed: 5 })
    expect(screen.getByText('本次连续完成 5 条样本')).toBeVisible()
    expect(screen.queryByLabelText('category-s-1')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '从头继续' }))
    expect(props.onRestart).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '筛选样本' }))
    expect(props.onOpenSamples).toHaveBeenCalledOnce()
  })
})
