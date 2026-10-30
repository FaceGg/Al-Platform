import { useEffect, useState } from 'react'
import { Table, Tag, Button, Input, message, Popconfirm, Space, Card, Switch, Form, Modal, Select, Drawer, InputNumber } from 'antd'
import { ReloadOutlined, StopOutlined, PlusOutlined, DeleteOutlined, FileTextOutlined, EyeOutlined } from '@ant-design/icons'
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
  const [editForm] = Form.useForm()
  const [editingBinding, setEditingBinding] = useState<KBBinding | null>(null)
  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([])
  const [selectedEntryIds, setSelectedEntryIds] = useState<string[]>([])
  const [previewEntry, setPreviewEntry] = useState<ExperienceEntry | null>(null)

  const load = () => {
    setLoading(true)
    Promise.all([
      listBindings(),
      listExperience(),
      apiClient.get('/knowledge/bases'),
      apiClient.get('/projects').catch(() => ({ data: { items: [] } })),
    ])
      .then(([bindingList, entryList, kbRes, projRes]) => {
        setBindings(bindingList)
        setEntries(entryList)
        setKbs(kbRes.data?.items || kbRes.data || [])
        setProjects(projRes.data?.items || projRes.data || [])
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

  const saveBindingEdit = async (values: Record<string, unknown>) => {
    if (!editingBinding) return
    try {
      await patchBinding(editingBinding.id, values)
      message.success('绑定配置已更新')
      setEditingBinding(null)
      load()
    } catch (error) {
      message.error(formatApiError(error, text.updateFailed))
    }
  }

  const batchRetire = async () => {
    const targets = selectedEntryIds.filter((id) => {
      const entry = entries.find((e) => e.id === id)
      return entry && entry.status === 'active'
    })
    if (targets.length === 0) {
      message.info('所选条目中没有可否决的 active 条目')
      return
    }
    try {
      await Promise.all(targets.map((id) => retireExperience(id)))
      message.success(`已否决 ${targets.length} 条`)
      setSelectedEntryIds([])
      load()
    } catch (error) {
      message.error(formatApiError(error, text.updateFailed))
    }
  }

  const batchDelete = async () => {
    try {
      const res = await apiClient.post('/knowledge-center/experience/batch-delete', {
        ids: selectedEntryIds,
      })
      message.success(`已删除 ${res.data?.deleted ?? selectedEntryIds.length} 条`)
      setSelectedEntryIds([])
      load()
    } catch (error) {
      message.error(formatApiError(error, text.updateFailed))
    }
  }

  const deleteEntry = async (entry: ExperienceEntry) => {
    try {
      await apiClient.delete(`/knowledge-center/experience/${entry.id}`)
      message.success('已删除')
      load()
    } catch (error) {
      message.error(formatApiError(error, text.updateFailed))
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
    {
      title: text.colActions,
      key: 'actions',
      render: (_: unknown, record: KBBinding) =>
        record.is_system ? (
          <Tag color="purple">{text.systemTag}</Tag>
        ) : (
          <Button
            size="small"
            icon={<EyeOutlined />}
            onClick={() => {
              setEditingBinding(record)
              editForm.setFieldsValue({
                enabled: record.enabled,
                scope_projects: record.scope_projects || [],
                scope_chat: record.scope_chat,
                scope_agent_s1: record.scope_agent_s1,
                retrieval_top_k: record.retrieval_top_k,
                retrieval_trigger: record.retrieval_trigger,
                sync_receive_experience: record.sync_receive_experience,
                sync_experience_min_confidence: record.sync_experience_min_confidence,
              })
            }}
          >
            {t.kbcenter.editBinding}
          </Button>
        ),
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
      width: 280,
      render: (_: unknown, record: ExperienceEntry) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => setPreviewEntry(record)}>
            {text.preview}
          </Button>
          {record.status === 'active' && (
            <Popconfirm title={text.retireConfirm} onConfirm={() => retire(record)}>
              <Button size="small" danger icon={<StopOutlined />}>
                {text.retire}
              </Button>
            </Popconfirm>
          )}
          <Popconfirm title="物理删除该条目？不可恢复。" onConfirm={() => deleteEntry(record)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
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
          dataSource={kbs.filter((kb) => !systemKbIds.has(String(kb.id)))}
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
      <Card
        title={text.experienceTitle}
        extra={
          <Space>
            {selectedEntryIds.length > 0 && (
              <>
                <Button danger size="small" icon={<StopOutlined />} onClick={batchRetire}>
                  {text.batchRetire}（{selectedEntryIds.length}）
                </Button>
                <Popconfirm
                  title={`物理删除所选 ${selectedEntryIds.length} 条？不可恢复。`}
                  onConfirm={batchDelete}
                >
                  <Button danger size="small" icon={<DeleteOutlined />}>
                    批量删除（{selectedEntryIds.length}）
                  </Button>
                </Popconfirm>
              </>
            )}
            <Button icon={<ReloadOutlined />} onClick={load}>
              {text.refresh}
            </Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          size="small"
          columns={entryColumns as never}
          dataSource={entries}
          pagination={{ pageSize: 10 }}
          rowSelection={{
            selectedRowKeys: selectedEntryIds,
            onChange: (keys) => setSelectedEntryIds(keys as string[]),
            getCheckboxProps: () => ({ disabled: false }),
          }}
        />
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
      <Modal
        title="编辑绑定"
        open={!!editingBinding}
        onCancel={() => setEditingBinding(null)}
        onOk={() => editForm.submit()}
        okText="保存"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" onFinish={saveBindingEdit} autoComplete="off">
          <Form.Item name="enabled" label="总开关" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="scope_projects" label="项目范围（留空 = 全部项目）">
            <Select
              mode="multiple"
              placeholder="选择可见项目"
              options={projects.map((p) => ({ value: p.id, label: p.name ?? p.id }))}
              optionFilterProp="label"
              showSearch
            />
          </Form.Item>
          <Form.Item name="scope_chat" label="参与 AI 对话检索" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="scope_agent_s1" label="参与 S1 建模分析" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="retrieval_top_k" label="检索条数 top_k">
            <InputNumber min={1} max={20} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="retrieval_trigger" label="触发方式">
            <Select options={[{ value: 'auto', label: 'auto（自动检索）' }, { value: 'explicit', label: 'explicit（显式请求）' }]} />
          </Form.Item>
          <Form.Item name="sync_receive_experience" label="接收经验同步" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="sync_experience_min_confidence" label="经验同步置信度门槛">
            <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
      <Drawer
        title={text.previewTitle}
        open={!!previewEntry}
        onClose={() => setPreviewEntry(null)}
        width={520}
      >
        {previewEntry && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13, lineHeight: 1.8 }}>
            <div><Tag color="blue">{previewEntry.domain}</Tag><Tag color={previewEntry.status === 'active' ? 'green' : previewEntry.status === 'shadow' ? 'blue' : 'default'}>{previewEntry.status}</Tag><Tag color="purple">{previewEntry.origin}</Tag></div>
            <div><b>情况</b><div>{previewEntry.situation}</div></div>
            <div><b>教训</b><div>{previewEntry.lesson}</div></div>
            <div><b>动作</b><div>{previewEntry.action}</div></div>
            <div><b>置信度</b><div>{previewEntry.confidence.toFixed(2)}{previewEntry.hit_count ? ` · 命中 ${previewEntry.hit_count} 次` : ''}</div></div>
            {(previewEntry.source_tasks ?? []).length > 0 && (
              <div><b>来源任务</b><div>{previewEntry.source_tasks.map((t) => String(t).slice(0, 8)).join('、')}</div></div>
            )}
            {previewEntry.human_note && <div><b>人工附注</b><div>{previewEntry.human_note}</div></div>}
          </div>
        )}
      </Drawer>
    </>
  )
}
