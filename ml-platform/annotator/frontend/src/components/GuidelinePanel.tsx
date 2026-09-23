import { LabelColumn, LabelSchema } from '../api/tasks'

const typeLabels: Record<LabelColumn['value_type'], string> = { int: '整数', float: '数值', string: '文本' }

function columnDetail(column: LabelColumn) {
  const parts = [typeLabels[column.value_type], column.required ? '必填' : '选填']
  if (column.min_value != null || column.max_value != null) {
    parts.push(`范围 ${column.min_value ?? '-∞'} ~ ${column.max_value ?? '+∞'}`)
  }
  if (column.max_length != null) parts.push(`最长 ${column.max_length} 字节`)
  return parts.join(' · ')
}

export default function GuidelinePanel({ instructions, schema }: { instructions?: string; schema?: LabelSchema }) {
  const columns = schema?.columns ?? []
  return (
    <aside className="guideline" aria-label="标注指南">
      <div className="guideline-body">
        <section>
          <h3>任务说明</h3>
          {instructions ? <p>{instructions}</p> : <p className="muted">暂无任务说明</p>}
        </section>
        <section>
          <h3>标签说明</h3>
          {columns.length ? columns.map(column => (
            <div className="schema-column" key={column.machine_key}>
              <strong>{column.display_name ?? column.machine_key}</strong>
              <span className="muted">{column.machine_key} · {columnDetail(column)}</span>
              {column.enum_values?.length ? (
                <span>可选值：{column.enum_values.map(String).join('、')}</span>
              ) : null}
            </div>
          )) : <p className="muted">暂无标签说明</p>}
        </section>
      </div>
    </aside>
  )
}
