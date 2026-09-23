import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import FeedbackBanner from './FeedbackBanner'

describe('FeedbackBanner', () => {
  it('renders nothing when there is no pending feedback', () => {
    const { container } = render(<FeedbackBanner count={0} onLocate={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('warns about pending feedback items and triggers locating on click', () => {
    const onLocate = vi.fn()
    render(<FeedbackBanner count={3} onLocate={onLocate} />)
    expect(screen.getByRole('alert')).toHaveTextContent('有 3 条反馈待处理')
    fireEvent.click(screen.getByRole('button', { name: '查看反馈任务' }))
    expect(onLocate).toHaveBeenCalledOnce()
  })
})
