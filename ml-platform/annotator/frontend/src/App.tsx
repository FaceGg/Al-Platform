import { useState } from 'react'
import { logout } from './api/auth'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import TaskQueuePage from './pages/TaskQueuePage'
import TaskWorkspacePage from './pages/TaskWorkspacePage'
import './styles.css'

type View = 'login' | 'register' | 'queue' | 'workspace'

export default function App() {
  const [view, setView] = useState<View>('login'); const [taskId, setTaskId] = useState('')
  const leave = async () => { try { await logout() } finally { setView('login') } }
  if (view === 'register') return <RegisterPage onLogin={() => setView('login')} />
  if (view === 'queue') return <TaskQueuePage onOpenTask={id => { setTaskId(id); setView('workspace') }} onLogout={leave} />
  if (view === 'workspace') return <TaskWorkspacePage taskId={taskId} onBack={() => setView('queue')} />
  return <LoginPage onComplete={() => setView('queue')} onRegister={() => setView('register')} />
}
