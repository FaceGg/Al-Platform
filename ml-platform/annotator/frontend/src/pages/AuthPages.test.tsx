import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import LoginPage from './LoginPage'
import RegisterPage from './RegisterPage'

vi.mock('../api/auth', () => ({
  login: vi.fn().mockResolvedValue({ username: 'annotator' }),
  register: vi.fn().mockResolvedValue({ status: 'pending_review' }),
}))

describe('portal authentication pages', () => {
  it('submits independent portal login credentials without a project selector', async () => {
    const onComplete = vi.fn()
    render(<LoginPage onComplete={onComplete} onRegister={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'annotator' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password1' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    await vi.waitFor(() => expect(onComplete).toHaveBeenCalled())
    expect(screen.queryByLabelText('项目')).not.toBeInTheDocument()
  })

  it('shows pending review after registration', async () => {
    render(<RegisterPage onLogin={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'new-user' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password1' } })
    fireEvent.click(screen.getByRole('button', { name: '注册' }))
    expect(await screen.findByText('注册已提交，等待审核')).toBeVisible()
  })
})
