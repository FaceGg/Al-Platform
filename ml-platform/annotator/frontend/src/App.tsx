import { useEffect, useState } from 'react'
import './styles.css'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import TaskQueuePage from './pages/TaskQueuePage'
import TaskWorkspacePage from './pages/TaskWorkspacePage'
import AdminQueuePage from './pages/AdminQueuePage'
import AdminReviewPage from './pages/AdminReviewPage'
import NotificationInbox from './components/NotificationInbox'
import { me, logout, PortalIdentity } from './api/auth'
import { setPortalViewer } from './api/client'

type Page = 'queue' | 'workspace' | 'adminQueue' | 'adminReview'

type LocationView = { taskId: string | null; assignmentId: string | null; adminQueue: boolean }

function viewFromLocation(): LocationView {
  const params = new URLSearchParams(window.location.search)
  return {
    taskId: params.get('task'),
    assignmentId: params.get('assignment'),
    adminQueue: params.get('page') === 'adminQueue',
  }
}

function urlFor(page: Page, taskId: string | null, assignmentId: string | null): string {
  const params = new URLSearchParams()
  if (taskId) {
    params.set('task', taskId)
    if (assignmentId) params.set('assignment', assignmentId)
  } else if (page === 'adminQueue') {
    params.set('page', 'adminQueue')
  }
  const query = params.toString()
  return query ? `/?${query}` : '/'
}

export default function App() {
  const [user, setUser] = useState<PortalIdentity | null>(null)
  const [authView, setAuthView] = useState<'login' | 'register'>('login')
  const [page, setPage] = useState<Page>('queue')
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null)
  const [activeAssignmentId, setActiveAssignmentId] = useState<string | null>(null)

  // Mirror page switches onto the History API so the browser back button
  // returns from a workspace to its task list instead of leaving the portal.
  function navigate(page: Page, options: { taskId?: string | null; assignmentId?: string | null; replace?: boolean } = {}) {
    const taskId = options.taskId ?? null
    const assignmentId = options.assignmentId ?? null
    setActiveTaskId(taskId)
    setActiveAssignmentId(assignmentId)
    setPage(page)
    const url = urlFor(page, taskId, assignmentId)
    if (window.location.pathname + window.location.search === url) return
    if (options.replace) {
      window.history.replaceState({}, '', url)
    } else {
      window.history.pushState({}, '', url)
    }
  }

  useEffect(() => {
    // Deep links opened by the admin platform carry ?viewer=admin so this tab
    // binds to the admin session cookie before the first identity probe.
    const params = new URLSearchParams(window.location.search)
    if (params.get('viewer') === 'admin') {
      setPortalViewer('admin')
    }
    me().then((u) => {
      setUser(u)
      if (!u) return
      const admin = u.kind === 'admin'
      const view = viewFromLocation()
      if (view.taskId) {
        // Deep link (?task=&assignment=) straight into a workspace, e.g. from
        // the admin platform's return-acceptance panel. Leave a list entry in
        // the history first so the browser back button returns to the list.
        window.history.replaceState({}, '', urlFor(admin ? 'adminQueue' : 'queue', null, null))
        navigate(admin ? 'adminReview' : 'workspace', { taskId: view.taskId, assignmentId: view.assignmentId })
      } else if (admin) {
        navigate('adminQueue', { replace: true })
      } else {
        navigate('queue', { replace: true })
      }
    }).catch(() => setUser(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const onPopState = () => {
      const view = viewFromLocation()
      const admin = user?.kind === 'admin'
      if (view.taskId) {
        setActiveTaskId(view.taskId)
        setActiveAssignmentId(view.assignmentId)
        setPage(admin ? 'adminReview' : 'workspace')
      } else {
        setActiveTaskId(null)
        setActiveAssignmentId(null)
        setPage(admin ? 'adminQueue' : 'queue')
      }
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [user])

  function handleLogin() {
    me().then((u) => {
      setUser(u)
      if (!u) return
      const admin = u.kind === 'admin'
      const view = viewFromLocation()
      if (view.taskId) {
        navigate(admin ? 'adminReview' : 'workspace', { taskId: view.taskId, assignmentId: view.assignmentId, replace: true })
      } else if (admin) {
        navigate('adminQueue', { replace: true })
      } else {
        navigate('queue', { replace: true })
      }
    }).catch(() => setUser(null))
  }

  function handleLogout() {
    logout().finally(() => {
      setUser(null)
      setPage('queue')
      setActiveTaskId(null)
      setActiveAssignmentId(null)
      window.history.replaceState({}, '', '/')
    })
  }

  function openTask(taskId: string, assignmentId?: string) {
    navigate(user?.kind === 'admin' ? 'adminReview' : 'workspace', { taskId, assignmentId })
  }

  if (!user) {
    if (authView === 'register') {
      return <RegisterPage onLogin={() => setAuthView('login')} />
    }
    return (
      <LoginPage
        onLogin={handleLogin}
        onRegister={() => setAuthView('register')}
      />
    )
  }

  const isAdmin = user.kind === 'admin'
  const initials = user.username
    ? user.username.slice(0, 2).toUpperCase()
    : 'U'

  return (
    <>
      <header className="app-topbar">
        <div className="app-brand">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
          Linkraft
        </div>
        <nav className="app-nav" aria-label="主导航">
          {isAdmin ? (
            <>
              <button
                className={page === 'adminQueue' ? 'active' : ''}
                onClick={() => navigate('adminQueue')}
              >
                评审任务
              </button>
              <button
                className={page === 'adminReview' ? 'active' : ''}
                onClick={() => navigate('adminReview', { taskId: activeTaskId, assignmentId: activeAssignmentId })}
                disabled={!activeTaskId}
              >
                评审工作区
              </button>
            </>
          ) : (
            <>
              <button
                className={page === 'queue' ? 'active' : ''}
                onClick={() => navigate('queue')}
              >
                任务队列
              </button>
              <button
                className={page === 'workspace' ? 'active' : ''}
                onClick={() => navigate('workspace', { taskId: activeTaskId, assignmentId: activeAssignmentId })}
                disabled={!activeTaskId}
              >
                标注工作区
              </button>
            </>
          )}
        </nav>
        <div className="app-topbar-right">
          {!isAdmin && <NotificationInbox onOpenTask={openTask} />}
          <div className="user-chip">
            <span className="user-avatar" aria-hidden="true">{initials}</span>
            <span>{user.username}</span>
            <span className={`user-kind-badge ${isAdmin ? 'user-kind-badge--admin' : ''}`} title={isAdmin ? '当前以管理员身份登录' : '当前以标注员身份登录'}>
              {isAdmin ? '管理员' : '标注员'}
            </span>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={handleLogout}
            title="退出登录"
            aria-label="退出登录"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
          </button>
        </div>
      </header>

      {isAdmin ? (
        <>
          {page === 'adminQueue' && (
            <AdminQueuePage user={user} onOpenTask={(id) => openTask(id)} />
          )}
          {page === 'adminReview' && activeTaskId && (
            <AdminReviewPage
              taskId={activeTaskId}
              onBack={() => navigate('adminQueue')}
            />
          )}
        </>
      ) : (
        <>
          {page === 'queue' && (
            <TaskQueuePage user={user} onOpenTask={openTask} />
          )}
          {page === 'workspace' && activeTaskId && (
            <TaskWorkspacePage
              taskId={activeTaskId}
              assignmentId={activeAssignmentId ?? undefined}
              onBack={() => navigate('queue')}
            />
          )}
        </>
      )}
    </>
  )
}
