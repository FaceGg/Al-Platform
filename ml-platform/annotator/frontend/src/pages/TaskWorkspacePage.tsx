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
import GuidelinePanel from '../components/GuidelinePanel'
import SampleStream, { NumberedOption } from '../components/SampleStream'
import ShortcutHelp from '../components/ShortcutHelp'

type Conflict = { revision: number; labels: Record<string, unknown> }
type SaveState = 'clean' | 'dirty' | 'saving' | 'saved' | 'error' | 'conflict'
type Drafts = Record<string, Record<string, unknown>>
type UndoEntry = { sampleId: string; key: string; previous: unknown }
type WorkspaceTab = 'guide' | 'samples' | 'batch' | 'return' | 'comments'

const workspaceTabs: Array<{
  key: WorkspaceTab
  label: string
  icon: JSX.Element
}> = [
  {
    key: 'guide',
    label: '指南',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
      </svg>
    ),
  },
  {
    key: 'samples',
    label: '样本',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7" />
        <rect x="14" y="3" width="7" height="7" />
        <rect x="14" y="14" width="7" height="7" />
        <rect x="3" y="14" width="7" height="7" />
      </svg>
    ),
  },
  {
    key: 'batch',
    label: '批量',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
      </svg>
    ),
  },
  {
    key: 'return',
    label: '回传',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
        <path d="M3 3v5h5" />
      </svg>
    ),
  },
  {
    key: 'comments',
    label: '批注',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    ),
  },
]

