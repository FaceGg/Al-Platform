import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import TaskQueuePage from './TaskQueuePage'

vi.mock('../api/tasks', () => ({
  listTasks: vi.fn().mockResolvedValue({ items: [{ id: 'task-1', title: 'Review set', due_at: '2026-09-10T10:00:00Z', status: 'assigned', completed_samples: 2, total_samples: 5 }] }),
}))

describe('TaskQueuePage', () => {
  it('shows only assigned work and opens the workspace', async () => {
    const openTask = vi.fn()
    render(<TaskQueuePage onOpenTask={openTask} onLogout={vi.fn()} />)
    expect(await screen.findByText('Review set')).toBeVisible()
    expect(screen.queryByText('项目选择')).not.toBeInTheDocument()
  })
})
