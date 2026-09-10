import { FormEvent, useState } from 'react'
import { register } from '../api/auth'

export default function RegisterPage({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [submitted, setSubmitted] = useState(false); const [error, setError] = useState('')
  async function submit(event: FormEvent) { event.preventDefault(); setError(''); try { await register({ username, password }); setSubmitted(true) } catch (err) { setError(err instanceof Error ? err.message : '注册失败') } }
  if (submitted) return <main className="auth-page"><section className="auth-panel"><p className="eyebrow">ANNOTATOR PORTAL</p><h1>注册已提交，等待审核</h1><p className="muted">审核通过后即可登录并接收任务。</p><button className="primary" onClick={onLogin}>返回登录</button></section></main>
  return <main className="auth-page"><section className="auth-panel"><p className="eyebrow">ANNOTATOR PORTAL</p><h1>创建账号</h1><form onSubmit={submit}><label>用户名<input aria-label="用户名" required value={username} onChange={event => setUsername(event.target.value)} /></label><label>密码<input aria-label="密码" required minLength={8} type="password" value={password} onChange={event => setPassword(event.target.value)} /></label>{error && <p className="error">{error}</p>}<button type="submit" className="primary">注册</button></form><button type="button" className="link-button" onClick={onLogin}>已有账号，返回登录</button></section></main>
}
