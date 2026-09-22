import { FormEvent, useState } from 'react'
import { register } from '../api/auth'

export default function RegisterPage({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      await register({ username, password })
      setSubmitted(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : '注册失败')
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    return (
      <main className="auth-page">
        <section className="auth-panel">
          <p className="eyebrow">ANNOTATOR PORTAL</p>
          <h1>注册已提交，等待审核</h1>
          <p className="muted">
            账号状态为待审核。管理员激活后即可登录并接收任务。
          </p>
          <button className="primary" onClick={onLogin}>
            返回登录
          </button>
        </section>
      </main>
    )
  }

  return (
    <main className="auth-page">
      <section className="auth-panel">
        <p className="eyebrow">ANNOTATOR PORTAL</p>
        <h1>创建账号</h1>
        <p className="muted">填写以下信息申请标注员账号，管理员审核通过后将通知您。</p>

        <form onSubmit={submit}>
          <label>
            用户名
            <input
              aria-label="用户名"
              required
              placeholder="请设置用户名"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
            />
          </label>
          <label>
            密码
            <input
              aria-label="密码"
              required
              minLength={8}
              type="password"
              placeholder="至少 8 位字符"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit" className="primary" disabled={submitting}>
            {submitting ? '提交中...' : '提交注册申请'}
          </button>
        </form>

        <div className="auth-footer">
          已有账号？
          <button type="button" className="link-button" onClick={onLogin}>
            返回登录
          </button>
        </div>
      </section>
    </main>
  )
}
