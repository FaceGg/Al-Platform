import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import GuidelinePanel from './GuidelinePanel'

const schema = {
  columns: [
    { machine_key: 'category', display_name: '类别', value_type: 'string' as const, required: true, enum_values: ['A', 'B'] },
    { machine_key: 'score', value_type: 'float' as const, min_value: 0, max_value: 1 },
  ],
}

describe('GuidelinePanel', () => {
  it('renders task instructions and label schema details from the task snapshot', () => {
    render(<GuidelinePanel instructions="逐条核对焊点数据。" schema={schema} />)
    expect(screen.getByText('逐条核对焊点数据。')).toBeVisible()
    expect(screen.getByText('类别')).toBeVisible()
    expect(screen.getByText('category · 文本 · 必填')).toBeVisible()
    expect(screen.getByText('可选值：A、B')).toBeVisible()
    expect(screen.getByText('score · 数值 · 选填 · 范围 0 ~ 1')).toBeVisible()
  })

  it('always shows content inline without a collapse button', () => {
    render(<GuidelinePanel instructions="逐条核对焊点数据。" schema={schema} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('逐条核对焊点数据。')).toBeVisible()
  })

  it('shows placeholders when instructions or schema are missing', () => {
    render(<GuidelinePanel />)
    expect(screen.getByText('暂无任务说明')).toBeVisible()
    expect(screen.getByText('暂无标签说明')).toBeVisible()
  })
})
