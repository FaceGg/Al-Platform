import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import TaskCard, { isFeedbackTask } from './TaskCard'
import { Task } from '../api/tasks'

const base: Task = { id: 'task-1', title: '焊点复核', status: 'in_progress', task_revision: 1, scope_hash: 'h' }
const dueAt = '2026-09-20T10:00:00Z'

describe('TaskCard', () => {
  it('renders title, status tag, progress, due date and the continue button', () => {
    render(<TaskCard task={{ ...base, completed_samples: 2, total_samples: 5, due_at: dueAt }} onOpenTask={vi.fn()} />)
    expect(screen.getByText('焊点复核')).toBeVisible()
    expect(screen.getByText('进行中')).toBeVisible()
    expect(screen.getByText('我的进度 2/5')).toBeVisible()
    expect(screen.getByText(`截止 ${new Date(dueAt).toLocaleDateString()}`)).toBeVisible()
    expect(screen.getByRole('button', { name: '继续标注' })).toBeVisible()
  })

  it('hides progress when the list API provides no progress fields', () => {
    render(<TaskCard task={base} onOpenTask={vi.fn()} />)
    expect(screen.queryByText(/^我的进度/)).not.toBeInTheDocument()
    expect(screen.getByText('未设置截止时间')).toBeVisible()
  })

  it('marks returned work as needing rework', () => {
    render(<TaskCard task={{ ...base, state: 'edit_for_return' }} onOpenTask={vi.fn()} />)
    expect(screen.getByText('需重做')).toBeVisible()
  })

  it('opens the workspace with the assignment id when present', () => {
    const onOpenTask = vi.fn()
    render(<TaskCard task={{ ...base, assignment_id: 'a-1' }} onOpenTask={onOpenTask} />)
    fireEvent.click(screen.getByRole('button', { name: '继续标注' }))
    expect(onOpenTask).toHaveBeenCalledWith('task-1', 'a-1')
  })

  it('treats returned or rework assignment states as feedback tasks', () => {
    expect(isFeedbackTask({ ...base, state: 'returned_pending_acceptance' })).toBe(true)
    expect(isFeedbackTask({ ...base, state: 'edit_for_return' })).toBe(true)
    expect(isFeedbackTask({ ...base, status: 'returned_pending_acceptance' })).toBe(true)
    expect(isFeedbackTask({ ...base, state: 'pending' })).toBe(false)
  })
})
