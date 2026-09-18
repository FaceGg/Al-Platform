import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  bulkLabels,
  confirmTask,
  editForReturn,
  getTask,
  LabelColumn,
  listSamples,
  Sample,
  SampleFilters,
  saveLabels,
  Task,
  returnTask,
} from '../api/tasks'
import { Comment, createComment, listComments } from '../api/comments'

type Conflict = { revision: number; labels: Record<string, unknown> }
type SaveState = 'clean' | 'dirty' | 'saving' | 'saved' | 'error' | 'conflict'
type Drafts = Record<string, Record<string, unknown>>

function conflictFrom(error: unknown): Conflict | null {
  const detail = (error as { response?: { data?: { detail?: Record<string, unknown> } } })?.response?.data?.detail
  if (detail?.code !== 'REVISION_CONFLICT') return null
  return {
    revision: Number(detail.current_revision ?? 0),
    labels: (detail.current_values ?? detail.labels ?? {}) as Record<string, unknown>,
  }
}

function utf8Bytes(value: string) {
  return new TextEncoder().encode(value).length
}

function parseValue(column: LabelColumn, raw: unknown): { value?: unknown; error?: string } {
  if (raw === undefined || raw === null || raw === '') {
    return column.required ? { error: '必填标签不能为空' } : {}
  }
  if (column.value_type === 'string') {
    if (typeof raw !== 'string' || !raw.trim()) return { error: '文本标签不能为空' }
    if (column.max_length !== undefined && utf8Bytes(raw) > column.max_length) return { error: '文本标签超出长度限制' }
    if (column.enum_values?.length && !column.enum_values.some((item) => item === raw)) return { error: '标签不在允许值范围内' }
    return { value: raw }
  }
  const text = String(raw).trim()
  if (column.value_type === 'int') {
    if (!/^[+-]?\d+$/.test(text)) return { error: '请输入十进制整数' }
    try {
      const integer = BigInt(text)
      if (integer < BigInt('-9223372036854775808') || integer > BigInt('9223372036854775807')) return { error: '整数超出范围' }
      const number = Number(integer)
      if (column.min_value !== undefined && integer < BigInt(String(column.min_value))) return { error: '整数低于最小值' }
      if (column.max_value !== undefined && integer > BigInt(String(column.max_value))) return { error: '整数高于最大值' }
      return { value: Number.isSafeInteger(number) ? number : text }
    } catch {
      return { error: '请输入十进制整数' }
    }
  }
  const number = Number(text)
  if (!Number.isFinite(number)) return { error: '请输入有限数值' }
  if (column.min_value !== undefined && number < column.min_value) return { error: '数值低于最小值' }
  if (column.max_value !== undefined && number > column.max_value) return { error: '数值高于最大值' }
  return { value: number }
}

function normalizeDraft(columns: LabelColumn[], draft: Record<string, unknown>) {
  const values: Record<string, unknown> = {}
  let error = ''
  for (const column of columns) {
    const result = parseValue(column, draft[column.machine_key])
    if (result.error && !error) error = `${column.display_name ?? column.machine_key}: ${result.error}`
    if (result.value !== undefined) values[column.machine_key] = result.value
  }
  return { values, error }
}

