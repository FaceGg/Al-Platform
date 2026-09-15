import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  confirmTask,
  editForReturn,
  getTask,
  LabelColumn,
  listSamples,
  Sample,
  saveLabels,
  Task,
  returnTask,
} from '../api/tasks'

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
  onBack,
}: {
  taskId: string
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
  const draftsRef = useRef<Drafts>({})
  const samplesRef = useRef<Sample[]>([])
  const savingRef = useRef<Record<string, boolean>>({})
  const queuedRef = useRef<Record<string, boolean>>({})
  const debounceVersionRef = useRef<Record<string, number>>({})
  const timersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const requestGeneration = useRef(0)

  const schema = task?.label_schema?.columns ?? []
  const sample = samples[selected]
  const draft = sample ? (drafts[sample.sample_id] ?? sample.labels ?? {}) : {}
  const blockers = useMemo(
    () => Object.values(saveStates).some((state) => ['dirty', 'saving', 'error', 'conflict'].includes(state)),
    [saveStates],
  )
  const normalized = useMemo(() => normalizeDraft(schema, draft), [schema, draft])
  const canSave = Boolean(sample) && !locked && !savingRef.current[sample?.sample_id ?? ''] && !normalized.error

  const replacePage = useCallback((items: Sample[], cursor?: string) => {
    setSamples(items)
    samplesRef.current = items
    setNextCursor(cursor)
    setSelected(0)
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
    const result = await listSamples(taskId, cursor)
    if (generation !== requestGeneration.current) return
    replacePage(result.items, result.next_cursor)
    setPage(pageIndex)
    setPageCursors((current) => current.slice(0, pageIndex + 1))
  }, [replacePage, taskId])

  useEffect(() => {
    let active = true
    Promise.all([getTask(taskId), listSamples(taskId)])
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
  }, [replacePage, taskId])

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
    if (!task || locked || savingRef.current[sampleId]) {
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
    const payload = override && currentConflict ? { ...currentConflict.labels, ...parsed.values } : parsed.values
    savingRef.current[sampleId] = true
    queuedRef.current[sampleId] = false
    setSaveStates((current) => ({ ...current, [sampleId]: 'saving' }))
    setError('')
    try {
      const result = await saveLabels(task.id, sampleId, payload, baseRevision)
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
  }, [conflicts, locked, schema, task])

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
      await confirmTask(task.id, task.task_revision, task.scope_hash)
      setConfirmed(true)
      setMessage('任务已确认，可以发起回传')
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认失败')
    }
  }

  async function sendReturn() {
    if (!task || !confirmed || blockers || locked) return
    try {
      await returnTask(task.id, task.task_revision, task.scope_hash)
      setLocked(true)
      setMessage('回传已提交，等待验收')
    } catch (err) {
      setError(err instanceof Error ? err.message : '回传失败')
    }
  }

  async function unlock() {
    if (!task || blockers) return
    try {
      await editForReturn(task.id, task.task_revision, task.scope_hash)
      setLocked(false)
      setConfirmed(false)
      setRequiresFreshEdit(true)
      setMessage('已开启新的编辑修订')
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法开启编辑')
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
          {samples.map((item, index) => (
            <button
              className={index === selected ? 'sample-item active' : 'sample-item'}
              key={item.sample_id}
              onClick={() => chooseSample(index)}
            >
              {index + 1}. {item.sample_id}
            </button>
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
                    disabled: locked,
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
        </section>
        <aside className="actions">
          <h2>回传</h2>
          <p className="muted">保存完整标签后确认当前任务修订，再发起回传。</p>
          <button disabled={locked || blockers || normalized.error !== '' || requiresFreshEdit} onClick={confirm}>确认任务</button>
          <button className="primary" disabled={locked || blockers || !confirmed} onClick={sendReturn}>发起回传</button>
          {locked && <button disabled={blockers} onClick={unlock}>编辑后回传</button>}
        </aside>
      </div>
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
