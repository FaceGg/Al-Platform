import { useEffect, useMemo, useState } from 'react'
import {
  confirmTask,
  editForReturn,
  getTask,
  listSamples,
  returnTask,
  Sample,
  saveLabels,
  Task,
} from '../api/tasks'

type Conflict = { revision: number; labels: Record<string, unknown> }

function conflictFrom(error: unknown): Conflict | null {
  const detail = (error as { response?: { data?: { detail?: Record<string, unknown> } } })?.response?.data?.detail
  if (detail?.code !== 'REVISION_CONFLICT') return null
  return {
    revision: Number(detail.current_revision ?? 0),
    labels: (detail.labels ?? detail.current_values ?? {}) as Record<string, unknown>,
  }
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
  const [selected, setSelected] = useState(0)
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [locked, setLocked] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [conflict, setConflict] = useState<Conflict | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    Promise.all([getTask(taskId), listSamples(taskId)])
      .then(([taskData, sampleData]) => {
        if (!active) return
        const taskSamples = sampleData.items.length ? sampleData.items : taskData.samples ?? []
        setTask(taskData)
        setSamples(taskSamples)
        setLocked(Boolean(taskData.read_only))
        setDraft(taskSamples[0]?.labels ?? {})
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : '工作区加载失败')
      })
    return () => {
      active = false
    }
  }, [taskId])

  const sample = samples[selected]
  const fields = useMemo(
    () => Object.keys(sample?.labels ?? {}),
    [sample],
  )

  function chooseSample(index: number) {
    setSelected(index)
    setDraft(samples[index]?.labels ?? {})
    setConflict(null)
    setAcknowledged(false)
    setMessage('')
  }

  async function save(override = false) {
    if (!task || !sample || locked) return
    setError('')
    try {
      const result = await saveLabels(
        task.id,
        sample.sample_id,
        override && conflict ? { ...conflict.labels, ...draft } : draft,
        override && conflict ? conflict.revision : sample.revision,
      )
      const updated = {
        ...sample,
        labels: draft,
        revision: result.revision ?? sample.revision + 1,
      }
      setSamples((items) => items.map((item, index) => (index === selected ? updated : item)))
      setConflict(null)
      setAcknowledged(false)
      setMessage('标签已保存')
    } catch (err) {
      const received = conflictFrom(err)
      if (received) {
        setConflict(received)
        setAcknowledged(false)
      } else {
        setError(err instanceof Error ? err.message : '保存失败')
      }
    }
  }

  async function confirm() {
    if (!task) return
    try {
      await confirmTask(task.id, task.task_revision, task.scope_hash)
      setConfirmed(true)
      setMessage('任务已确认，可以发起回传')
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认失败')
    }
  }

  async function sendReturn() {
    if (!task || !confirmed || locked) return
    try {
      await returnTask(task.id, task.task_revision, task.scope_hash)
      setLocked(true)
      setMessage('回传已提交，等待验收')
    } catch (err) {
      setError(err instanceof Error ? err.message : '回传失败')
    }
  }

  async function unlock() {
    if (!task) return
    setLocked(false)
    setConfirmed(true)
    try {
      await editForReturn(task.id, task.task_revision, task.scope_hash)
      setMessage('已开启新的编辑修订')
    } catch (err) {
      setLocked(true)
      setError(err instanceof Error ? err.message : '无法开启编辑')
    }
  }

  if (error && !task) return <main className="portal-page"><p className="error">{error}</p></main>

  return (
    <main className="portal-page workspace">
      <header className="topbar">
        <div>
          <button className="back" onClick={onBack}>返回任务</button>
          <p className="eyebrow">ANNOTATOR PORTAL</p>
          <h1>{task?.title ?? '加载中...'}</h1>
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
                {fields.map((field) => (
                  <label key={field}>
                    {field}
                    <input
                      aria-label={`${field}-${sample.sample_id}`}
                      disabled={locked}
                      value={String(draft[field] ?? '')}
                      onChange={(event) => setDraft((current) => ({ ...current, [field]: event.target.value }))}
                    />
                  </label>
                ))}
              </div>
              <button className="primary" disabled={locked} onClick={() => save()}>保存标签</button>
            </>
          )}
        </section>
        <aside className="actions">
          <h2>回传</h2>
          <p className="muted">保存完整标签后确认当前任务修订，再发起回传。</p>
          <button disabled={locked} onClick={confirm}>确认任务</button>
          <button className="primary" disabled={locked || !confirmed} onClick={sendReturn}>发起回传</button>
          {locked && <button onClick={unlock}>编辑后回传</button>}
        </aside>
      </div>
      {conflict && (
        <div className="dialog" role="dialog" aria-label="版本冲突">
          <section>
            <h2>版本冲突</h2>
            <p>服务器已有较新的完整标签集合。核对后才能使用当前修订覆盖。</p>
            <pre>{JSON.stringify(conflict.labels, null, 2)}</pre>
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
              <button onClick={() => setConflict(null)}>取消</button>
              <button className="primary" disabled={!acknowledged} onClick={() => save(true)}>确认并覆盖完整标签</button>
            </div>
          </section>
        </div>
      )}
    </main>
  )
}
