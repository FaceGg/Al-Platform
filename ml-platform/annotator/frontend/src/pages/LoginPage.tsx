import { FormEvent, useState } from 'react'
import { login } from '../api/auth'

export default function LoginPage({
  onLogin,
  onRegister,
}: {
  onLogin: () => void
  onRegister: () => void
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [remember, setRemember] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await login({ username, password })
      onLogin()
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-panel">
        <p className="eyebrow">Annotator Portal</p>
        <h1>标注员门户</h1>
        <p className="muted">请使用分配的企业账号登录，开始今天的标注任务。</p>

        <form onSubmit={submit}>
          <label>
            用户名 / 工号
            <input
              type="text"
              aria-label="用户名"
              required
              placeholder="例如 annotator-0421"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
            />
          </label>
          <label>
            密码
            <input
              type="password"
              aria-label="密码"
              required
              placeholder="输入密码"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          </label>
          <div className="form-row">
            <label className="check">
              <input
                type="checkbox"
                checked={remember}
                onChange={(event) => setRemember(event.target.checked)}
              />
              记住我
            </label>
            <a href="#forgot">忘记密码？</a>
          </div>
          {error && <p className="error">{error}</p>}
          <button type="submit" className="primary" disabled={submitting}>
            {submitting ? '登录中...' : '登录到任务中心'}
          </button>
        </form>

        <div className="auth-footer">
          还没有账号？
          <button type="button" className="link-button" onClick={onRegister}>
            申请注册
          </button>
        </div>
      </section>
    </main>
  )
}