function apiErrorCode(error: unknown): string | undefined {
  return (error as { response?: { data?: { detail?: { code?: string } } } })?.response?.data?.detail?.code
}

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
    if (column.max_length != null && utf8Bytes(raw) > column.max_length) return { error: '文本标签超出长度限制' }
    if (column.enum_values?.length && !column.enum_values.some((item) => item === raw)) return { error: '标签不在允许值范围内' }
    return { value: raw }
  }
  const text = String(raw).normalize('NFKC').trim()
  if (column.value_type === 'int') {
    if (!/^[+-]?\d+$/.test(text)) return { error: '请输入十进制整数' }
    try {
      const integer = BigInt(text)
      if (integer < BigInt('-9223372036854775808') || integer > BigInt('9223372036854775807')) return { error: '整数超出范围' }
      const number = Number(integer)
      if (column.min_value != null && integer < BigInt(String(column.min_value))) return { error: '整数低于最小值' }
      if (column.max_value != null && integer > BigInt(String(column.max_value))) return { error: '整数高于最大值' }
      return { value: Number.isSafeInteger(number) ? number : text }
    } catch {
      return { error: '请输入十进制整数' }
    }
  }
  const number = Number(text)
  if (!Number.isFinite(number)) return { error: '请输入有限数值' }
  if (column.min_value != null && number < column.min_value) return { error: '数值低于最小值' }
  if (column.max_value != null && number > column.max_value) return { error: '数值高于最大值' }
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
  const [taskMissing, setTaskMissing] = useState(false)
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
  const [openPanels, setOpenPanels] = useState<Record<WorkspaceTab, boolean>>({
    guide: true,
    samples: false,
    batch: false,
    return: false,
    comments: false,
  })
  const [batchSamples, setBatchSamples] = useState<Sample[]>([])
  const [batchPage, setBatchPage] = useState(0)
  const [batchPageCursors, setBatchPageCursors] = useState<Array<string | undefined>>([undefined])
  const [batchNextCursor, setBatchNextCursor] = useState<string | undefined>()
  const batchGeneration = useRef(0)
  const [helpOpen, setHelpOpen] = useState(false)
  const [streamCompleted, setStreamCompleted] = useState(0)
  const [summaryOpen, setSummaryOpen] = useState(false)
  const [exitConfirmOpen, setExitConfirmOpen] = useState(false)
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
  const advanceTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const undoStackRef = useRef<UndoEntry[]>([])
  const loadingNextRef = useRef(false)
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
  const numberedOptions = useMemo<NumberedOption[]>(
    () => schema
      .flatMap(column => (column.enum_values ?? []).map(value => ({ column, value: String(value) })))
      .slice(0, 9)
      .map((entry, offset) => ({ ...entry, index: offset + 1 })),
    [schema],
  )

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
    setTaskMissing(false)
    setPage(0)
    setPageCursors([undefined])
    setBatchPage(0)
    setBatchPageCursors([undefined])
    Promise.all([getTask(taskId, ...assignmentArgs), assignmentId ? listSamples(taskId, undefined, assignmentId, ...sampleFilterArgs) : listSamples(taskId, undefined, undefined, ...sampleFilterArgs)])
      .then(([taskData, sampleData]) => {
        if (!active) return
        setTask(taskData)
        setLocked(Boolean(taskData.read_only))
        const items = sampleData.items.length ? sampleData.items : taskData.samples ?? []
        replacePage(items, sampleData.next_cursor)
        setBatchSamples(items)
        setBatchNextCursor(sampleData.next_cursor)
      })
      .catch((err) => {
        if (!active) return
        // Deep links (?task=) survive browser refresh; if the task has since
        // been deleted, show a friendly fallback instead of a raw error code.
        const status = (err as { response?: { status?: number } })?.response?.status
        if (status === 404) setTaskMissing(true)
        setError(err instanceof Error ? err.message : '工作区加载失败')
      })
    return () => { active = false }
  }, [replacePage, taskId, assignmentId, assignmentArgs, sampleFilterArgs])

  const loadBatchPage = useCallback(async (cursor: string | undefined, pageIndex: number) => {
    const generation = ++batchGeneration.current
    const result = await listSamples(taskId, cursor, ...assignmentArgs, ...sampleFilterArgs)
    if (generation !== batchGeneration.current) return
    setBatchSamples(result.items)
    for (const item of result.items) batchRowsRef.current.set(item.sample_id, item)
    setBatchNextCursor(result.next_cursor)
    setBatchPage(pageIndex)
  }, [taskId, assignmentArgs, sampleFilterArgs])

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

  // Refresh task-wide progress counters (best-effort, silent on failure).
  const refreshTaskStats = useCallback(() => {
    getTask(taskId, ...assignmentArgs)
      .then((data) => {
        setTask((current) => current ? {
          ...current,
          completed_samples: data.completed_samples,
          total_samples: data.total_samples,
        } : current)
      })
      .catch(() => { /* ignore */ })
  }, [taskId, assignmentArgs])

  const save = useCallback(async (sampleId: string, override = false): Promise<boolean> => {
    if (!task || locked || batchSavingRef.current || savingRef.current[sampleId]) {
      if (savingRef.current[sampleId]) queuedRef.current[sampleId] = true
      return false
    }
    const target = samplesRef.current.find((item) => item.sample_id === sampleId) ?? sampleCacheRef.current.get(sampleId)
    if (!target) return false
    clearTimeout(timersRef.current[sampleId])
    const currentDraft = draftsRef.current[sampleId] ?? target.labels ?? {}
    const currentConflict = conflicts[sampleId]
    if (currentConflict && !override) {
      setConflictOpen((current) => ({ ...current, [sampleId]: true }))
      return false
    }
    const parsed = normalizeDraft(schema, currentDraft)
    if (parsed.error) {
      setSaveStates((current) => ({ ...current, [sampleId]: 'error' }))
      setError(parsed.error)
      return false
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
        refreshTaskStats()
      } else {
        setSaveStates((current) => ({ ...current, [sampleId]: 'dirty' }))
        setConfirmed(false)
      }
      return true
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
      return false
    } finally {
      savingRef.current[sampleId] = false
      if (queuedRef.current[sampleId] && !conflicts[sampleId]) {
        queuedRef.current[sampleId] = false
        setTimeout(() => { void save(sampleId) }, 0)
      }
    }
  }, [conflicts, locked, schema, task, assignmentArgs, refreshTaskStats])

  useEffect(() => () => {
    Object.values(timersRef.current).forEach(clearTimeout)
    clearTimeout(advanceTimerRef.current)
  }, [])

  function commitDraft(sampleId: string, key: string, value: string | undefined, recordUndo: boolean) {
    const currentDraft = draftsRef.current[sampleId] ?? {}
    if (recordUndo) {
      undoStackRef.current.push({ sampleId, key, previous: currentDraft[key] })
      if (undoStackRef.current.length > 20) undoStackRef.current.shift()
    }
    const next = { ...currentDraft }
    if (value === undefined || value === null) delete next[key]
    else next[key] = value
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

  function updateDraft(sampleId: string, key: string, value: string) {
    commitDraft(sampleId, key, value, true)
  }

  function undoLabelChange() {
    const entry = undoStackRef.current.pop()
    if (!entry) return
    commitDraft(entry.sampleId, entry.key, entry.previous === undefined ? undefined : String(entry.previous), false)
  }

  function toggleOption(column: LabelColumn, optionValue: string) {
    if (!sample || locked || batchSaving) return
    const current = draft[column.machine_key]
    updateDraft(sample.sample_id, column.machine_key, current === optionValue ? '' : optionValue)
  }

  function chooseSample(index: number) {
    setSelected(index)
    setMessage('')
    setError('')
    setAcknowledged(false)
  }

  function moveNext() {
    if (!samples.length) return
    if (selected < samples.length - 1) {
      chooseSample(selected + 1)
    } else if (nextCursor && !loadingNextRef.current) {
      loadingNextRef.current = true
      setPageCursors((current) => [...current.slice(0, page + 1), nextCursor])
      loadPage(nextCursor, page + 1).finally(() => { loadingNextRef.current = false })
    }
  }

  function movePrev() {
    if (selected > 0) {
      chooseSample(selected - 1)
    } else if (page > 0) {
      void loadPage(pageCursors[page - 1], page - 1)
    }
  }

  function advanceStream() {
    if (summaryOpen) return
    if (!samples.length) return
    if (selected < samples.length - 1) {
      chooseSample(selected + 1)
    } else if (nextCursor) {
      setPageCursors((current) => [...current.slice(0, page + 1), nextCursor])
      void loadPage(nextCursor, page + 1)
    } else {
      setSummaryOpen(true)
    }
  }

  async function saveAndAdvance() {
    if (!sample) return
    const saved = await save(sample.sample_id)
    if (!saved) return
    setStreamCompleted((count) => count + 1)
    clearTimeout(advanceTimerRef.current)
    advanceTimerRef.current = setTimeout(() => { streamApiRef.current.advance() }, 600)
  }

  function restartStream() {
    setSummaryOpen(false)
    setStreamCompleted(0)
    chooseSample(0)
  }

  function openSamplesPanel() {
    setSummaryOpen(false)
    setOpenPanels(prev => ({ ...prev, samples: true }))
  }

  function togglePanel(key: WorkspaceTab) {
    setOpenPanels(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const streamApiRef = useRef({ advance: advanceStream, moveNext, movePrev })
  streamApiRef.current = { advance: advanceStream, moveNext, movePrev }

  function requestBack() {
    if (batchSaving) return
    const unsaved = Object.values(saveStates).some((state) => ['dirty', 'saving', 'error', 'conflict'].includes(state))
    if (!unsaved) {
      onBack?.()
      return
    }
    for (const [id, state] of Object.entries(saveStates)) {
      if (state === 'dirty') void save(id)
    }
    setExitConfirmOpen(true)
  }

  async function confirm() {
    if (!task || locked || blockers || normalized.error || requiresFreshEdit) return
    // Flush debounced edits before confirming: a save that lands after the
    // confirm silently invalidates it (the backend resets the task to
    // in_progress and rejects the return with ANNOTATION_NOT_READY).
    for (const [id, state] of Object.entries(saveStates)) {
      if (state !== 'dirty') continue
      clearTimeout(timersRef.current[id])
      const flushed = await save(id)
      if (!flushed) return
    }
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
    const submit = () => returnTask(task.id, task.task_revision, task.scope_hash, ...assignmentArgs)
    try {
      await submit()
      setLocked(true)
      setMessage('回传已提交，等待验收')
    } catch (err) {
      // A save that raced with the confirmation leaves the backend task in
      // in_progress; re-confirm the current revision and retry the return
      // instead of surfacing a cryptic "whole task scope" error.
      if (apiErrorCode(err) === 'ANNOTATION_NOT_READY') {
        try {
          await confirmTask(task.id, task.task_revision, task.scope_hash, ...assignmentArgs)
          await submit()
          setLocked(true)
          setMessage('检测到确认后有新的修改，已自动重新确认并发起回传')
          return
        } catch (retryError) {
          const code = apiErrorCode(retryError)
          setError(code === 'ANNOTATION_NOT_READY'
            ? '任务范围尚未全部确认：请检查所有样本已保存合法标签后，重新点击「确认任务」'
            : (retryError instanceof Error ? retryError.message : '回传失败'))
          return
        }
      }
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
      refreshTaskStats()
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

  const handleShortcut = (event: KeyboardEvent) => {
    const target = event.target as HTMLElement | null
    const editable = Boolean(target) && (
      target !== null && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
    )
    const inLabelInput = target instanceof HTMLElement && target.getAttribute('data-label-input') === 'true'
    if (event.key === 'Escape') {
      if (helpOpen) {
        event.preventDefault()
        setHelpOpen(false)
      } else if (inLabelInput) {
        // Esc 让光标离开标签框，恢复数字快捷选项等全局快捷键
        event.preventDefault()
        target.blur()
      }
      return
    }
    if (helpOpen) return
    if (event.key === 'F1' || event.key === '?') {
      if (editable) return
      event.preventDefault()
      setHelpOpen(true)
      return
    }
    if (inLabelInput && event.key === 'Enter' && !event.ctrlKey && !event.metaKey && !event.altKey) {
      // 标签框内按 Enter 同样保存并进入下一样本，切换后光标自动回到标签框
      event.preventDefault()
      void saveAndAdvance()
      return
    }
    if (editable || !sample) return
    if ((event.ctrlKey || event.metaKey) && !event.altKey && (event.key === 'z' || event.key === 'Z')) {
      event.preventDefault()
      undoLabelChange()
      return
    }
    if (event.repeat) {
      if (event.key === 'Enter' || event.key === ' ') event.preventDefault()
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      void saveAndAdvance()
      return
    }
    if (event.key === ' ') {
      event.preventDefault()
      streamApiRef.current.moveNext()
      return
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      streamApiRef.current.movePrev()
      return
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      streamApiRef.current.moveNext()
      return
    }
    if (/^[1-9]$/.test(event.key)) {
      const option = numberedOptions[Number(event.key) - 1]
      if (option) {
        event.preventDefault()
        toggleOption(option.column, option.value)
      }
    }
  }
  const shortcutHandlerRef = useRef(handleShortcut)
  shortcutHandlerRef.current = handleShortcut
  useEffect(() => {
    const listener = (event: KeyboardEvent) => shortcutHandlerRef.current(event)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  if (error && !task) {
    // Task deleted (or inaccessible) after a refresh on a deep-linked workspace:
    // fall back to a friendly page instead of a raw ANNOTATION_TASK_NOT_FOUND.
    return (
      <main className="portal-page">
        <div className="queue-header">
          <h2>标注工作区</h2>
        </div>
        <div role="alert" className="error">
          {taskMissing ? '任务不存在或已被删除，无法打开标注工作区' : (error || '工作区加载失败')}
          <button type="button" className="primary" onClick={() => onBack?.()}>返回任务列表</button>
        </div>
      </main>
    )
  }

  const statusLabel = locked ? '回传后只读' : task?.status ?? ''
  const labeledCount = samples.filter((item) => ['clean', 'saved'].includes(saveStates[item.sample_id] ?? '')).length
  // Task-wide counters: fall back to local page stats until the task detail loads.
  const totalSamples = task?.total_samples ?? samples.length
  const completedCount = task?.completed_samples ?? labeledCount
  const globalPosition = page * 50 + selected + 1

  const renderPanel = (key: WorkspaceTab) => {
    if (key === 'guide') {
      return <GuidelinePanel instructions={task?.instructions} schema={task?.label_schema} />
    }
    if (key === 'samples') {
      return (
        <>
          <section>
            <h3>样本筛选</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
              <input
                aria-label="搜索样本"
                placeholder="搜索样本 ID"
                value={sampleSearch}
                disabled={locked || batchSaving}
                onChange={(event) => setSampleSearch(event.target.value)}
              />
              <select
                aria-label="授权字段"
                value={authorizedField}
                disabled={locked || batchSaving}
                onChange={(event) => { setAuthorizedField(event.target.value); setAuthorizedValue('') }}
              >
                <option value="">全部授权字段</option>
                {(task?.visible_columns ?? []).map((field) => (
                  <option key={field} value={field}>{field}</option>
                ))}
              </select>
              <input
                aria-label="授权字段值"
                placeholder="输入字段值"
                value={authorizedValue}
                disabled={locked || batchSaving || !authorizedField}
                onChange={(event) => setAuthorizedValue(event.target.value)}
              />
              <select
                aria-label="标签完成状态"
                value={labelStatus ?? ''}
                disabled={locked || batchSaving}
                onChange={(event) => setLabelStatus((event.target.value || undefined) as SampleFilters['label_status'])}
              >
                <option value="">全部标签状态</option>
                <option value="complete">标签完整</option>
                <option value="incomplete">标签未完整</option>
              </select>
              <select
                aria-label="批注状态筛选"
                value={commentStatus ?? ''}
                disabled={locked || batchSaving}
                onChange={(event) => setCommentStatus((event.target.value || undefined) as SampleFilters['comment_status'])}
              >
                <option value="">全部批注状态</option>
                <option value="open">有待处理批注</option>
                <option value="resolved">有已解决批注</option>
                <option value="none">无批注</option>
              </select>
              <select
                aria-label="最近修改时间"
                value={modifiedAfter}
                disabled={locked || batchSaving}
                onChange={(event) => setModifiedAfter(event.target.value)}
              >
                <option value="">全部修改时间</option>
                <option value={new Date(Date.now() - 86400000).toISOString()}>最近 24 小时</option>
                <option value={new Date(Date.now() - 7 * 86400000).toISOString()}>最近 7 天</option>
              </select>
            </div>
          </section>
          <section>
            <h3>分页</h3>
            <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
              <button
                style={{ flex: 1 }}
                disabled={locked || batchSaving || page === 0}
                onClick={() => void loadPage(pageCursors[page - 1], page - 1)}
              >上一页</button>
              <span className="muted">第 {page + 1} 页</span>
              <button
                style={{ flex: 1 }}
                disabled={locked || batchSaving || !nextCursor}
                onClick={() => {
                  const cursor = nextCursor
                  setPageCursors((current) => [...current.slice(0, page + 1), cursor])
                  void loadPage(cursor, page + 1)
                }}
              >下一页</button>
            </div>
          </section>
        </>
      )
    }
    if (key === 'batch') {
      return (
        <>
          <section>
            <h3>批量编辑</h3>
            <p className="muted" style={{ marginBottom: 'var(--space-3)' }}>
              选择样本并批量应用标签值。
            </p>
            <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', marginBottom: 'var(--space-3)' }}>
              <button
                style={{ flex: 1 }}
                disabled={locked || batchSaving || batchPage === 0}
                onClick={() => {
                  setBatchPageCursors((current) => current.slice(0, batchPage + 1))
                  void loadBatchPage(batchPageCursors[batchPage - 1], batchPage - 1)
                }}
              >上一页</button>
              <span className="muted">第 {batchPage + 1} 页</span>
              <button
                style={{ flex: 1 }}
                disabled={locked || batchSaving || !batchNextCursor}
                onClick={() => {
                  const cursor = batchNextCursor
                  setBatchPageCursors((current) => [...current.slice(0, batchPage + 1), cursor])
                  void loadBatchPage(cursor, batchPage + 1)
                }}
              >下一页</button>
            </div>
            <label className="check" style={{ marginBottom: 'var(--space-3)' }}>
              <input
                type="checkbox"
                aria-label="选择当前页全部样本"
                disabled={locked || batchSaving || !batchSamples.length}
                checked={batchSamples.length > 0 && batchSamples.every((item) => batchIds.includes(item.sample_id))}
                onChange={(event) => {
                  if (event.target.checked) {
                    for (const item of batchSamples) batchRowsRef.current.set(item.sample_id, item)
                    setBatchIds((current) => Array.from(new Set([...current, ...batchSamples.map((item) => item.sample_id)])))
                  } else {
                    for (const item of batchSamples) batchRowsRef.current.delete(item.sample_id)
                    setBatchIds((current) => current.filter((id) => !batchSamples.some((item) => item.sample_id === id)))
                  }
                }}
              />
              全选当前页
            </label>
            <div style={{ maxHeight: '200px', overflowY: 'auto', marginBottom: 'var(--space-3)' }}>
              {batchSamples.map((item) => (
                <label className="check" key={item.sample_id} style={{ marginBottom: 'var(--space-2)' }}>
                  <input
                    type="checkbox"
                    aria-label={`选择样本 ${item.sample_id}`}
                    disabled={locked || batchSaving}
                    checked={batchIds.includes(item.sample_id)}
                    onChange={(event) => {
                      if (event.target.checked) batchRowsRef.current.set(item.sample_id, item)
                      else batchRowsRef.current.delete(item.sample_id)
                      setBatchIds((current) => event.target.checked
                        ? Array.from(new Set([...current, item.sample_id]))
                        : current.filter((id) => id !== item.sample_id))
                    }}
                  />
                  <span className="muted" style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                    {item.sample_id}
                  </span>
                </label>
              ))}
              {!batchSamples.length && <p className="muted">当前没有可选择的样本</p>}
            </div>
            <p className="muted">已选择 {batchIds.length} 条样本</p>
          </section>
          <section>
            <h3>标签设置</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
              <label>
                标签列
                <select
                  aria-label="批量标签列"
                  disabled={locked || batchSaving}
                  value={batchColumn?.machine_key ?? ''}
                  onChange={(event) => { setBatchField(event.target.value); setBatchValue(''); setBatchConfirm(false) }}
                >
                  {schema.map((column) => (
                    <option key={column.machine_key} value={column.machine_key}>
                      {column.display_name ?? column.machine_key}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                标签值
                {batchColumn?.enum_values?.length ? (
                  <select
                    aria-label="批量标签值"
                    disabled={locked || batchSaving}
                    value={batchValue}
                    onChange={(event) => setBatchValue(event.target.value)}
                  >
                    <option value="">请选择</option>
                    {batchColumn.enum_values.map((value) => (
                      <option key={String(value)} value={String(value)}>{String(value)}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    aria-label="批量标签值"
                    disabled={locked || batchSaving}
                    value={batchValue}
                    type={batchColumn?.value_type === 'string' ? 'text' : 'number'}
                    step={batchColumn?.value_type === 'float' ? 'any' : '1'}
                    onChange={(event) => setBatchValue(event.target.value)}
                  />
                )}
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  aria-label="覆盖已有合法标签"
                  disabled={locked || batchSaving}
                  checked={batchOverwrite}
                  onChange={(event) => setBatchOverwrite(event.target.checked)}
                />
                覆盖已有合法标签
              </label>
              {batchParsed.error && batchValue && <p className="error">{batchParsed.error}</p>}
              <button
                className="primary"
                disabled={locked || blockers || !batchIds.length || Boolean(batchParsed.error)}
                onClick={() => void applyBatch()}
              >
                应用到所选样本
              </button>
              {batchSaving && <p role="status" className="muted">批量保存中...</p>}
            </div>
          </section>
        </>
      )
    }
    if (key === 'return') {
      return (
        <section>
          <h3>任务回传</h3>
          <p className="muted" style={{ marginBottom: 'var(--space-4)' }}>
            保存完整标签后确认当前任务修订，再发起回传。
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            <button
              disabled={locked || blockers || normalized.error !== '' || requiresFreshEdit}
              onClick={confirm}
            >
              确认任务
            </button>
            <button
              className="primary"
              disabled={locked || blockers || !confirmed}
              onClick={sendReturn}
            >
              发起回传
            </button>
            {locked && (
              <button disabled={blockers} onClick={unlock}>
                编辑后回传
              </button>
            )}
          </div>
        </section>
      )
    }
    return (
      <section>
        <h3>批注</h3>
        <div style={{ maxHeight: '300px', overflowY: 'auto', marginBottom: 'var(--space-3)' }}>
          {comments
            .filter((item) => !item.parent_id && (!item.sample_id || item.sample_id === sample?.sample_id))
            .map((item) => (
              <article key={item.id} style={{ padding: 'var(--space-3) 0', borderBottom: '1px solid var(--color-border)' }}>
                <p style={{ fontSize: 'var(--text-sm)', marginBottom: 4 }}>{item.content}</p>
                <span className="muted" style={{ fontSize: 'var(--text-xs)' }}>
                  {item.sample_id ? `样本 ${item.sample_id}` : '任务批注'} · {item.status === 'resolved' ? '已解决' : '待处理'}
                </span>
                <button
                  type="button"
                  style={{ marginTop: 4, padding: '2px 8px', fontSize: 'var(--text-xs)' }}
                  disabled={commentSaving}
                  onClick={() => { setReplyTo(item.id); setCommentScope(item.sample_id ? 'sample' : 'task') }}
                >
                  回复
                </button>
                {comments
                  .filter((reply) => reply.parent_id === item.id)
                  .map((reply) => (
                    <div key={reply.id} style={{ paddingLeft: 'var(--space-4)', marginTop: 'var(--space-2)' }}>
                      <p style={{ fontSize: 'var(--text-sm)', marginBottom: 2 }}>{reply.content}</p>
                      <span className="muted" style={{ fontSize: 'var(--text-xs)' }}>
                        {reply.status === 'resolved' ? '已解决' : '待处理'}
                      </span>
                    </div>
                  ))}
              </article>
            ))}
        </div>
        {commentsLoading && <p role="status" className="muted">批注加载中...</p>}
        {commentsLoadError && <p role="alert" className="error">{commentsLoadError}</p>}
        {(commentCursor || commentsLoadError) && (
          <button
            style={{ marginBottom: 'var(--space-3)' }}
            disabled={commentsLoading}
            onClick={() => void loadComments(commentCursor ?? undefined)}
          >
            {commentCursor ? '加载更多批注' : '重试加载批注'}
          </button>
        )}
        {commentError && <p role="alert" className="error">{commentError}</p>}
        <select
          aria-label="批注范围"
          value={commentScope}
          disabled={commentSaving}
          onChange={(event) => setCommentScope(event.target.value)}
          style={{ marginBottom: 'var(--space-2)' }}
        >
          <option value="sample">当前样本</option>
          <option value="task">整个任务</option>
        </select>
        <textarea
          aria-label="新增批注"
          value={commentText}
          maxLength={2000}
          disabled={commentSaving}
          onChange={(event) => setCommentText(event.target.value)}
          style={{ marginBottom: 'var(--space-2)' }}
        />
        {replyTo && (
          <p className="muted" style={{ fontSize: 'var(--text-xs)' }}>
            正在回复批注
            <button type="button" className="link-button" onClick={() => setReplyTo(undefined)}>取消回复</button>
          </p>
        )}
        <button
          className="primary"
          disabled={commentSaving || !commentText.trim() || (commentScope === 'sample' && !sample)}
          onClick={() => void addComment()}
        >
          添加批注
        </button>
      </section>
    )
  }

  return (
    <>
      <div className="workspace">
        {/* Left icon rail */}
        <aside className="side-tabs" role="tablist" aria-label="工作区面板" aria-orientation="vertical">
          {workspaceTabs.map(({ key, label, icon }) => (
            <div key={key} className="side-panel-group">
              <button
                type="button"
                role="tab"
                className={`side-tab ${openPanels[key] ? 'active' : ''}`}
                aria-label={label}
                aria-selected={openPanels[key]}
                title={label}
                onClick={() => togglePanel(key)}
              >
                {icon}
                <span>{label}</span>
              </button>
              {openPanels[key] && (
                <div className="side-panel-body">{renderPanel(key)}</div>
              )}
            </div>
          ))}
          <div className="side-divider" />
          <button
            type="button"
            className="side-tab bottom"
            title="快捷键"
            aria-label="快捷键"
            onClick={() => setHelpOpen(true)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            <span>帮助</span>
          </button>
        </aside>

        {/* Center: editor + status messages */}
        <div className="workspace-main">
          <div className="workspace-center">
            <div className="stream-meta">
              <div>
                <h2 className="workspace-title">
                  {task?.title ?? '加载中...'}
                </h2>
                <p className="muted">
                  样本 {globalPosition} / {totalSamples}
                  {statusLabel && ` · ${statusLabel}`}
                </p>
              </div>
              <div className="stream-meta-right">
                <div className="progress" aria-label="标注进度">
                  <span>已标注 {completedCount} / {totalSamples}</span>
                  <div className="progress-bar" aria-hidden="true">
                    <div
                      className="progress-fill"
                      style={{ width: `${totalSamples ? Math.round((completedCount / totalSamples) * 100) : 0}%` }}
                    />
                  </div>
                  <span className="mono">
                    {totalSamples ? Math.round((completedCount / totalSamples) * 100) : 0}%
                  </span>
                </div>
                <button type="button" onClick={requestBack} disabled={batchSaving}>
                  ← 返回任务列表
                </button>
              </div>
            </div>

            {error && <p className="error">{error}</p>}
            {message && <p className="success">{message}</p>}

            {sample ? (
              <SampleStream
                sample={sample}
                columns={schema}
                draft={draft}
                visibleColumns={task?.visible_columns ?? []}
                numberedOptions={numberedOptions}
                disabled={locked || batchSaving}
                saveDisabled={!canSave}
                saveState={saveStates[sample.sample_id]}
                position={globalPosition}
                total={totalSamples}
                completed={streamCompleted}
                summaryOpen={summaryOpen}
                onDraftChange={updateDraft}
                onToggleOption={toggleOption}
                onSave={() => void save(sample.sample_id)}
                onSaveAndNext={() => void saveAndAdvance()}
                onSkip={moveNext}
                onPrev={movePrev}
                onNext={moveNext}
                onOpenSamples={openSamplesPanel}
                onRestart={restartStream}
              />
            ) : <p className="muted">暂无样本</p>}
          </div>
        </div>
      </div>

      {exitConfirmOpen && (
        <div className="dialog" role="dialog" aria-label="离开工作区确认">
          <section>
            <h2>有未保存的修改</h2>
            <p>部分标签修改尚未保存完成，立即返回可能丢失这些修改。</p>
            <div className="dialog-actions">
              <button onClick={() => setExitConfirmOpen(false)}>继续标注</button>
              <button className="primary" onClick={() => { setExitConfirmOpen(false); onBack?.() }}>
                放弃修改并返回
              </button>
            </div>
          </section>
        </div>
      )}

      {batchConfirm && (
        <div className="dialog" role="dialog" aria-label="批量覆盖确认">
          <section>
            <h2>确认覆盖 {batchIds.length} 条样本的标签</h2>
            <p>{batchColumn?.display_name ?? batchColumn?.machine_key}: {batchValue || '空值'}</p>
            <div className="dialog-actions">
              <button onClick={() => setBatchConfirm(false)}>取消覆盖</button>
              <button disabled={blockers || locked} onClick={() => void applyBatch(true)}>
                确认批量覆盖
              </button>
            </div>
          </section>
        </div>
      )}

      {conflictOpen[sample?.sample_id ?? ''] && conflicts[sample?.sample_id ?? ''] && (
        <div className="dialog" role="dialog" aria-label="版本冲突">
          <section>
            <h2>版本冲突</h2>
            <p>服务器已有较新的完整标签集合。核对后才能使用当前修订覆盖。</p>
            <pre style={{
              background: 'var(--color-bg-subtle)',
              padding: 'var(--space-3)',
              borderRadius: 'var(--radius-md)',
              fontFamily: 'var(--font-mono)',
              fontSize: '12px',
              overflow: 'auto',
              maxHeight: '200px',
            }}>
              {JSON.stringify(conflicts[sample?.sample_id ?? '']?.labels, null, 2)}
            </pre>
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
              <button onClick={() => setConflictOpen((current) => ({ ...current, [sample?.sample_id ?? '']: false }))}>
                取消
              </button>
              <button
                className="primary"
                disabled={!acknowledged}
                onClick={() => sample && void save(sample.sample_id, true)}
              >
                确认并覆盖完整标签
              </button>
            </div>
          </section>
        </div>
      )}

      <ShortcutHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
    </>
  )
}
