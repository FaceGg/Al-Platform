import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AdminComment,
  AdminSample,
  AdminTask,
  createAdminComment,
  getAdminTask,
  listAdminComments,
  listAdminSamples,
} from '../api/admin'

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

function formatValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return '未标注'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function formatTime(value: string | null | undefined): string {
  if (!value) return ''
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

export default function AdminReviewPage({
  taskId,
  onBack,
}: {
  taskId: string
  onBack: () => void
}) {
  const [task, setTask] = useState<AdminTask | null>(null)
  const [samples, setSamples] = useState<AdminSample[]>([])
  const [total, setTotal] = useState(0)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [index, setIndex] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [comments, setComments] = useState<AdminComment[]>([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [draft, setDraft] = useState('')
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [commentError, setCommentError] = useState('')
  const [error, setError] = useState('')

  const taskGeneration = useRef(0)
  const sampleGeneration = useRef(0)
  const commentGeneration = useRef(0)
  const samplesRef = useRef<AdminSample[]>([])
  const sampleIdRef = useRef<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const armedRef = useRef<{ sampleId: string; content: string } | null>(null)
  const savingRef = useRef(false)
  const lastSavedRef = useRef<Map<string, string>>(new Map())
  const unsavedRef = useRef<Map<string, string>>(new Map())
  const loadingMoreRef = useRef(false)

  const sample = samples[index]
  const sampleId = sample?.sample_id ?? null
  const reviewable = Boolean(task?.pending_return_batch_id)
  const columns = task?.label_schema?.columns ?? []

  const saveComment = useCallback(async (targetSampleId: string, content: string, silent = false) => {
    const trimmed = content.trim()
    if (!task || savingRef.current || !trimmed) return
    if ((lastSavedRef.current.get(targetSampleId) ?? '') === trimmed) return
    savingRef.current = true
    if (!silent) {
      setSaveState('saving')
      setCommentError('')
    }
    try {
      const created = await createAdminComment(task.id, targetSampleId, trimmed)
      lastSavedRef.current.set(targetSampleId, trimmed)
      unsavedRef.current.delete(targetSampleId)
      if (armedRef.current && armedRef.current.sampleId === targetSampleId && armedRef.current.content === content) {
        armedRef.current = null
      }
      if (!silent && sampleIdRef.current === targetSampleId) {
        setDraft('')
        setComments((current) => [...current, created])
        setSaveState('saved')
      }
    } catch (err) {
      if (!silent && sampleIdRef.current === targetSampleId) {
        setSaveState('error')
        setCommentError(err instanceof Error ? err.message : '批注保存失败')
      }
    } finally {
      savingRef.current = false
    }
  }, [task])

  const saveCommentRef = useRef(saveComment)
  saveCommentRef.current = saveComment

  useEffect(() => {
    const current = ++taskGeneration.current
    getAdminTask(taskId)
      .then((data) => {
        if (current === taskGeneration.current) setTask(data)
      })
      .catch((err) => {
        if (current === taskGeneration.current)
          setError(err instanceof Error ? err.message : '任务加载失败')
        // A deep-linked task may have been deleted before a browser refresh.
        const status = (err as { response?: { status?: number } })?.response?.status
        if (current === taskGeneration.current && status === 404) setError('任务不存在或已被删除，无法打开评审工作区')
      })
  }, [taskId])

  useEffect(() => {
    const current = ++sampleGeneration.current
    setLoading(true)
    listAdminSamples(taskId)
      .then((data) => {
        if (current !== sampleGeneration.current) return
        setSamples(data.items ?? [])
        setTotal(data.total ?? 0)
        setNextCursor(data.next_cursor ?? null)
        setIndex(0)
      })
      .catch((err) => {
        if (current === sampleGeneration.current)
          setError(err instanceof Error ? err.message : '样本加载失败')
      })
      .finally(() => {
        if (current === sampleGeneration.current) setLoading(false)
      })
  }, [taskId])

  useEffect(() => {
    samplesRef.current = samples
  }, [samples])

  useEffect(() => {
    sampleIdRef.current = sampleId
  }, [sampleId])

  // Comments follow the active sample; an unsaved draft (e.g. after a failed
  // autosave) is restored instead of being dropped when switching samples.
  useEffect(() => {
    if (!sampleId) return
    const current = ++commentGeneration.current
    const restored = unsavedRef.current.get(sampleId) ?? ''
    setDraft(restored)
    if (restored) {
      setSaveState('error')
      setCommentError('上次批注未保存成功，已恢复草稿；编辑后将重新自动保存')
    } else {
      setSaveState('idle')
      setCommentError('')
    }
    setCommentsLoading(true)
    // Retry drafts of other samples that a previous silent save may have lost.
    void retryUnsaved()
    listAdminComments(taskId, sampleId)
      .then((data) => {
        if (current === commentGeneration.current) setComments(data.items ?? [])
      })
      .catch(() => {
        if (current === commentGeneration.current) setComments([])
      })
      .finally(() => {
        if (current === commentGeneration.current) setCommentsLoading(false)
      })
  }, [sampleId, taskId])

  // Prefetch the next page silently so boundary navigation stays fast.
  useEffect(() => {
    if (!nextCursor || loadingMoreRef.current) return
    if (index < samples.length - 5) return
    loadingMoreRef.current = true
    listAdminSamples(taskId, nextCursor)
      .then((data) => {
        setSamples((current) => [...current, ...(data.items ?? [])])
        setNextCursor(data.next_cursor ?? null)
      })
      .catch(() => { /* prefetch failures surface on the next explicit load */ })
      .finally(() => {
        loadingMoreRef.current = false
      })
  }, [index, samples.length, nextCursor, taskId])

  // Flush any pending debounced comment before leaving the page.
  useEffect(() => () => {
    clearTimeout(timerRef.current)
    const armed = armedRef.current
    armedRef.current = null
    if (armed) void saveCommentRef.current(armed.sampleId, armed.content, true)
  }, [])

  function flushArmed() {
    clearTimeout(timerRef.current)
    const armed = armedRef.current
    armedRef.current = null
    if (armed) void saveComment(armed.sampleId, armed.content, true)
  }

  function movePrev() {
    if (index <= 0) return
    flushArmed()
    setIndex(index - 1)
  }

  async function moveNext() {
    if (loadingMoreRef.current) return
    if (index < samples.length - 1) {
      flushArmed()
      setIndex(index + 1)
      return
    }
    if (!nextCursor || !samples.length) return
    flushArmed()
    loadingMoreRef.current = true
    setLoadingMore(true)
    try {
      const data = await listAdminSamples(taskId, nextCursor)
      if (data.items?.length) {
        setSamples((current) => [...current, ...data.items])
        setNextCursor(data.next_cursor ?? null)
        setIndex(index + 1)
      } else {
        setNextCursor(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '样本加载失败')
    } finally {
      loadingMoreRef.current = false
      setLoadingMore(false)
    }
  }

  const moveNextRef = useRef(moveNext)
  moveNextRef.current = moveNext
  const movePrevRef = useRef(movePrev)
  movePrevRef.current = movePrev

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      const editable = Boolean(target) && (
        target !== null && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
      )
      if (editable) return
      if (event.key === 'ArrowLeft') {
        event.preventDefault()
        movePrevRef.current()
      } else if (event.key === 'ArrowRight') {
        event.preventDefault()
        void moveNextRef.current()
      }
    }
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  // Retry (sequentially, to respect the single-flight save lock) drafts that a
  // previous silent save failed to persist, except the one being edited.
  async function retryUnsaved() {
    for (const [sid, content] of Array.from(unsavedRef.current.entries())) {
      if (sid === sampleIdRef.current) continue
      await saveCommentRef.current(sid, content, true)
    }
  }

  function changeDraft(value: string) {
    setDraft(value)
    clearTimeout(timerRef.current)
    if (!sampleId) return
    const trimmed = value.trim()
    if (!trimmed || (lastSavedRef.current.get(sampleId) ?? '') === trimmed) {
      armedRef.current = null
      unsavedRef.current.delete(sampleId)
      return
    }
    unsavedRef.current.set(sampleId, value)
    armedRef.current = { sampleId, content: value }
    timerRef.current = setTimeout(() => {
      const armed = armedRef.current
      armedRef.current = null
      if (armed) void saveComment(armed.sampleId, armed.content)
    }, 800)
  }

  function submitComment() {
    if (!reviewable || savingRef.current) return
    clearTimeout(timerRef.current)
    armedRef.current = null
    if (sampleId) void saveComment(sampleId, draft)
  }

  if (error && !task && !samples.length) {
    return (
      <main className="app-main">
        <div className="queue-header">
          <h2>评审工作区</h2>
        </div>
        <div role="alert" className="error">
          {error}
          <button type="button" onClick={onBack}>返回任务列表</button>
        </div>
      </main>
    )
  }

  const saveHint = !reviewable
    ? '任务未回传，无法批注'
    : saveState === 'saving'
      ? '保存中...'
      : saveState === 'saved'
        ? '已保存'
        : saveState === 'error'
          ? (commentError || '批注保存失败')
          : '停止输入后自动保存'

  return (
    <main className="app-main admin-review">
      <div className="admin-review-header">
        <button type="button" className="admin-back" onClick={onBack}>← 返回任务列表</button>
        <h2 className="admin-review-title">{task?.title ?? '评审工作区'}</h2>
        <span className="admin-review-position">
          样本 {samples.length ? index + 1 : 0} / {total}
        </span>
      </div>

      {error && (
        <div role="alert" className="error">{error}</div>
      )}
      {loading && <p role="status" className="muted">正在加载样本...</p>}
      {!loading && !samples.length && !error && (
        <div className="empty-state">该任务暂无可评审的样本</div>
      )}

      {sample && (
        <>
          <div className="admin-review-nav">
            <button type="button" onClick={movePrev} disabled={index <= 0}>上一条</button>
            <span className="mono admin-sample-id">{sample.sample_id}</span>
            <button type="button" onClick={() => { void moveNext() }} disabled={index >= total - 1 || loadingMore}>
              {loadingMore ? '加载中...' : '下一条'}
            </button>
          </div>

          <section className="field-group highlight admin-sample-data">
            <h4>样本数据</h4>
            <div className="field-grid">
              {Object.entries(sample.values).map(([key, value]) => (
                <div className="field-item" key={key}>
                  <span className="field-item-name">{key}</span>
                  <span className="field-item-value admin-field-value">{formatValue(value)}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="stream-labels admin-labels">
            <h3>标注结果（只读）</h3>
            {columns.length ? (
              <div className="field-grid">
                {columns.map((column) => (
                  <div className="field-item" key={column.machine_key}>
                    <span className="field-item-name">{column.display_name ?? column.machine_key}</span>
                    <span className="field-item-value admin-field-value">
                      {formatValue(sample.labels?.[column.machine_key])}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">该任务未配置标签列。</p>
            )}
          </section>

          <section className="admin-comments">
            <h3>批注</h3>
            <ul className="admin-comment-list">
              {commentsLoading && <li className="muted">正在加载批注...</li>}
              {!commentsLoading && !comments.length && (
                <li className="muted">暂无批注</li>
              )}
              {comments.map((comment) => (
                <li className="admin-comment" key={comment.id}>
                  <div className="admin-comment-meta">
                    <span className="admin-comment-author">{comment.author_name ?? '未知用户'}</span>
                    <span className="muted">{formatTime(comment.created_at)}</span>
                  </div>
                  <p className="admin-comment-body">{comment.content}</p>
                </li>
              ))}
            </ul>
            <div className="admin-comment-input">
              <textarea
                aria-label="批注内容"
                rows={3}
                maxLength={4000}
                placeholder={reviewable ? '输入批注，停止输入后自动保存...' : '任务未回传，无法批注'}
                value={draft}
                disabled={!reviewable}
                onChange={(event) => changeDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                    event.preventDefault()
                    submitComment()
                  }
                }}
              />
              <div className="admin-comment-toolbar">
                <span
                  className={`muted admin-save-hint${saveState === 'error' ? ' is-error' : ''}`}
                  role="status"
                >
                  {saveHint}
                </span>
                <button
                  type="button"
                  className="primary"
                  disabled={!reviewable || saveState === 'saving' || !draft.trim()}
                  onClick={submitComment}
                >
                  添加批注
                </button>
              </div>
            </div>
          </section>
        </>
      )}
    </main>
  )
}
