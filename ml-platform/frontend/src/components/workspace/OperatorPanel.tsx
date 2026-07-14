import { useState, useCallback } from 'react'
import { Input, Collapse, Tag, Tooltip } from 'antd'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useI18n } from '../../i18n'

const CATEGORY_LABELS: Record<string, { zh: string; en: string }> = {
  data_io: { zh: '数据IO', en: 'Data I/O' },
  processing: { zh: '数据处理', en: 'Processing' },
  ml: { zh: '传统机器学习', en: 'ML' },
  dl: { zh: '深度学习', en: 'Deep Learning' },
  evaluation: { zh: '模型评估', en: 'Evaluation' },
  visualization: { zh: '可视化', en: 'Visualization' },
  control: { zh: '流程控制', en: 'Control Flow' },
  mechanism: { zh: '机理模型', en: 'Mechanism' },
}

const CAT_ORDER = ['data_io', 'processing', 'blending', 'ml', 'dl', 'evaluation', 'visualization', 'control', 'mechanism', 'utility']

export default function OperatorPanel() {
  const { operators } = useWorkflowStore()
  const { t, lang } = useI18n()
  const [search, setSearch] = useState('')

  const getOpName = (op: any) => {
    const key = op.id as string
    return (t as any).operator?.[key] || op.name || op.id
  }

  const getCategoryLabel = (cat: string) => {
    const cfg = CATEGORY_LABELS[cat]
    if (!cfg) return cat
    return lang === 'zh' ? cfg.zh : cfg.en
  }

  const filtered = operators.filter((op: any) => {
    const name = getOpName(op)
    const s = search.toLowerCase()
    return name.toLowerCase().includes(s) || op.name?.toLowerCase().includes(s) || op.id.toLowerCase().includes(s)
  })

  const categories = [...new Set(filtered.map((op: any) => op.category))]
    .sort((a, b) => {
      const ai = CAT_ORDER.indexOf(a), bi = CAT_ORDER.indexOf(b)
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
    })

  const onDragStart = (event: React.DragEvent, operator: any) => {
    event.dataTransfer.setData('application/reactflow', JSON.stringify(operator))
    event.dataTransfer.effectAllowed = 'move'
  }

  const items = categories.map((cat) => ({
    key: cat as string,
    label: (
      <span style={{ fontSize: 13, fontWeight: 600 }}>
        {getCategoryLabel(cat)}
        <Tag style={{ marginLeft: 6, fontSize: 10 }}>
          {filtered.filter((op: any) => op.category === cat).length}
        </Tag>
      </span>
    ),
    children: filtered.filter((op: any) => op.category === cat).map((op: any) => (
      <Tooltip key={op.id} title={op.description || op.name} placement="right">
        <div
          draggable
          onDragStart={(e) => onDragStart(e, op)}
          style={{
            padding: '7px 10px', cursor: 'grab', borderBottom: '1px solid #f0f0f0',
            borderRadius: 6, marginBottom: 3, transition: 'background 0.15s',
            background: '#fafafa',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = '#e6f7ff')}
          onMouseLeave={(e) => (e.currentTarget.style.background = '#fafafa')}
        >
          <div style={{ fontWeight: 500, fontSize: 13, lineHeight: 1.4 }}>
            {getOpName(op)}
          </div>
          <div style={{ fontSize: 10, color: '#999', marginTop: 1 }}>
            {op.id}
          </div>
        </div>
      </Tooltip>
    )),
  }))

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 8 }}>
      <Input.Search
        placeholder={t.workspace?.search_operator || '搜索算子...'}
        onChange={(e) => setSearch(e.target.value)}
        style={{ marginBottom: 8 }}
        allowClear
      />
      <Collapse items={items} defaultActiveKey={categories} size="small" />
    </div>
  )
}
