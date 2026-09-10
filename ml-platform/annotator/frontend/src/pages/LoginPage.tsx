import { FormEvent, useState } from 'react'
import { login } from '../api/auth'

export default function LoginPage({ onComplete, onRegister }: { onComplete: () => void; onRegister: () => void }) {
  const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [error, setError] = useState('')
  async function submit(event: FormEvent) { event.preventDefault(); setError(''); try { await login({ username, password }); onComplete() } catch (err) { setError(err instanceof Error ? err.message : '登录失败') } }
  return <main className="auth-page"><section className="auth-panel"><p className="eyebrow">ANNOTATOR PORTAL</p><h1>登录</h1><p className="muted">使用独立门户账号访问已分派任务。</p><form onSubmit={submit}><label>用户名<input aria-label="用户名" required value={username} onChange={event => setUsername(event.target.value)} /></label><label>密码<input aria-label="密码" required minLength={8} type="password" value={password} onChange={event => setPassword(event.target.value)} /></label>{error && <p className="error">{error}</p>}<button type="submit" className="primary">登录</button></form><button type="button" className="link-button" onClick={onRegister}>创建门户账号</button></section></main>
}
