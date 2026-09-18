import { useState } from 'react'
import { logout } from './api/auth'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import TaskQueuePage from './pages/TaskQueuePage'
import TaskWorkspacePage from './pages/TaskWorkspacePage'
import NotificationInbox from './components/NotificationInbox'
import './styles.css'

type View = 'login' | 'register' | 'queue' | 'workspace'

export default function App() {
  const [view, setView] = useState<View>('login'); const [taskId, setTaskId] = useState('')
  const [assignmentId, setAssignmentId] = useState<string>()
  const leave = async () => { try { await logout() } finally { setView('login') } }
  if (view === 'register') return <RegisterPage onLogin={() => setView('login')} />
  if (view === 'queue' || view === 'workspace') return <>
    <NotificationInbox onOpenTask={(id, assignment) => { setTaskId(id); setAssignmentId(assignment); setView('workspace') }} />
    {view === 'queue'
      ? <TaskQueuePage onOpenTask={(id, assignment) => { setTaskId(id); setAssignmentId(assignment); setView('workspace') }} onLogout={leave} />
      : <TaskWorkspacePage key={`${taskId}:${assignmentId}`} taskId={taskId} assignmentId={assignmentId} onBack={() => setView('queue')} />}
  </>
  return <LoginPage onComplete={() => setView('queue')} onRegister={() => setView('register')} />
}