export default function TaskWorkspacePage({
  taskId,
  assignmentId,
  onBack,
}: {
  taskId: string
  assignmentId?: string
  onBack?: () => void
}) {
  const [task, setTask] = useState<Task | null>(null)
  const [samples, setSamples] = useState<Sample[]>([])
  const [drafts, setDrafts] = useState<Drafts>({})
  const [saveStates, setSaveStates] = useState<Record<string, SaveState>>({})
  const [conflicts, setConflicts] = useState<Record<string, Conflict | null>>({})
  const [conflictOpen, setConflictOpen] = useState<Record<string, boolean>>({})
  const [selected, setSelected] = useState(0)
  const [page, setPage] = useState(0)
  const [pageCursors, setPageCursors] = useState<Array<string | undefined>>([undefined])
  const [nextCursor, setNextCursor] = useState<string | undefined>()
  const [locked, setLocked] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [requiresFreshEdit, setRequiresFreshEdit] = useState(false)
  const [acknowledged, setAcknowledged] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [comments, setComments] = useState<Comment[]>([])
  const [commentText, setCommentText] = useState('')
  const [commentError, setCommentError] = useState('')
  const [commentSaving, setCommentSaving] = useState(false)
  const [commentCursor, setCommentCursor] = useState<string | null>(null)
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentsLoadError, setCommentsLoadError] = useState('')
  const [commentScope, setCommentScope] = useState('sample')
  const [replyTo, setReplyTo] = useState<string | undefined>()
  const [batchIds, setBatchIds] = useState<string[]>([])
  const [batchField, setBatchField] = useState('')
  const [batchValue, setBatchValue] = useState('')
  const [batchOverwrite, setBatchOverwrite] = useState(false)
  const [batchConfirm, setBatchConfirm] = useState(false)
  const [batchSaving, setBatchSaving] = useState(false)
  const [sampleSearch, setSampleSearch] = useState('')
  const [labelStatus, setLabelStatus] = useState<SampleFilters['label_status']>()
  const [commentStatus, setCommentStatus] = useState<SampleFilters['comment_status']>()
  const [modifiedAfter, setModifiedAfter] = useState('')
  const [authorizedField, setAuthorizedField] = useState('')
  const [authorizedValue, setAuthorizedValue] = useState('')
  const sampleFilters = useMemo<SampleFilters>(() => ({
    sample_search: sampleSearch.trim() || undefined, label_status: labelStatus,
    comment_status: commentStatus, modified_after: modifiedAfter || undefined,
    authorized_field: authorizedField || undefined,
    authorized_value: authorizedField ? authorizedValue.trim() || undefined : undefined,
  }), [sampleSearch, labelStatus, commentStatus, modifiedAfter, authorizedField, authorizedValue])
  const sampleFilterArgs = useMemo(
    () => Object.values(sampleFilters).some(Boolean) ? [sampleFilters] as [SampleFilters] : [] as [],
    [sampleFilters],
  )
  const batchSavingRef = useRef(false)
  const commentGeneration = useRef(0)
  const commentPages = useRef(1)
  const commentReading = useRef(false)
  const commentWriting = useRef(false)
  const draftsRef = useRef<Drafts>({})
  const samplesRef = useRef<Sample[]>([])
  const sampleCacheRef = useRef<Map<string, Sample>>(new Map())
  const batchRowsRef = useRef<Map<string, Sample>>(new Map())
  const savingRef = useRef<Record<string, boolean>>({})
  const queuedRef = useRef<Record<string, boolean>>({})
  const debounceVersionRef = useRef<Record<string, number>>({})
  const timersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const requestGeneration = useRef(0)
  const assignmentArgs = useMemo((): [] | [string] => assignmentId ? [assignmentId] : [], [assignmentId])

  const schema = task?.label_schema?.columns ?? []
  const sample = samples[selected]
  const draft = sample ? (drafts[sample.sample_id] ?? sample.labels ?? {}) : {}
  const blockers = useMemo(
    () => batchSaving || Object.values(saveStates).some((state) => ['dirty', 'saving', 'error', 'conflict'].includes(state)),
    [saveStates, batchSaving],
  )
  const normalized = useMemo(() => normalizeDraft(schema, draft), [schema, draft])
  const canSave = Boolean(sample) && !locked && !batchSaving && !savingRef.current[sample?.sample_id ?? ''] && !normalized.error
  const batchColumn = schema.find(column => column.machine_key === batchField) ?? schema[0]
  const batchParsed = batchColumn ? parseValue(batchColumn, batchValue) : { error: '请选择标签列' }

  const replacePage = useCallback((items: Sample[], cursor?: string) => {
    setSamples(items)
    samplesRef.current = items
    for (const item of items) sampleCacheRef.current.set(item.sample_id, item)
    setNextCursor(cursor)
    setSelected(0)
    setBatchConfirm(false)
    setError('')
    for (const item of items) {
      if (!draftsRef.current[item.sample_id]) {
        draftsRef.current = { ...draftsRef.current, [item.sample_id]: { ...item.labels } }
        setDrafts(draftsRef.current)
      }
      setSaveStates((current) => current[item.sample_id] ? current : { ...current, [item.sample_id]: 'clean' })
    }
  }, [])

  const loadPage = useCallback(async (cursor: string | undefined, pageIndex: number) => {
    const generation = ++requestGeneration.current
    const result = await listSamples(taskId, cursor, ...assignmentArgs, ...sampleFilterArgs)
    if (generation !== requestGeneration.current) return
    replacePage(result.items, result.next_cursor)
    setPage(pageIndex)
    setPageCursors((current) => current.slice(0, pageIndex + 1))
  }, [replacePage, taskId, assignmentArgs, sampleFilterArgs])

  useEffect(() => {
    let active = true
    Promise.all([getTask(taskId, ...assignmentArgs), assignmentId ? listSamples(taskId, undefined, assignmentId, ...sampleFilterArgs) : listSamples(taskId, undefined, undefined, ...sampleFilterArgs)])
      .then(([taskData, sampleData]) => {
        if (!active) return
        setTask(taskData)
        setLocked(Boolean(taskData.read_only))
        replacePage(sampleData.items.length ? sampleData.items : taskData.samples ?? [], sampleData.next_cursor)
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : '工作区加载失败')
      })
    return () => { active = false }
  }, [replacePage, taskId, assignmentId, assignmentArgs, sampleFilterArgs])

  const loadComments = useCallback(async (cursor?: string) => {
    if (commentReading.current || commentWriting.current) return
    const generation = ++commentGeneration.current
    commentReading.current = true
    setCommentsLoading(true)
    setCommentsLoadError('')
    try {
      const result = await listComments(taskId, cursor, ...assignmentArgs)
      if (generation !== commentGeneration.current) return
      setComments(current => Array.from(new Map(
        [...(cursor ? current : []), ...(result.items ?? [])].map(item => [item.id, item]),
      ).values()))
      setCommentCursor(result.next_cursor ?? null)
      commentPages.current = cursor ? commentPages.current + 1 : 1
    } catch (err) {
      if (generation === commentGeneration.current) {
        setCommentsLoadError(err instanceof Error ? err.message : '批注加载失败')
      }
    } finally {
      if (generation === commentGeneration.current) {
        commentReading.current = false
        setCommentsLoading(false)
      }
    }
  }, [taskId, assignmentArgs])

  const refreshComments = useCallback(async () => {
    if (document.visibilityState === 'hidden' || commentReading.current || commentWriting.current) return
    const generation = ++commentGeneration.current
    commentReading.current = true
    setCommentsLoading(true)
    try {
      // Reload the visible page window atomically; partial failures preserve it.
      const refreshed: Comment[] = []
      let cursor: string | undefined
      let loaded = 0
      do {
        const result = await listComments(taskId, cursor, ...assignmentArgs)
        if (generation !== commentGeneration.current) return
        refreshed.push(...(result.items ?? []))
        cursor = result.next_cursor ?? undefined
        loaded += 1
      } while (cursor && loaded < commentPages.current)
      setComments(Array.from(new Map(refreshed.map(item => [item.id, item])).values()))
      setCommentCursor(cursor ?? null)
      commentPages.current = loaded
      setCommentsLoadError('')
    } catch (err) {
      if (generation === commentGeneration.current) setCommentsLoadError(err instanceof Error ? err.message : '批注刷新失败')
    } finally {
      if (generation === commentGeneration.current) {
        commentReading.current = false
        setCommentsLoading(false)
      }
    }
  }, [taskId, assignmentArgs])

  useEffect(() => {
    commentReading.current = false
    commentWriting.current = false
    commentPages.current = 1
    setComments([])
    setCommentCursor(null)
    setCommentText('')
    setCommentError('')
    setReplyTo(undefined)
    setCommentSaving(false)
    void loadComments()
    return () => { commentGeneration.current += 1 }
  }, [loadComments])

  useEffect(() => {
    const refresh = () => { void refreshComments() }
    const timer = window.setInterval(refresh, 30_000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [refreshComments])

  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (blockers) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [blockers])

  const save = useCallback(async (sampleId: string, override = false) => {
    if (!task || locked || batchSavingRef.current || savingRef.current[sampleId]) {
      if (savingRef.current[sampleId]) queuedRef.current[sampleId] = true
      return
    }
    const target = samplesRef.current.find((item) => item.sample_id === sampleId)
    if (!target) return
    clearTimeout(timersRef.current[sampleId])
    const currentDraft = draftsRef.current[sampleId] ?? target.labels ?? {}
    const currentConflict = conflicts[sampleId]
    if (currentConflict && !override) {
      setConflictOpen((current) => ({ ...current, [sampleId]: true }))
      return
    }
    const parsed = normalizeDraft(schema, currentDraft)
    if (parsed.error) {
      setSaveStates((current) => ({ ...current, [sampleId]: 'error' }))
      setError(parsed.error)
      return
    }
    const baseRevision = override && currentConflict ? currentConflict.revision : target.revision
    const payload = parsed.values
    savingRef.current[sampleId] = true
    queuedRef.current[sampleId] = false
    setSaveStates((current) => ({ ...current, [sampleId]: 'saving' }))
    setError('')
    try {
      const result = await saveLabels(task.id, sampleId, payload, baseRevision, ...assignmentArgs)
      const latestDraft = draftsRef.current[sampleId] ?? {}
      const stillSame = JSON.stringify(latestDraft) === JSON.stringify(currentDraft)
      const updated = { ...target, labels: result.values ?? payload, revision: result.revision }
      samplesRef.current = samplesRef.current.map((item) => item.sample_id === sampleId ? updated : item)
      setSamples((current) => current.map((item) => item.sample_id === sampleId ? updated : item))
      if (result.task_revision !== undefined) {
        setTask((current) => current ? { ...current, task_revision: result.task_revision ?? current.task_revision } : current)
      }
      setConflicts((current) => ({ ...current, [sampleId]: null }))
      setAcknowledged(false)
      if (stillSame && !queuedRef.current[sampleId]) {
        draftsRef.current = { ...draftsRef.current, [sampleId]: { ...(result.values ?? payload) } }
        setDrafts(draftsRef.current)
        setSaveStates((current) => ({ ...current, [sampleId]: 'saved' }))
        setConfirmed(false)
        setRequiresFreshEdit(false)
        setMessage('标签已保存')
      } else {
        setSaveStates((current) => ({ ...current, [sampleId]: 'dirty' }))
        setConfirmed(false)
      }
    } catch (err) {
      const received = conflictFrom(err)
      if (received) {
        setConflicts((current) => ({ ...current, [sampleId]: received }))
        setConflictOpen((current) => ({ ...current, [sampleId]: true }))
        setSaveStates((current) => ({ ...current, [sampleId]: 'conflict' }))
        setAcknowledged(false)
      } else {
        setSaveStates((current) => ({ ...current, [sampleId]: 'error' }))
        setError(err instanceof Error ? err.message : '保存失败')
      }
    } finally {
      savingRef.current[sampleId] = false
      if (queuedRef.current[sampleId] && !conflicts[sampleId]) {
        queuedRef.current[sampleId] = false
        setTimeout(() => { void save(sampleId) }, 0)
      }
    }
  }, [conflicts, locked, schema, task, assignmentArgs])

  useEffect(() => () => {
    Object.values(timersRef.current).forEach(clearTimeout)
  }, [])

  function updateDraft(sampleId: string, key: string, value: string) {
    const next = { ...draftsRef.current[sampleId], [key]: value }
    draftsRef.current = { ...draftsRef.current, [sampleId]: next }
    setDrafts(draftsRef.current)
    setSaveStates((current) => ({ ...current, [sampleId]: 'dirty' }))
    setConfirmed(false)
    setError('')
    clearTimeout(timersRef.current[sampleId])
    const version = (debounceVersionRef.current[sampleId] ?? 0) + 1
    debounceVersionRef.current[sampleId] = version
    timersRef.current[sampleId] = setTimeout(() => {
      if (debounceVersionRef.current[sampleId] === version) void save(sampleId)
    }, 600)
  }

  function chooseSample(index: number) {
    setSelected(index)
    setMessage('')
    setError('')
    setAcknowledged(false)
  }

  async function confirm() {
    if (!task || locked || blockers || normalized.error || requiresFreshEdit) return
    try {
      await confirmTask(task.id, task.task_revision, task.scope_hash, ...assignmentArgs)
      setConfirmed(true)
      setMessage('任务已确认，可以发起回传')
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认失败')
    }
  }

  async function sendReturn() {
    if (!task || !confirmed || blockers || locked) return
    try {
      await returnTask(task.id, task.task_revision, task.scope_hash, ...assignmentArgs)
      setLocked(true)
      setMessage('回传已提交，等待验收')
    } catch (err) {
      setError(err instanceof Error ? err.message : '回传失败')
    }
  }

  async function unlock() {
    if (!task || blockers) return
    try {
      await editForReturn(task.id, task.task_revision, task.scope_hash, ...assignmentArgs)
      setLocked(false)
      setConfirmed(false)
      setRequiresFreshEdit(true)
      setMessage('已开启新的编辑修订')
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法开启编辑')
    }
  }

  async function addComment() {
    const content = commentText.trim()
    if (!content || commentWriting.current) return
    const generation = ++commentGeneration.current
    commentReading.current = false
    commentWriting.current = true
    setCommentsLoading(false)
    setCommentSaving(true)
    setCommentError('')
    try {
      const sampleId = commentScope === 'sample' ? sample?.sample_id : undefined
      const created = assignmentId || replyTo
        ? (replyTo
          ? await createComment(taskId, content, sampleId, assignmentId, replyTo)
          : await createComment(taskId, content, sampleId, assignmentId))
        : await createComment(taskId, content, sampleId)
      if (generation !== commentGeneration.current) return
      setComments(current => [...current, created])
      setCommentText('')
      setReplyTo(undefined)
    } catch (err) {
      if (generation === commentGeneration.current) setCommentError(err instanceof Error ? err.message : '批注提交失败')
    } finally {
      if (generation === commentGeneration.current) {
        commentWriting.current = false
        setCommentSaving(false)
      }
    }
  }

  async function applyBatch(overwriteConfirmed = false) {
    if (!task || locked || blockers || batchSavingRef.current || !batchColumn || batchParsed.error || !batchIds.length) return
    if (batchOverwrite && !overwriteConfirmed) {
      setBatchConfirm(true)
      return
    }
    setBatchConfirm(false)
    setError('')
    const items: Array<{ sample_id: string; values: Record<string, unknown>; base_revision: number }> = []
    for (const row of batchIds.map(id => sampleCacheRef.current.get(id) ?? batchRowsRef.current.get(id)).filter((item): item is Sample => Boolean(item))) {
      const existing = row.labels[batchColumn.machine_key]
      const existingParsed = parseValue(batchColumn, existing)
      if (!batchOverwrite && existingParsed.value !== undefined && !existingParsed.error) continue
      const values = { ...row.labels }
      if (batchParsed.value === undefined) delete values[batchColumn.machine_key]
      else values[batchColumn.machine_key] = batchParsed.value
      const complete = normalizeDraft(schema, values)
      if (complete.error) {
        setError(`${row.sample_id}: ${complete.error}`)
        return
      }
      items.push({ sample_id: row.sample_id, values: complete.values, base_revision: row.revision })
    }
    if (!items.length) {
      setMessage('所选样本已有合法标签，无需修改')
      return
    }
    batchSavingRef.current = true
    setBatchSaving(true)
    setConfirmed(false)
    try {
      const result = await bulkLabels(task.id, items, ...assignmentArgs)
      const updated = new Map(result.items.map(item => [item.sample_id, item]))
      for (const [id, saved] of updated) {
        const cached = sampleCacheRef.current.get(id)
        if (cached) sampleCacheRef.current.set(id, { ...cached, labels: saved.values, revision: saved.revision })
      }
      samplesRef.current = samplesRef.current.map(row => sampleCacheRef.current.get(row.sample_id) ?? row)
      setSamples(samplesRef.current)
      for (const item of result.items) {
        draftsRef.current[item.sample_id] = { ...item.values }
      }
      setDrafts({ ...draftsRef.current })
      setSaveStates(current => ({ ...current, ...Object.fromEntries(result.items.map(item => [item.sample_id, 'saved' as const])) }))
      setRequiresFreshEdit(false)
      setBatchOverwrite(false)
      setMessage(`已保存 ${result.items.length} 条样本`)
    } catch (err) {
      const conflict = conflictFrom(err)
      const detail = (err as { response?: { data?: { detail?: { sample_id?: string } } } })?.response?.data?.detail
      if (conflict && detail?.sample_id) {
        const id = detail.sample_id
        const attempted = items.find(item => item.sample_id === id)
        if (attempted) {
          draftsRef.current[id] = { ...attempted.values }
          setDrafts({ ...draftsRef.current })
          setConflicts(current => ({ ...current, [id]: conflict }))
          setSaveStates(current => ({ ...current, [id]: 'conflict' }))
          setConflictOpen(current => ({ ...current, [id]: true }))
          setAcknowledged(false)
          setSelected(samplesRef.current.findIndex(item => item.sample_id === id))
        }
        setError('批量保存存在版本冲突，整批未写入')
      } else {
        setError(err instanceof Error ? err.message : '批量保存失败')
      }
    } finally {
      batchSavingRef.current = false
      setBatchSaving(false)
    }
  }

  if (error && !task) return <main className="portal-page"><p className="error">{error}</p></main>

  return (
    <main className="portal-page workspace">
      <header className="topbar">
        <div>
          <button className="back" disabled={blockers} onClick={onBack}>返回任务</button>
          <p className="eyebrow">ANNOTATOR PORTAL</p>
          <h1>{task?.title ?? '加载中...'}</h1>
          {task?.instructions && <p className="muted">{task.instructions}</p>}
        </div>
        <div className="status">{locked ? '回传后只读' : task?.status ?? ''}</div>
      </header>
      {error && <p className="error">{error}</p>}
      {message && <p className="success">{message}</p>}
      <div className="workspace-grid">
        <aside className="sample-list">
          <h2>样本</h2>
          <input aria-label="搜索样本" placeholder="搜索样本 ID" value={sampleSearch} disabled={blockers}
           onChange={event => setSampleSearch(event.target.value)} />
          <select aria-label="授权字段" value={authorizedField} disabled={blockers}
            onChange={event => { setAuthorizedField(event.target.value); setAuthorizedValue('') }}>
            <option value="">全部授权字段</option>
            {(task?.visible_columns ?? []).map(field => <option key={field} value={field}>{field}</option>)}
          </select>
          <input aria-label="授权字段值" placeholder="输入字段值" value={authorizedValue}
            disabled={blockers || !authorizedField} onChange={event => setAuthorizedValue(event.target.value)} />
          <select aria-label="标签完成状态" value={labelStatus ?? ''} disabled={blockers}
            onChange={event => setLabelStatus((event.target.value || undefined) as SampleFilters['label_status'])}>
            <option value="">全部标签状态</option><option value="complete">标签完整</option><option value="incomplete">标签未完整</option>
          </select>
          <select aria-label="批注状态筛选" value={commentStatus ?? ''} disabled={blockers}
            onChange={event => setCommentStatus((event.target.value || undefined) as SampleFilters['comment_status'])}>
            <option value="">全部批注状态</option><option value="open">有待处理批注</option><option value="resolved">有已解决批注</option><option value="none">无批注</option>
          </select>
          <select aria-label="最近修改时间" value={modifiedAfter} disabled={blockers}
            onChange={event => setModifiedAfter(event.target.value)}>
            <option value="">全部修改时间</option><option value={new Date(Date.now() - 86400000).toISOString()}>最近 24 小时</option><option value={new Date(Date.now() - 7 * 86400000).toISOString()}>最近 7 天</option>
          </select>
          <label className="check"><input type="checkbox" aria-label="选择当前页全部样本" disabled={locked || batchSaving || !samples.length}
            checked={samples.length > 0 && samples.every(item => batchIds.includes(item.sample_id))}
            onChange={event => {
              if (event.target.checked) {
                for (const item of samples) batchRowsRef.current.set(item.sample_id, item)
                setBatchIds(current => Array.from(new Set([...current, ...samples.map(item => item.sample_id)])))
              } else {
                for (const item of samples) batchRowsRef.current.delete(item.sample_id)
                setBatchIds(current => current.filter(id => !samples.some(item => item.sample_id === id)))
              }
            }} />全选当前页</label>
          {samples.map((item, index) => (
            <div className="sample-selection" key={item.sample_id}>
            <input type="checkbox" aria-label={`选择样本 ${item.sample_id}`} disabled={locked || batchSaving}
              checked={batchIds.includes(item.sample_id)}
              onChange={event => {
                if (event.target.checked) batchRowsRef.current.set(item.sample_id, item)
                else batchRowsRef.current.delete(item.sample_id)
                setBatchIds(current => event.target.checked
                  ? Array.from(new Set([...current, item.sample_id]))
                  : current.filter(id => id !== item.sample_id))
              }} />
            <button
              className={index === selected ? 'sample-item active' : 'sample-item'}
              key={item.sample_id}
              onClick={() => chooseSample(index)}
            >
              {index + 1}. {item.sample_id}
            </button>
            </div>
          ))}
          <div className="pagination">
            <button
              disabled={blockers || page === 0}
              onClick={() => void loadPage(pageCursors[page - 1], page - 1)}
            >上一页</button>
            <span>第 {page + 1} 页</span>
            <button
              disabled={blockers || !nextCursor}
              onClick={() => {
                const cursor = nextCursor
                setPageCursors((current) => [...current.slice(0, page + 1), cursor])
                void loadPage(cursor, page + 1)
              }}
            >下一页</button>
          </div>
        </aside>
        <section className="editor">
          <div className="sample-header"><h2>标签编辑</h2><span>修订 {sample?.revision ?? 0}</span></div>
          {sample && (
            <>
              <div className="values">
                <h3>数据</h3>
                {Object.entries(sample.values).map(([key, value]) => (
                  <p key={key}><strong>{key}</strong><span>{String(value)}</span></p>
                ))}
              </div>
              <div className="labels">
                <h3>标签</h3>
                {schema.map((column) => {
                  const value = draft[column.machine_key]
                  const common = {
                    'aria-label': `${column.machine_key}-${sample.sample_id}`,
                    disabled: locked || batchSaving,
                    value: String(value ?? ''),
                    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
                      updateDraft(sample.sample_id, column.machine_key, event.target.value),
                  }
                  return (
                    <label key={column.machine_key}>
                      {column.display_name ?? column.machine_key}
                      {column.enum_values?.length ? (
                        <select {...common}>
                          <option value="">请选择</option>
                          {column.enum_values.map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}
                        </select>
                      ) : (
                        <input
                          {...common}
                          type={column.value_type === 'string' ? 'text' : 'number'}
                          step={column.value_type === 'float' ? 'any' : '1'}
                        />
                      )}
                    </label>
                  )
                })}
              </div>
              <button className="primary" disabled={!canSave} onClick={() => void save(sample.sample_id)}>保存标签</button>
              {saveStates[sample.sample_id] === 'saving' && <p className="muted">保存中...</p>}
              {saveStates[sample.sample_id] === 'saved' && <p className="success">已保存</p>}
              {saveStates[sample.sample_id] === 'error' && <p className="error">保存失败，请重试</p>}
            </>
          )}
          <section className="batch-editor" aria-label="批量编辑">
            <h2>批量编辑</h2>
            <p>已选择 {batchIds.length} 条样本</p>
            <label>标签列<select aria-label="批量标签列" disabled={locked || batchSaving} value={batchColumn?.machine_key ?? ''}
              onChange={event => { setBatchField(event.target.value); setBatchValue(''); setBatchConfirm(false) }}>
              {schema.map(column => <option key={column.machine_key} value={column.machine_key}>{column.display_name ?? column.machine_key}</option>)}
            </select></label>
            <label>标签值{batchColumn?.enum_values?.length ? (
              <select aria-label="批量标签值" disabled={locked || batchSaving} value={batchValue} onChange={event => setBatchValue(event.target.value)}>
                <option value="">请选择</option>
                {batchColumn.enum_values.map(value => <option key={String(value)} value={String(value)}>{String(value)}</option>)}
              </select>
            ) : <input aria-label="批量标签值" disabled={locked || batchSaving} value={batchValue}
              type={batchColumn?.value_type === 'string' ? 'text' : 'number'} step={batchColumn?.value_type === 'float' ? 'any' : '1'}
              onChange={event => setBatchValue(event.target.value)} />}</label>
            <label className="check"><input type="checkbox" aria-label="覆盖已有合法标签" disabled={locked || batchSaving}
              checked={batchOverwrite} onChange={event => setBatchOverwrite(event.target.checked)} />覆盖已有合法标签</label>
            {batchParsed.error && batchValue && <p className="error">{batchParsed.error}</p>}
            <button disabled={locked || blockers || !batchIds.length || Boolean(batchParsed.error)}
              onClick={() => void applyBatch()}>应用到所选样本</button>
            {batchSaving && <p role="status">批量保存中...</p>}
          </section>
        </section>
        <aside className="actions">
          <h2>回传</h2>
          <p className="muted">保存完整标签后确认当前任务修订，再发起回传。</p>
          <button disabled={locked || blockers || normalized.error !== '' || requiresFreshEdit} onClick={confirm}>确认任务</button>
          <button className="primary" disabled={locked || blockers || !confirmed} onClick={sendReturn}>发起回传</button>
          {locked && <button disabled={blockers} onClick={unlock}>编辑后回传</button>}
          <h2>批注</h2>
          <div className="comments" aria-label="批注列表">
            {comments.filter(item => !item.parent_id && (!item.sample_id || item.sample_id === sample?.sample_id)).map(item => (
              <article key={item.id} className="comment-thread">
                <p>{item.content}</p>
                <span className="muted">{item.sample_id ? `样本 ${item.sample_id}` : '任务批注'} · {item.status === 'resolved' ? '已解决' : '待处理'}</span>
                <button type="button" disabled={commentSaving} onClick={() => { setReplyTo(item.id); setCommentScope(item.sample_id ? 'sample' : 'task') }}>回复</button>
                {comments.filter(reply => reply.parent_id === item.id).map(reply => (
                  <div className="comment-reply" key={reply.id}>
                    <p>{reply.content}</p>
                    <span className="muted">{reply.status === 'resolved' ? '已解决' : '待处理'}</span>
                  </div>
                ))}
              </article>
            ))}
          </div>
          {commentsLoading && <p role="status">批注加载中...</p>}
          {commentsLoadError && <p role="alert" className="error">{commentsLoadError}</p>}
          {(commentCursor || commentsLoadError) && (
            <button disabled={commentsLoading} onClick={() => void loadComments(commentCursor ?? undefined)}>
              {commentCursor ? '加载更多批注' : '重试加载批注'}
            </button>
          )}
          {commentError && <p role="alert" className="error">{commentError}</p>}
          <select aria-label="批注范围" value={commentScope} disabled={commentSaving} onChange={event => setCommentScope(event.target.value)}>
            <option value="sample">当前样本</option>
            <option value="task">整个任务</option>
          </select>
          <textarea aria-label="新增批注" value={commentText} maxLength={2000} disabled={commentSaving} onChange={event => setCommentText(event.target.value)} />
          {replyTo && <p className="muted">正在回复批注 <button type="button" onClick={() => setReplyTo(undefined)}>取消回复</button></p>}
          <button disabled={commentSaving || !commentText.trim() || (commentScope === 'sample' && !sample)} onClick={() => void addComment()}>添加批注</button>
        </aside>
      </div>
      {batchConfirm && <div className="dialog" role="dialog" aria-label="批量覆盖确认"><section>
        <h2>确认覆盖 {batchIds.length} 条样本的标签</h2>
        <p>{batchColumn?.display_name ?? batchColumn?.machine_key}: {batchValue || '空值'}</p>
        <div className="dialog-actions"><button onClick={() => setBatchConfirm(false)}>取消覆盖</button>
          <button disabled={blockers || locked} onClick={() => void applyBatch(true)}>确认批量覆盖</button></div>
      </section></div>}
      {conflictOpen[sample?.sample_id ?? ''] && conflicts[sample?.sample_id ?? ''] && (
        <div className="dialog" role="dialog" aria-label="版本冲突">
          <section>
            <h2>版本冲突</h2>
            <p>服务器已有较新的完整标签集合。核对后才能使用当前修订覆盖。</p>
            <pre>{JSON.stringify(conflicts[sample?.sample_id ?? '']?.labels, null, 2)}</pre>
            <label className="check">
              <input
                type="checkbox"
                aria-label="我已核对完整标签集合"
                checked={acknowledged}
                onChange={(event) => setAcknowledged(event.target.checked)}
              />
              我已核对完整标签集合
            </label>
            <div className="dialog-actions">
              <button onClick={() => setConflictOpen((current) => ({ ...current, [sample?.sample_id ?? '']: false }))}>取消</button>
              <button
                className="primary"
                disabled={!acknowledged}
                onClick={() => sample && void save(sample.sample_id, true)}
              >确认并覆盖完整标签</button>
            </div>
          </section>
        </div>
      )}
    </main>
  )
}
