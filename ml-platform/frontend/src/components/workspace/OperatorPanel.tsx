import { useState, useCallback } from 'react'
import { Input, Collapse, Tag } from 'antd'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useI18n } from '../../i18n'

const categoryLabels: Record<string, string> = {
  data_io: '数据输入/输出',
  processing: '数据预处理',
  ml: '传统机器学习',
  dl: '深度学习',
  evaluation: '模型评估',
  visualization: '可视化',
}

export default function OperatorPanel() {
  const { operators } = useWorkflowStore()
  const { t } = useI18n()
  const [search, setSearch] = useState('')

  const getOpName = (op: any) => {
    const key = op.id.replace(/-/g, '_') as keyof typeof t.operator
    return (t.operator as any)[key] || op.name
  }

  const filtered = operators.filter((op: any) =>
    getOpName(op).toLowerCase().includes(search.toLowerCase()) ||
    op.name.toLowerCase().includes(search.toLowerCase())
  )

  const categories = [...new Set(filtered.map((op: any) => op.category))]

  const onDragStart = (event: React.DragEvent, operator: any) => {
    event.dataTransfer.setData('application/reactflow', JSON.stringify(operator))
    event.dataTransfer.effectAllowed = 'move'
  }

  const getCategoryLabel = (cat: string) => {
    const key = cat as keyof typeof categoryLabels
    return categoryLabels[key] || cat
  }

  const items = categories.map((cat) => ({
    key: cat as string,
    label: getCategoryLabel(cat),
    children: filtered.filter((op: any) => op.category === cat).map((op: any) => (
      <div
        key={op.id}
        draggable
        onDragStart={(e) => onDragStart(e, op)}
        style={{
          padding: '6px 8px', cursor: 'grab', borderBottom: '1px solid #f0f0f0',
          borderRadius: 4, marginBottom: 2,
        }}
      >
        <div style={{ fontWeight: 500, fontSize: 13 }}>{getOpName(op)}</div>
        <Tag style={{ fontSize: 10, marginTop: 2 }}>{getCategoryLabel(op.category)}</Tag>
      </div>
    )),
  }))

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 8 }}>
      <Input.Search
        placeholder={t.workspace.search_operator || '搜索算子...'}
        onChange={(e) => setSearch(e.target.value)}
        style={{ marginBottom: 8 }}
        allowClear
      />
      <Collapse items={items} defaultActiveKey={categories} size="small" />
    </div>
  )
}