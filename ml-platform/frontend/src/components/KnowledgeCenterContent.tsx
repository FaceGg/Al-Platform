import { useEffect, useState } from 'react'
import { Table, Tag, Button, Input, message, Popconfirm, Space, Card, Switch, Form, Modal, Select } from 'antd'
import { ReloadOutlined, PushpinOutlined, PlusOutlined, DeleteOutlined, FileTextOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
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
  const navigate = useNavigate()
  const [bindings, setBindings] = useState<KBBinding[]>([])
  const [entries, setEntries] = useState<ExperienceEntry[]>([])
  const [kbs, setKbs] = useState<Array<Record<string, unknown>>>([])
  const [loading, setLoading] = useState(false)
  const [noteTarget, setNoteTarget] = useState<string | null>(null)
  const [noteText, setNoteText] = useState('')
  const [kbModalOpen, setKbModalOpen] = useState(false)
  const [bindModalOpen, setBindModalOpen] = useState(false)
  const [kbForm] = Form.useForm()
  const [bindForm] = Form.useForm()

  const load = () => {
    setLoading(true)
    Promise.all([listBindings(), listExperience(), apiClient.get('/knowledge/bases')])
      .then(([bindingList, entryList, kbRes]) => {
        setBindings(bindingList)
        setEntries(entryList)
        setKbs(kbRes.data?.items || kbRes.data || [])
      })
      .catch((error) => message.error(formatApiError(error, text.loadFailed)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const unboundKbs = kbs.filter(
    (kb) => !bindings.some((b) => b.kb_id === kb.id)
  )

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

  const createKb = async (values: { name: string; description?: string }) => {
    try {
      await apiClient.post('/knowledge/bases', values)
      message.success('知识库已创建')
      setKbModalOpen(false)
      kbForm.resetFields()
      load()
    } catch (error) {
      message.error(formatApiError(error, '创建失败'))
    }
  }

  const createBinding = async (kbId: string) => {
    try {
      await apiClient.post('/knowledge-center/bindings', { kb_id: kbId })
      message.success('绑定已创建——该知识库现参与统一检索')
      load()
    } catch (error) {
      message.error(formatApiError(error, '绑定失败'))
    }
  }

  const deleteKb = async (kb: Record<string, unknown>) => {
    try {
      await apiClient.delete(`/knowledge/bases/${kb.id}`)
      message.success('知识库已删除（文档与检索配置一并清理）')
      load()
    } catch (error) {
      message.error(formatApiError(error, '删除失败'))
    }
  }

  // 系统分区（平台经验真源）对应的 KB 不可删除——删掉等于毁掉经验源。
  const systemKbIds = new Set(bindings.filter((b) => b.is_system).map((b) => b.kb_id))

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
        title="知识库管理"
        extra={
          <Space>
            <Button icon={<PlusOutlined />} type="primary" onClick={() => setKbModalOpen(true)}>
              新建知识库
            </Button>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={kbs}
          pagination={kbs.length > 8 ? { pageSize: 8 } : false}
          locale={{ emptyText: '暂无知识库 —— 点击右上角「新建知识库」创建，或到旧版知识库页迁移' }}
          columns={[
            {
              title: '名称',
              dataIndex: 'name',
              render: (value: string) => <span className="tt">{value}</span>,
            },
            { title: '描述', dataIndex: 'description', ellipsis: true, render: (v: string) => v || '—' },
            { title: '文档数', dataIndex: 'document_count', width: 80, render: (v: number) => v ?? 0 },
            {
              title: '操作',
              key: 'actions',
              width: 220,
              render: (_: unknown, record: Record<string, unknown>) => {
                const isSystemKb = systemKbIds.has(String(record.id));
                return (
                <Space>
                  <Button
                    size="small"
                    icon={<FileTextOutlined />}
                    onClick={() => navigate(`/knowledge/${record.id}`)}
                  >
                    管理文档
                  </Button>
                  <Popconfirm
                    title="确认删除该知识库？"
                    description="文档、向量与检索绑定将一并删除，不可恢复。"
                    onConfirm={() => deleteKb(record)}
                    disabled={isSystemKb}
                  >
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      disabled={isSystemKb}
                      title={isSystemKb ? '系统经验分区不可删除' : undefined}
                    >
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
                );
              },
            },
          ] as never}
        />
        <div style={{ color: 'var(--v2-dim)', fontSize: 11.5, marginTop: 6 }}>
          「管理文档」支持上传 PDF / Word / Excel / 文本并做向量化与检索测试；删除知识库会级联清理其绑定配置。
        </div>
      </Card>
      <Card
        title={text.title}
        extra={
          <Space>
            {unboundKbs.length > 0 && (
              <Button icon={<PlusOutlined />} onClick={() => setBindModalOpen(true)}>
                {text.addBinding}
              </Button>
            )}
            <Button icon={<ReloadOutlined />} onClick={load}>
              {text.refresh}
            </Button>
          </Space>
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
      <Modal
        title="新建知识库"
        open={kbModalOpen}
        onCancel={() => setKbModalOpen(false)}
        onOk={() => kbForm.submit()}
        okText="创建"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={kbForm} layout="vertical" onFinish={createKb} autoComplete="off">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入知识库名称' }]}>
            <Input maxLength={128} placeholder="例如：拧紧工艺标准 / 电焊缺陷图谱" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} maxLength={500} placeholder="知识库用途说明（可选）" />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={text.addBinding}
        open={bindModalOpen}
        onCancel={() => setBindModalOpen(false)}
        onOk={() => {
          const kbId = bindForm.getFieldValue('kb_id')
          if (kbId) createBinding(kbId)
          setBindModalOpen(false)
        }}
        okText={text.addBinding}
        cancelText={t.common.cancel}
        destroyOnHidden
      >
        <Form form={bindForm} layout="vertical" autoComplete="off">
          <Form.Item name="kb_id" label="选择知识库" rules={[{ required: true, message: '请选择知识库' }]}>
            <Select
              placeholder="选择未绑定的知识库"
              options={unboundKbs.map((kb) => ({ value: kb.id as string, label: String(kb.name ?? kb.id) }))}
              optionFilterProp="label"
              showSearch
            />
          </Form.Item>
          <div style={{ color: 'var(--v2-dim)', fontSize: 12 }}>
            绑定后该知识库即参与统一检索（可在此后用开关与范围列细调）。
          </div>
        </Form>
      </Modal>
    </>
  )
}
