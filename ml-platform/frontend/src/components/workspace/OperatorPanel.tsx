import { useState, useCallback } from 'react'
import { Input, Collapse, Tag } from 'antd'
import { useWorkflowStore } from '../../stores/workflowStore'

const categoryLabels: Record<string, string> = {
  data_io: '数据输入/输出',
  processing: '数据预处理',
  ml: '传统机器学习',
  evaluation: '模型评估',
  visualization: '可视化',
}

export default function OperatorPanel() {
  const { operators, addNode } = useWorkflowStore()
  const [search, setSearch] = useState('')

  const filtered = operators.filter((op: any) =>
    op.name.toLowerCase().includes(search.toLowerCase())
  )

  const categories = [...new Set(filtered.map((op: any) => op.category))]

  const onDragStart = (event: React.DragEvent, operator: any) => {
    event.dataTransfer.setData('application/reactflow', JSON.stringify(operator))
    event.dataTransfer.effectAllowed = 'move'
  }

  const items = categories.map((cat) => ({
    key: cat as string,
    label: categoryLabels[cat as string] || (cat as string),
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
        <div style={{ fontWeight: 500, fontSize: 13 }}>{op.name}</div>
        <Tag style={{ fontSize: 10, marginTop: 2 }}>{categoryLabels[op.category] || op.category}</Tag>
      </div>
    )),
  }))

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 8 }}>
      <Input.Search
        placeholder="搜索算子..."
        onChange={(e) => setSearch(e.target.value)}
        style={{ marginBottom: 8 }}
        allowClear
      />
      <Collapse items={items} defaultActiveKey={categories} size="small" />
    </div>
  )
}
