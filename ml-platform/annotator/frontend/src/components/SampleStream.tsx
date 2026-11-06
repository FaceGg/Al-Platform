import { useEffect, useRef, useState } from 'react'
import { LabelColumn, Sample } from '../api/tasks'
import { rangeHint } from '../utils/labelConstraints'
import WaveformChart from './WaveformChart'

export type NumberedOption = { column: LabelColumn; value: string; index: number }

export default function SampleStream({
  sample,
  columns,
  draft,
  visibleColumns,
  numberedOptions,
  fieldDescriptions = {},
  fieldErrors = {},
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
  /** 字段解释：数据列名 → 描述；匹配上的字段在名称下方展示描述 */
  fieldDescriptions?: Record<string, string>
  /** 标签列 machine_key → 当前填写值的类型/范围校验错误；有错误时不能保存 */
  fieldErrors?: Record<string, string>
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
  const firstLabelRef = useRef<HTMLInputElement | null>(null)
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
  // 模型推理输出（prediction/confidence）不进样本字段区，改在标签区展示
  const isInferenceOutput = (key: string) => /prediction|confidence/i.test(key)
  const annotationFields = entries.filter(([key]) => visible.has(key) && !isInferenceOutput(key))
  const otherFields = entries.filter(([key]) => !visible.has(key) && !isInferenceOutput(key))
  const inferenceFields = entries.filter(([key]) => isInferenceOutput(key))
  // 自动标注结果一旦发布就永久保留（人工修改后仍显示，用于对照），
  // 因此这里只看样本是否携带自动结果，而不是当前值是否仍来自自动标注。
  const automaticLabels = sample.automatic_labels ?? {}
  const hasAutomaticResult = Object.keys(automaticLabels).length > 0
  return (
    <section className="sample-stream" aria-label="样本流">
      <div className="stream-sample">
        <div className="stream-fields">
          <div className="stream-meta">
            <h3>当前样本 {sample.sample_id}</h3>
            <span className="muted">修订 {sample.revision}</span>
          </div>
          {sample.waveforms && <WaveformChart waveforms={sample.waveforms} />}
          {annotationFields.length > 0 && (
            <div className="field-group highlight">
              <h4>标注字段</h4>
              <div className="field-grid">
                {annotationFields.map(([key, value]) => (
                  <div className="field-item" key={key}>
                    <span className="field-item-name">{key}</span>
                    {fieldDescriptions[key] ? <span className="field-item-description">{fieldDescriptions[key]}</span> : null}
                    <span className="field-item-value">{String(value)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {otherFields.length > 0 && (
            <div className="field-group">
              <h4>其他字段</h4>
              <div className="field-grid">
                {otherFields.map(([key, value]) => (
                  <div className="field-item" key={key}>
                    <span className="field-item-name">{key}</span>
                    {fieldDescriptions[key] ? <span className="field-item-description">{fieldDescriptions[key]}</span> : null}
                    <span className="field-item-value">{String(value)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {entries.length === 0 && <p className="muted">该样本没有可见数据字段</p>}
          {hasAutomaticResult && (
            <div className="field-group automatic-labels" aria-label="自动标注结果">
              <h4>自动标注结果</h4>
              <p className="muted">以下标签由自动标注生成并保留存档，右侧人工修改后会覆盖使用。</p>
              <div className="field-grid">
                {columns.map((column) => {
                  const value = automaticLabels[column.machine_key]
                  const edited = automaticLabels[column.machine_key] !== (sample.labels ?? {})[column.machine_key]
                  return (
                    <div className="field-item" key={column.machine_key}>
                      <span className="field-item-name">
                        {column.display_name ?? column.machine_key}
                        {edited ? <span className="field-item-badge">已修改</span> : null}
                      </span>
                      <span className="field-item-value">{value == null ? '—' : String(value)}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
        <div className="stream-labels">
          <h3>{hasAutomaticResult ? '标注员修改（人工结果）' : '标签'}</h3>
          {/* 枚举值常是 0/1 这样的数字，要和旁边的快捷键序号区分开 */}
          {numberedOptions.length > 0 && <p className="muted">点击选项选择标签值；选项前的灰色序号是键盘快捷键，不是标签值</p>}
          {inferenceFields.length > 0 && (
            <div className="field-group automatic-labels" aria-label="模型推理输出">
              <h4>模型推理输出（参考）</h4>
              <div className="field-grid">
                {inferenceFields.map(([key, value]) => (
                  <div className="field-item" key={key}>
                    <span className="field-item-name">
                      {key}
                      {fieldDescriptions[key] ? <span className="field-item-description">{fieldDescriptions[key]}</span> : null}
                    </span>
                    <span className="field-item-value">{value == null ? '—' : String(value)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {columns.map((column, index) => {
            const value = String(draft[column.machine_key] ?? '')
            const fieldLabel = `${column.machine_key}-${sample.sample_id}`
            const fieldError = fieldErrors[column.machine_key]
            if (column.enum_values?.length) {
              // 枚举列平铺全部定义值，只能点选（点已选中的取消）；不用 <label> 包裹，否则点标题文字会误触第一个选项
              return (
                <div className="stream-label-field" key={column.machine_key}>
                  {column.display_name ?? column.machine_key}
                  <div className="option-chips" role="group" aria-label={fieldLabel} title="点击选择标签值；徽标数字为键盘快捷键">
                    {column.enum_values.map(option => {
                      const optionValue = String(option)
                      const shortcut = numberedOptions.find(item => item.column.machine_key === column.machine_key && item.value === optionValue)
                      return (
                        <button
                          type="button"
                          key={optionValue}
                          className={`option-chip${value === optionValue ? ' selected' : ''}`}
                          aria-label={shortcut ? `快捷选项 ${shortcut.index} ${optionValue}` : optionValue}
                          aria-pressed={value === optionValue}
                          disabled={disabled}
                          onClick={(event) => {
                            onToggleOption(column, optionValue)
                            // 鼠标点选后释放焦点，Enter/空格继续走「保存并下一条/跳过」全局快捷键
                            if (event.detail > 0) event.currentTarget.blur()
                          }}
                        >{shortcut && <span className="badge">{shortcut.index}</span>}{optionValue}</button>
                      )
                    })}
                  </div>
                  {fieldError && <span className="error">{fieldError}</span>}
                </div>
              )
            }
            const hint = rangeHint(column)
            return (
              <label key={column.machine_key}>
                {column.display_name ?? column.machine_key}
                <input
                  aria-label={fieldLabel}
                  data-label-input="true"
                  disabled={disabled}
                  value={value}
                  onChange={(event) => onDraftChange(sample.sample_id, column.machine_key, event.target.value)}
                  ref={index === 0 ? firstLabelRef : undefined}
                  type={column.value_type === 'string' ? 'text' : 'number'}
                  step={column.value_type === 'float' ? 'any' : '1'}
                  min={column.min_value ?? undefined}
                  max={column.max_value ?? undefined}
                />
                {hint && <span className="muted">{hint}</span>}
                {fieldError && <span className="error">{fieldError}</span>}
              </label>
            )
          })}
          <div>
            <button type="button" disabled={saveDisabled} onClick={onSave}>保存标签</button>
            {saveState === 'saving' && <p className="muted">保存中...</p>}
            {saveState === 'saved' && <p className="success">已保存</p>}
            {/* 校验不通过时保存按钮已禁用、原因已提示，重试无济于事，此处只提示真正的保存失败 */}
            {saveState === 'error' && !saveDisabled && <p className="error">保存失败，请重试</p>}
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
