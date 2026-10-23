import { useEffect, useState } from 'react'
import { App as AntApp, Button, Table, Modal, Form, Input, Space } from 'antd'
import { DeleteOutlined, EyeOutlined, PlusOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'
import DeleteConfirmation from '../components/DeleteConfirmation'
import TableRowAction from '../components/TableRowAction'
import TypeToDeleteModal from '../components/TypeToDeleteModal'
import { useI18n } from '../i18n'
import { formatLocalTime } from '../utils/time'

// 项目删除连带清理数据集/模型/工作流/训练/部署/API 等全部项目数据，
// 二次确认必须逐字输入项目名称（批量删除输入固定短语）才可执行。
const BATCH_DELETE_PHRASE = '确认删除'

export default function ProjectListPage() {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<any[]>([])
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [pendingDelete, setPendingDelete] = useState<{ id: string; name: string } | null>(null)
  const [pendingBatch, setPendingBatch] = useState<number | null>(null)
  const [deleting, setDeleting] = useState(false)

  const load = () => {
    apiClient.get('/projects').then((res) => {
      setProjects(res.data.items || [])
    }).catch(() => {})
  }

  useEffect(() => { load() }, [])

  const { t } = useI18n()

  const deleteProject = async (id: string) => {
    setDeleting(true)
    try {
      await apiClient.delete('/projects/' + id)
      message.success('删除成功')
      setPendingDelete(null)
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  const batchDelete = async () => {
    setDeleting(true)
    try {
      await apiClient.post('/projects/batch-delete', { ids: selectedRowKeys })
      message.success(`成功删除 ${selectedRowKeys.length} 个项目`)
      setSelectedRowKeys([])
      setPendingBatch(null)
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '批量删除失败')
    } finally {
      setDeleting(false)
    }
  }

  const createProject = async (values: any) => {
    try {
      await apiClient.post('/projects', values)
      message.success('项目已创建')
      setModalOpen(false)
      form.resetFields()
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '创建失败，请检查后端是否运行')
    }
  }

  const rowSelection = {
    selectedRowKeys,
    onChange: (keys: React.Key[]) => setSelectedRowKeys(keys),
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name',
      render: (text: string, record: any) => <Link to={'/projects/' + record.id}>{text}</Link>
    },
    { title: '描述', dataIndex: 'description', key: 'description', ellipsis: true },
    { title: '创建者', dataIndex: 'creator_username', key: 'creator_username',
      render: (username: string | null | undefined) => username || '-'
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at',
      render: (v: string) => formatLocalTime(v)
    },
    {
      title: '操作', key: 'actions', align: 'right' as const,
      render: (_: any, record: any) => (
        <div className="table-row-actions">
          <TableRowAction label={`进入项目 ${record.name}`} icon={<EyeOutlined />} onClick={() => navigate('/projects/' + record.id)} />
          <DeleteConfirmation label={`删除项目 ${record.name}`} targetName={record.name} onConfirm={() => setPendingDelete({ id: record.id, name: record.name })} />
        </div>
      ),
    },
  ]

  return (
    <AppLayout>
      <div className="page-shell fade-in">
        <div className="page-header">
          <div className="page-header-copy">
            <h3 className="page-title">项目列表</h3>
          </div>
          <Space className="page-actions" wrap>
            {selectedRowKeys.length > 0 && (
              <DeleteConfirmation label="批量删除项目" selectedCount={selectedRowKeys.length} onConfirm={() => setPendingBatch(selectedRowKeys.length)}>
                <Button danger icon={<DeleteOutlined />}>批量删除 ({`${selectedRowKeys.length}`})</Button>
              </DeleteConfirmation>
            )}
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>新建项目</Button>
          </Space>
        </div>
        <div className="table-surface">
          <Table rowKey="id" rowSelection={rowSelection} dataSource={projects} columns={columns} pagination={{ pageSize: 20 }} />
        </div>
      </div>
      <Modal title="新建项目" open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => form.submit()}>
        <Form form={form} onFinish={createProject} layout="vertical" autoComplete="off">
          <Form.Item name="name" label="项目名称" rules={[{ required: true }]}>
            <Input placeholder="输入项目名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
      <TypeToDeleteModal
        open={pendingDelete !== null}
        targetName={pendingDelete?.name || ""}
        title={`删除项目「${pendingDelete?.name || ""}」`}
        description={
          <div>
            <p style={{ margin: "4px 0" }}>删除项目将<b>同时删除</b>该项目下的全部数据，包括：</p>
            <p style={{ margin: "4px 0" }}>
              数据集与文件、模型与版本、工作流与模板、训练任务与实验、推理部署与
              <b>API 市场条目</b>、闭环自动化任务、标注任务、定时调度等。
            </p>
            <p style={{ margin: "4px 0", color: "#cf1322" }}>删除后数据无法恢复，存储文件将被清理。</p>
          </div>
        }
        confirmLabel="我已了解后果，删除项目"
        loading={deleting}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => { if (pendingDelete) void deleteProject(pendingDelete.id) }}
      />
      <TypeToDeleteModal
        open={pendingBatch !== null}
        targetName={BATCH_DELETE_PHRASE}
        title={`批量删除 ${pendingBatch ?? 0} 个项目`}
        description={
          <div>
            <p style={{ margin: "4px 0" }}>批量删除将<b>同时删除</b>这些项目下的全部数据（数据集、模型、
              工作流、训练任务、推理部署与 <b>API 市场条目</b>、闭环任务、标注任务等）。</p>
            <p style={{ margin: "4px 0", color: "#cf1322" }}>删除后数据无法恢复。</p>
          </div>
        }
        prompt={`请输入「${BATCH_DELETE_PHRASE}」以确认批量删除：`}
        confirmLabel="我已了解后果，批量删除"
        loading={deleting}
        onCancel={() => setPendingBatch(null)}
        onConfirm={() => void batchDelete()}
      />
    </AppLayout>
  )
}
