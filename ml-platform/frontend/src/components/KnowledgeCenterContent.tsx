import { useEffect, useState } from 'react'
import { Table, Tag, Button, Input, message, Popconfirm, Space, Card, Switch } from 'antd'
import { ReloadOutlined, PushpinOutlined } from '@ant-design/icons'
import {
  ExperienceEntry,
  KBBinding,
  annotateExperience,
  listBindings,
  listExperience,
  patchBinding,
  retireExperience,
} from '../api/knowledgeCenter'
import { formatApiError } from '../api/client'

/**
 * 知识中心内容（绑定配置表 + 平台经验真源条目）：独立于路由壳，
 * 供 /knowledge-center 独立页与智能体中心 knowledge subtab 内嵌共用（§16.1 合并呈现）。
 */
export default function KnowledgeCenterContent({ t }: { t: any }) {
  const text = t.kbcenter
  const [bindings, setBindings] = useState<KBBinding[]>([])
  const [entries, setEntries] = useState<ExperienceEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [noteTarget, setNoteTarget] = useState<string | null>(null)
  const [noteText, setNoteText] = useState('')

  const load = () => {
    setLoading(true)
    Promise.all([listBindings(), listExperience()])
      .then(([bindingList, entryList]) => {
        setBindings(bindingList)
        setEntries(entryList)
      })
      .catch((error) => message.error(formatApiError(error, text.loadFailed)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const toggleBinding = async (binding: KBBinding, enabled: boolean) => {
    try {
      await patchBinding(binding.id, { enabled })
      load()
    } catch (error) {
      message.error(formatApiError(error, text.updateFailed))
    }
  }

  const retire = async (entry: ExperienceEntry) => {
    try {
      await retireExperience(entry.id)
      message.success(text.retireOk)
      load()
    } catch (error) {
      message.error(formatApiError(error, text.updateFailed))
    }
  }

  const saveNote = async (entry: ExperienceEntry) => {
    try {
      await annotateExperience(entry.id, noteText)
      message.success(text.noteOk)
      setNoteTarget(null)
      setNoteText('')
      load()
    } catch (error) {
      message.error(formatApiError(error, text.updateFailed))
    }
  }

  const bindingColumns = [
    {
      title: text.colName,
      dataIndex: 'kb_name',
      render: (value: string, record: KBBinding) => (
        <Space>
          <span>{value}</span>
          {record.is_system && <Tag color="purple">{text.systemTag}</Tag>}
        </Space>
      ),
    },
    { title: text.colDocs, dataIndex: 'doc_count' },
    {
      title: text.colEnabled,
      dataIndex: 'enabled',
      render: (value: boolean, record: KBBinding) => (
        <Switch checked={value} disabled={record.is_system} onChange={(checked) => toggleBinding(record, checked)} />
      ),
    },
    {
      title: text.colScope,
      dataIndex: 'scope_projects',
      render: (value: string[]) =>
        !value || value.length === 0 ? (
          <Tag>{text.scopeUnbound}</Tag>
        ) : value.includes('*') ? (
          <Tag color="green">{text.scopeAll}</Tag>
        ) : (
          <Tag color="blue">{value.length}</Tag>
        ),
    },
    { title: text.colChat, dataIndex: 'scope_chat', render: (v: boolean) => (v ? '✓' : '—') },
    { title: text.colS1, dataIndex: 'scope_agent_s1', render: (v: boolean) => (v ? '✓' : '—') },
    { title: text.colTopK, dataIndex: 'retrieval_top_k' },
    { title: text.colTrigger, dataIndex: 'retrieval_trigger' },
    {
      title: text.colSync,
      dataIndex: 'sync_receive_experience',
      render: (v: boolean, record: KBBinding) =>
        record.is_system ? '—' : v ? '≥' + record.sync_experience_min_confidence : text.syncOff,
    },
  ]

  const entryColumns = [
    { title: 'ID', dataIndex: 'id', render: (v: string) => <span className="mono">{v.slice(0, 8)}</span> },
    { title: text.colDomain, dataIndex: 'domain' },
    { title: text.colLesson, dataIndex: 'lesson', ellipsis: true },
    { title: text.colAction, dataIndex: 'action', ellipsis: true },
    { title: text.colConfidence, dataIndex: 'confidence', render: (v: number) => v.toFixed(2) },
    {
      title: text.colStatus,
      dataIndex: 'status',
      render: (value: string) => (
        <Tag color={value === 'active' ? 'green' : value === 'shadow' ? 'blue' : 'default'}>{value}</Tag>
      ),
    },
    { title: text.colNote, dataIndex: 'human_note', ellipsis: true, render: (value: string | null) => value || '—' },
    {
      title: text.colActions,
      render: (_: unknown, record: ExperienceEntry) => (
        <Space>
          {record.status === 'active' && (
            <Popconfirm title={text.retireConfirm} onConfirm={() => retire(record)}>
              <Button size="small" danger icon={<PushpinOutlined />}>
                {text.retire}
              </Button>
            </Popconfirm>
          )}
          <Button
            size="small"
            onClick={() => {
              setNoteTarget(record.id)
              setNoteText(record.human_note || '')
            }}
          >
            {text.note}
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Card
        title={text.title}
        extra={
          <Button icon={<ReloadOutlined />} onClick={load}>
            {text.refresh}
          </Button>
        }
        style={{ marginBottom: 16 }}
      >
        <Table rowKey="id" size="small" columns={bindingColumns as never} dataSource={bindings} loading={loading} pagination={false} />
      </Card>
      <Card title={text.experienceTitle}>
        <Table rowKey="id" size="small" columns={entryColumns as never} dataSource={entries} pagination={{ pageSize: 10 }} />
      </Card>
      {noteTarget && (
        <Card title={text.noteTitle} style={{ marginTop: 16 }}>
          <Space.Compact style={{ width: '100%' }}>
            <Input value={noteText} onChange={(event) => setNoteText(event.target.value)} placeholder={text.notePlaceholder} />
            <Button
              type="primary"
              onClick={() => {
                const entry = entries.find((item) => item.id === noteTarget)
                if (entry) saveNote(entry)
              }}
            >
              {text.noteSave}
            </Button>
            <Button onClick={() => setNoteTarget(null)}>{text.noteCancel}</Button>
          </Space.Compact>
        </Card>
      )}
    </>
  )
}
