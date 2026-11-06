import { useEffect, useState } from 'react'
import { Table, Tag, Button, Input, message, Popconfirm, Space, Card, Switch, Form, Modal, Select, Drawer, InputNumber, Alert } from 'antd'
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
      message.success(text.kb_created)
      setKbModalOpen(false)
      kbForm.resetFields()
      load()
    } catch (error) {
      message.error(formatApiError(error, text.create_failed))
    }
  }

  const createBinding = async (kbId: string) => {
    try {
      await apiClient.post('/knowledge-center/bindings', { kb_id: kbId })
      message.success(text.bind_created)
      load()
    } catch (error) {
      message.error(formatApiError(error, text.bind_failed))
    }
  }

  const saveBindingEdit = async (values: Record<string, unknown>) => {
    if (!editingBinding) return
    // 系统分区的锁定字段不进 payload（后端对这三项有锁语义，改值会被 409 拒绝）
    const payload = editingBinding.is_system
      ? { ...values, enabled: undefined, scope_projects: undefined, sync_receive_experience: undefined }
      : values
    try {
      await patchBinding(editingBinding.id, payload)
      message.success(text.bind_updated)
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
      message.info(text.retire_none)
      return
    }
    try {
      await Promise.all(targets.map((id) => retireExperience(id)))
      message.success(text.retired_n.replace('{n}', String(targets.length)))
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
      message.success(text.deleted_n.replace('{n}', String(res.data?.deleted ?? selectedEntryIds.length)))
      setSelectedEntryIds([])
      load()
    } catch (error) {
      message.error(formatApiError(error, text.updateFailed))
    }
  }

  const deleteEntry = async (entry: ExperienceEntry) => {
    try {
      await apiClient.delete(`/knowledge-center/experience/${entry.id}`)
      message.success(text.entry_deleted)
      load()
    } catch (error) {
      message.error(formatApiError(error, text.updateFailed))
    }
  }

  const deleteKb = async (kb: Record<string, unknown>) => {
    try {
      await apiClient.delete(`/knowledge/bases/${kb.id}`)
      message.success(text.kb_deleted)
      load()
    } catch (error) {
      message.error(formatApiError(error, text.delete_failed))
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
        record.is_system
          ? '≥' + record.sync_experience_min_confidence + (text.floor_suffix || '（投影门槛）')
          : v
            ? '≥' + record.sync_experience_min_confidence
            : text.syncOff,
    },
    {
      title: text.colActions,
      key: 'actions',
      render: (_: unknown, record: KBBinding) => (
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
      title: text.col_hit,
      key: 'outcome',
      render: (_: unknown, record: ExperienceEntry) => (
        <Space size={4} style={{ whiteSpace: 'nowrap' }}>
          <span>{(text.hit_n || '命中{n}').replace('{n}', String(record.hit_count ?? 0))}</span>
          <Tag color="green" style={{ marginRight: 0 }}>✓{record.success_count ?? 0}</Tag>
          <Tag color="red" style={{ marginRight: 0 }}>✗{record.fail_count ?? 0}</Tag>
        </Space>
      ),
    },
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
          <Popconfirm title={text.delete_entry_confirm} onConfirm={() => deleteEntry(record)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              {text.delete}
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
        title={text.kb_title}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>
              {text.refresh}
            </Button>
            <Button icon={<PlusOutlined />} type="primary" onClick={() => setKbModalOpen(true)}>
              {text.new_kb}
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
          locale={{ emptyText: text.empty_kbs }}
          columns={[
            {
              title: text.colName,
              dataIndex: 'name',
              render: (value: string) => <span className="tt">{value}</span>,
            },
            { title: text.col_desc, dataIndex: 'description', ellipsis: true, render: (v: string) => v || '—' },
            { title: text.col_doc_count, dataIndex: 'document_count', width: 80, render: (v: number) => v ?? 0 },
            {
              title: text.colActions,
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
                    {text.manage_docs}
                  </Button>
                  <Popconfirm
                    title={text.kb_delete_confirm}
                    description={text.kb_delete_desc}
                    onConfirm={() => deleteKb(record)}
                    disabled={isSystemKb}
                  >
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      disabled={isSystemKb}
                      title={isSystemKb ? text.system_undeletable : undefined}
                    >
                      {text.delete}
                    </Button>
                  </Popconfirm>
                </Space>
                );
              },
            },
          ] as never}
        />
        <div style={{ color: 'var(--v2-dim)', fontSize: 11.5, marginTop: 6 }}>
          {text.manage_hint}
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
                  title={(text.batch_delete_confirm || '物理删除所选 {n} 条？不可恢复。').replace('{n}', String(selectedEntryIds.length))}
                  onConfirm={batchDelete}
                >
                  <Button danger size="small" icon={<DeleteOutlined />}>
                    {(text.batch_delete_n || '批量删除（{n}）').replace('{n}', String(selectedEntryIds.length))}
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
        title={text.kb_modal_title}
        open={kbModalOpen}
        onCancel={() => setKbModalOpen(false)}
        onOk={() => kbForm.submit()}
        okText={text.create}
        cancelText={text.cancel}
        destroyOnHidden
      >
        <Form form={kbForm} layout="vertical" onFinish={createKb} autoComplete="off">
          <Form.Item name="name" label={text.name_label} rules={[{ required: true, message: text.name_rule }]}>
            <Input maxLength={128} placeholder={text.name_placeholder} />
          </Form.Item>
          <Form.Item name="description" label={text.desc_label}>
            <Input.TextArea rows={3} maxLength={500} placeholder={text.desc_placeholder} />
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
          <Form.Item name="kb_id" label={text.choose_kb} rules={[{ required: true, message: text.choose_kb_rule }]}>
            <Select
              placeholder={text.choose_unbound_kb}
              options={unboundKbs.map((kb) => ({ value: kb.id as string, label: String(kb.name ?? kb.id) }))}
              optionFilterProp="label"
              showSearch
            />
          </Form.Item>
          <div style={{ color: 'var(--v2-dim)', fontSize: 12 }}>
            {text.bind_hint}
          </div>
        </Form>
      </Modal>
      <Modal
        title={editingBinding?.is_system ? text.edit_binding_system : text.editBinding}
        open={!!editingBinding}
        onCancel={() => setEditingBinding(null)}
        onOk={() => editForm.submit()}
        okText={text.save}
        cancelText={text.cancel}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" onFinish={saveBindingEdit} autoComplete="off">
          {editingBinding?.is_system && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={text.system_locked}
              description={text.system_locked_desc}
            />
          )}
          <Form.Item name="enabled" label={text.colEnabled} valuePropName="checked">
            <Switch disabled={!!editingBinding?.is_system} />
          </Form.Item>
          <Form.Item name="scope_projects" label={text.scope_projects}>
            <Select
              mode="multiple"
              placeholder={text.choose_projects}
              options={projects.map((p) => ({ value: p.id, label: p.name ?? p.id }))}
              optionFilterProp="label"
              showSearch
              disabled={!!editingBinding?.is_system}
            />
          </Form.Item>
          <Form.Item name="scope_chat" label={text.scope_chat} valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="scope_agent_s1" label={text.scope_agent_s1} valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="retrieval_top_k" label={text.top_k_label}>
            <InputNumber min={1} max={20} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="retrieval_trigger" label={text.trigger_label}>
            <Select options={[{ value: 'auto', label: text.trigger_auto }, { value: 'explicit', label: text.trigger_explicit }]} />
          </Form.Item>
          <Form.Item name="sync_receive_experience" label={text.sync_receive} valuePropName="checked">
            <Switch disabled={!!editingBinding?.is_system} />
          </Form.Item>
          <Form.Item
            name="sync_experience_min_confidence"
            label={editingBinding?.is_system ? text.conf_floor_system : text.conf_floor}
          >
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
            <div><b>{text.preview_situation}</b><div>{previewEntry.situation}</div></div>
            <div><b>{text.preview_lesson}</b><div>{previewEntry.lesson}</div></div>
            <div><b>{text.preview_action}</b><div>{previewEntry.action}</div></div>
            <div><b>{text.colConfidence}</b><div>{previewEntry.confidence.toFixed(2)}{previewEntry.hit_count ? ` · ${(text.hit_n || '命中{n}').replace('{n}', String(previewEntry.hit_count))}` : ''}</div></div>
            {(previewEntry.source_tasks ?? []).length > 0 && (
              <div><b>{text.source_tasks}</b><div>{previewEntry.source_tasks.map((t) => String(t).slice(0, 8)).join('、')}</div></div>
            )}
            {previewEntry.human_note && <div><b>{text.note}</b><div>{previewEntry.human_note}</div></div>}
          </div>
        )}
      </Drawer>
    </>
  )
}
