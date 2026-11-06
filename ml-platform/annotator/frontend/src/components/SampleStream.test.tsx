import { fireEvent, render, screen, within } from '@testing-library/react'
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

  it('renders decoded waveform charts when the sample carries waveforms', () => {
    renderStream({
      sample: {
        ...sample,
        waveforms: { current: [10, 40, 20, 60], voltage: [5, 8, 6], resistance: [1, 2], power: [3, 9, 4, 7] },
      },
    })
    expect(screen.getByText('波形数据')).toBeVisible()
    expect(screen.getByRole('img', { name: '电流波形曲线，共 4 个采样点' })).toBeVisible()
    expect(screen.getByRole('img', { name: '电压波形曲线，共 3 个采样点' })).toBeVisible()
    expect(screen.getByRole('img', { name: '电阻波形曲线，共 2 个采样点' })).toBeVisible()
    expect(screen.getByRole('img', { name: '功率波形曲线，共 4 个采样点' })).toBeVisible()
  })

  it('keeps the workspace layout unchanged when the sample has no waveforms', () => {
    renderStream()
    expect(screen.queryByText('波形数据')).not.toBeInTheDocument()
  })

  it('shows automatic labels as the automatic result with an annotator override box', () => {
    renderStream({ sample: { ...sample, label_source: 'automatic', automatic_labels: { category: 'A' } } })
    const panel = screen.getByLabelText('自动标注结果')
    expect(panel).toBeVisible()
    expect(screen.getByText('以下标签由自动标注生成并保留存档，右侧人工修改后会覆盖使用。')).toBeVisible()
    expect(within(panel).getByText('类别')).toBeVisible()
    expect(within(panel).getByText('A')).toBeVisible()
    expect(screen.getByText('标注员修改（人工结果）')).toBeVisible()
    // 未修改的列不显示"已修改"标记
    expect(within(panel).queryByText('已修改')).not.toBeInTheDocument()
  })

  it('keeps the automatic result visible and marks modified columns after a manual edit', () => {
    renderStream({
      sample: {
        ...sample,
        label_source: 'manual',
        automatic_labels: { category: 'A' },
        labels: { category: 'B' },
        manual_modified: true,
      },
    })
    const panel = screen.getByLabelText('自动标注结果')
    // 自动结果保留显示
    expect(within(panel).getByText('A')).toBeVisible()
    // 修改过的列带"已修改"标记
    expect(within(panel).getByText('已修改')).toBeVisible()
    expect(screen.getByText('标注员修改（人工结果）')).toBeVisible()
  })

  it('keeps the plain label editor when the labels are not automatic', () => {
    renderStream({ sample: { ...sample, label_source: 'manual' } })
    expect(screen.queryByLabelText('自动标注结果')).not.toBeInTheDocument()
    expect(screen.getByText('标签')).toBeVisible()
    expect(screen.queryByText('标注员修改（人工结果）')).not.toBeInTheDocument()
  })

  it('shows field descriptions for matched columns and plain fields otherwise', () => {
    renderStream({ fieldDescriptions: { feature: '焊点强度分值' } })
    // 匹配上的字段显示名称、描述和数据
    const featureField = screen.getByText('feature').closest('.field-item') as HTMLElement
    expect(within(featureField).getByText('焊点强度分值')).toBeVisible()
    expect(within(featureField).getByText('1')).toBeVisible()
    // 未匹配的字段只显示名称和数据，没有描述
    const noteField = screen.getByText('焊点').closest('.field-item') as HTMLElement
    expect(noteField.querySelector('.field-item-description')).toBeNull()
  })

  it('lists every defined value as a clickable option and offers no free input for enum columns', () => {
    const grade: LabelColumn = { machine_key: 'grade', display_name: '等级', value_type: 'int', required: true, enum_values: [0, 1, 2] }
    // 只有前两个值分到数字快捷键，第三个同样要能点选
    const props = renderStream({
      columns: [grade],
      draft: { grade: 1 },
      numberedOptions: [{ column: grade, value: '0', index: 1 }, { column: grade, value: '1', index: 2 }],
    })
    const group = screen.getByRole('group', { name: 'grade-s-1' })
    expect(within(group).getAllByRole('button').map(button => button.getAttribute('aria-label'))).toEqual(['快捷选项 1 0', '快捷选项 2 1', '2'])
    expect(screen.getByRole('button', { name: '快捷选项 2 1' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '快捷选项 1 0' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'grade-s-1' })).not.toBeInTheDocument()
    expect(screen.queryByText(/允许范围/)).not.toBeInTheDocument()
    expect(screen.getByText('点击选项选择标签值；选项前的灰色序号是键盘快捷键，不是标签值')).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '2' }))
    expect(props.onToggleOption).toHaveBeenCalledWith(grade, '2')
    // 点标题文字不能误触选项
    fireEvent.click(screen.getByText('等级'))
    expect(props.onToggleOption).toHaveBeenCalledOnce()
  })

  it('releases focus after a mouse click on an option so Enter keeps saving', () => {
    renderStream()
    const option = screen.getByRole('button', { name: '快捷选项 2 B' })
    option.focus()
    // detail>0 才是鼠标点击；键盘激活（detail=0）保留焦点
    fireEvent.click(option, { detail: 0 })
    expect(document.activeElement).toBe(option)
    fireEvent.click(option, { detail: 1 })
    expect(document.activeElement).not.toBe(option)
  })

  it('shows the allowed range next to free-form numeric columns', () => {
    renderStream({
      columns: [
        { machine_key: 'count', display_name: '数量', value_type: 'int', required: true, min_value: 0, max_value: 10 },
        { machine_key: 'score', display_name: '分数', value_type: 'float', min_value: 0.5 },
        { machine_key: 'free', display_name: '无约束', value_type: 'float', min_value: null, max_value: null } as unknown as LabelColumn,
      ],
      draft: {},
      numberedOptions: [],
    })
    const count = screen.getByRole('spinbutton', { name: 'count-s-1' })
    expect(count).toHaveAttribute('min', '0')
    expect(count).toHaveAttribute('max', '10')
    expect(screen.getByText('允许范围 0 ~ 10（含边界，整数）')).toBeVisible()
    expect(screen.getByText('允许范围 0.5 ~ +∞（含边界，数值）')).toBeVisible()
    expect(screen.getByRole('spinbutton', { name: 'free-s-1' })).not.toHaveAttribute('min')
    expect(screen.getAllByText(/允许范围/)).toHaveLength(2)
  })

  it('shows validation errors under the field instead of a generic save failure', () => {
    renderStream({
      columns: [{ machine_key: 'count', display_name: '数量', value_type: 'int', min_value: 0, max_value: 10 }],
      draft: { count: '15' },
      numberedOptions: [],
      saveDisabled: true,
      saveState: 'error',
      fieldErrors: { count: '整数高于最大值' },
    })
    expect(screen.getByText('整数高于最大值')).toBeVisible()
    expect(screen.queryByText('保存失败，请重试')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存标签' })).toBeDisabled()
  })

  it('keeps the generic save failure when no field is invalid', () => {
    renderStream({ saveState: 'error' })
    expect(screen.getByText('保存失败，请重试')).toBeVisible()
  })
})
