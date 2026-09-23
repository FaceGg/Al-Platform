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
    const onLogin = vi.fn()
    render(<LoginPage onLogin={onLogin} onRegister={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'annotator' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password1' } })
    fireEvent.click(screen.getByRole('button', { name: '登录到任务中心' }))
    await vi.waitFor(() => expect(onLogin).toHaveBeenCalled())
    expect(screen.queryByLabelText('项目')).not.toBeInTheDocument()
  })

  it('shows pending review after registration', async () => {
    render(<RegisterPage onLogin={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'new-user' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password1' } })
    fireEvent.click(screen.getByRole('button', { name: '提交注册申请' }))
    expect(await screen.findByText('注册已提交，等待审核')).toBeVisible()
  })
})
