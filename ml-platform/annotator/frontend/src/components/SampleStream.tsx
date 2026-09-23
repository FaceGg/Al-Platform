import { useEffect, useRef, useState } from 'react'
import { LabelColumn, Sample } from '../api/tasks'

export type NumberedOption = { column: LabelColumn; value: string; index: number }

export default function SampleStream({
  sample,
  columns,
  draft,
  visibleColumns,
  numberedOptions,
  disabled,
  saveDisabled,
  saveState,
  position,
  total,
  completed,
  summaryOpen,
  onDraftChange,
  onToggleOption,
  onSave,
  onSaveAndNext,
  onSkip,
  onPrev,
  onNext,
  onJump,
  onOpenSamples,
  onRestart,
}: {
  sample: Sample
  columns: LabelColumn[]
  draft: Record<string, unknown>
  visibleColumns: string[]
  numberedOptions: NumberedOption[]
  disabled: boolean
  saveDisabled: boolean
  saveState?: string
  position: number
  total: number
  completed: number
  summaryOpen: boolean
  onDraftChange: (sampleId: string, key: string, value: string) => void
  onToggleOption: (column: LabelColumn, value: string) => void
  onSave: () => void
  onSaveAndNext: () => void
  onSkip: () => void
  onPrev: () => void
  onNext: () => void
  onJump?: (value: string) => void
  onOpenSamples: () => void
  onRestart: () => void
}) {
  const firstLabelRef = useRef<HTMLInputElement | HTMLSelectElement | null>(null)
  const setFirstLabelRef = (element: HTMLElement | null) => {
    firstLabelRef.current = element as HTMLInputElement | HTMLSelectElement | null
  }
  const [jumpText, setJumpText] = useState('')
  const submitJump = () => {
    const trimmed = jumpText.trim()
    if (!trimmed) return
    onJump?.(trimmed)
    setJumpText('')
  }
  // 光标默认落在第一个标签输入框；切换上一条/下一样本后自动回到标签框
  useEffect(() => {
    if (disabled) return
    firstLabelRef.current?.focus()
  }, [sample.sample_id, disabled])
  if (summaryOpen) {
    return (
      <section className="sample-stream" aria-label="完成汇总">
        <div className="stream-summary">
          <h2>已到队尾</h2>
          <p>本次连续完成 {completed} 条样本</p>
          <div className="dialog-actions">
            <button type="button" onClick={onRestart}>从头继续</button>
            <button className="primary" type="button" onClick={onOpenSamples}>筛选样本</button>
          </div>
        </div>
      </section>
    )
  }
  const visible = new Set(visibleColumns)
  const entries = Object.entries(sample.values ?? {})
  const annotationFields = entries.filter(([key]) => visible.has(key))
  const otherFields = entries.filter(([key]) => !visible.has(key))
  return (
    <section className="sample-stream" aria-label="样本流">
      <div className="stream-sample">
        <div className="stream-fields">
          <div className="stream-meta">
            <h3>当前样本 {sample.sample_id}</h3>
            <span className="muted">修订 {sample.revision}</span>
          </div>
          {annotationFields.length > 0 && (
            <div className="field-group highlight">
              <h4>标注字段</h4>
              <div className="field-grid">
                {annotationFields.map(([key, value]) => (
                  <div className="field-item" key={key}><span className="field-item-name">{key}</span><span className="field-item-value">{String(value)}</span></div>
                ))}
              </div>
            </div>
          )}
          {otherFields.length > 0 && (
            <div className="field-group">
              <h4>其他字段</h4>
              <div className="field-grid">
                {otherFields.map(([key, value]) => (
                  <div className="field-item" key={key}><span className="field-item-name">{key}</span><span className="field-item-value">{String(value)}</span></div>
                ))}
              </div>
            </div>
          )}
          {entries.length === 0 && <p className="muted">该样本没有可见数据字段</p>}
        </div>
        <div className="stream-labels">
          <h3>标签</h3>
          {columns.map((column, index) => {
            const value = draft[column.machine_key]
            const chips = numberedOptions.filter(option => option.column.machine_key === column.machine_key)
            const common = {
              'aria-label': `${column.machine_key}-${sample.sample_id}`,
              'data-label-input': 'true',
              disabled,
              value: String(value ?? ''),
              onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
                onDraftChange(sample.sample_id, column.machine_key, event.target.value),
            }
            const firstLabel = index === 0 ? setFirstLabelRef : undefined
            return (
              <label key={column.machine_key}>
                {column.display_name ?? column.machine_key}
                {column.enum_values?.length ? (
                  <select {...common} ref={firstLabel}>
                    <option value="">请选择</option>
                    {column.enum_values.map(option => <option key={String(option)} value={String(option)}>{String(option)}</option>)}
                  </select>
                ) : (
                  <input
                    {...common}
                    ref={firstLabel}
                    type={column.value_type === 'string' ? 'text' : 'number'}
                    step={column.value_type === 'float' ? 'any' : '1'}
                  />
                )}
                {chips.length > 0 && (
                  <div className="option-chips">
                    {chips.map(option => (
                      <button
                        type="button"
                        key={option.value}
                        className={`option-chip${String(value ?? '') === option.value ? ' selected' : ''}`}
                        aria-label={`快捷选项 ${option.index} ${option.value}`}
                        disabled={disabled}
                        onClick={() => onToggleOption(column, option.value)}
                      ><span className="badge">{option.index}</span>{option.value}</button>
                    ))}
                  </div>
                )}
              </label>
            )
          })}
          <div>
            <button type="button" disabled={saveDisabled} onClick={onSave}>保存标签</button>
            {saveState === 'saving' && <p className="muted">保存中...</p>}
            {saveState === 'saved' && <p className="success">已保存</p>}
            {saveState === 'error' && <p className="error">保存失败，请重试</p>}
          </div>
        </div>
      </div>
      <footer className="stream-footer">
        <button type="button" onClick={onPrev}>← 上一条</button>
        <span className="stream-progress" aria-label="样本进度">第 {position}/{total} 条</span>
        <span className="stream-jump" aria-label="跳转到指定样本">
          <input
            aria-label="跳转样本"
            placeholder="样本"
            inputMode="numeric"
            autoComplete="off"
            value={jumpText}
            disabled={disabled}
            onChange={(event) => setJumpText(event.target.value.replace(/\D/g, ''))}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                submitJump()
              }
            }}
          />
          <button
            type="button"
            disabled={disabled || !jumpText}
            onClick={submitJump}
          >跳转</button>
        </span>
        <button type="button" onClick={onNext}>下一条 →</button>
        <button type="button" onClick={onSkip}>跳过</button>
        <button className="primary" type="button" disabled={saveDisabled} onClick={onSaveAndNext}>保存并下一样本</button>
      </footer>
    </section>
  )
}
