import { useEffect, useState } from 'react'
import { App as AntApp, Button, Table, Modal, Form, Input, Space } from 'antd'
import { DeleteOutlined, EyeOutlined, PlusOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'
import DeleteConfirmation from '../components/DeleteConfirmation'
import TableRowAction from '../components/TableRowAction'
import { useI18n } from '../i18n'

export default function ProjectListPage() {
  const { message } = AntApp.useApp()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<any[]>([])
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()

  const load = () => {
    apiClient.get('/projects').then((res) => {
      setProjects(res.data.items || [])
    }).catch(() => {})
  }

  useEffect(() => { load() }, [])

  const { t } = useI18n()

  const deleteProject = async (id: string) => {
    try {
      await apiClient.delete('/projects/' + id)
      message.success('删除成功')
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '删除失败')
    }
  }

  const batchDelete = async () => {
    try {
      await apiClient.post('/projects/batch-delete', { ids: selectedRowKeys })
      message.success(`成功删除 ${selectedRowKeys.length} 个项目`)
      setSelectedRowKeys([])
      load()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '批量删除失败')
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
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm')
    },
    {
      title: '操作', key: 'actions', align: 'right' as const,
      render: (_: any, record: any) => (
        <div className="table-row-actions">
          <TableRowAction label={`进入项目 ${record.name}`} icon={<EyeOutlined />} onClick={() => navigate('/projects/' + record.id)} />
          <DeleteConfirmation label={`删除项目 ${record.name}`} targetName={record.name} onConfirm={() => void deleteProject(record.id)} />
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
              <DeleteConfirmation label="批量删除项目" selectedCount={selectedRowKeys.length} onConfirm={() => void batchDelete()}>
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
        <Form form={form} onFinish={createProject} layout="vertical">
          <Form.Item name="name" label="项目名称" rules={[{ required: true }]}>
            <Input placeholder="输入项目名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  )
}
