import { useEffect, useState } from 'react'
import { Button, Table, Modal, Form, Input, Space, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'
import { useI18n } from '../i18n'

export default function ProjectListPage() {
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

  const deleteProject = (id: string, name: string) => {
    Modal.confirm({
      title: '确认删除项目 ' + name + '?',
      content: '此操作不可撤销，项目下的所有工作流将被一并删除。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await apiClient.delete('/projects/' + id)
          message.success('删除成功')
          load()
        } catch (e: any) {
          message.error(e.response?.data?.detail || '删除失败')
        }
      },
    })
  }

  const batchDelete = () => {
    const names = projects
      .filter((p) => selectedRowKeys.includes(p.id))
      .map((p) => p.name)
      .join(', ')
    Modal.confirm({
      title: `确认删除选中的 ${selectedRowKeys.length} 个项目?`,
      content: `将删除: ${names}。此操作不可撤销。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await apiClient.post('/projects/batch-delete', { ids: selectedRowKeys })
          message.success(`成功删除 ${selectedRowKeys.length} 个项目`)
          setSelectedRowKeys([])
          load()
        } catch (e: any) {
          message.error(e.response?.data?.detail || '批量删除失败')
        }
      },
    })
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
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at',
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm')
    },
    {
      title: '操作', key: 'actions',
      render: (_: any, record: any) => (
        <Space>
          <a onClick={() => navigate('/projects/' + record.id)}>进入</a>
          <a style={{ color: '#ff4d4f' }} onClick={() => deleteProject(record.id, record.name)}>删除</a>
        </Space>
      ),
    },
  ]

  return (
    <AppLayout>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3>项目列表</h3>
        <Space>
          {selectedRowKeys.length > 0 && (
            <Button danger onClick={batchDelete}>
              批量删除 ({`${selectedRowKeys.length}`})
            </Button>
          )}
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>新建项目</Button>
        </Space>
      </div>
      <Table rowKey="id" rowSelection={rowSelection} dataSource={projects} columns={columns} pagination={{ pageSize: 20 }} />
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
