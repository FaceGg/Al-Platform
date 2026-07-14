import { useEffect, useState } from 'react'
import { Button, Card, List, Modal, Form, Input, Space, message, Tag, Popconfirm } from 'antd'
import { PlusOutlined, ExperimentOutlined, BranchesOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'

export default function ProjectDetailPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [workflows, setWorkflows] = useState<any[]>([])
  const [project, setProject] = useState<any>({})
  const [modalOpen, setModalOpen] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [projName, setProjName] = useState('')
  const [form] = Form.useForm()

  const load = () => {
    apiClient.get('/projects/' + projectId).then((r) => {
      setProject(r.data)
      setProjName(r.data.name || '')
    }).catch(() => {})
    apiClient.get('/projects/' + projectId + '/workflows').then((r) => {
      setWorkflows(r.data.items || r.data || [])
    }).catch(() => {})
  }

  useEffect(() => { load() }, [projectId])

  const saveProjectName = async () => {
    setEditingName(false)
    if (!projName.trim()) {
      setProjName(project.name)
      return
    }
    try {
      await apiClient.put('/projects/' + projectId, { name: projName })
      message.success('已保存')
      setProject({ ...project, name: projName })
    } catch {
      message.error('保存失败')
      setProjName(project.name)
    }
  }

  const createWorkflow = async (values: any) => {
    const res = await apiClient.post('/projects/' + projectId + '/workflows', values)
    message.success('工作流已创建')
    setModalOpen(false)
    form.resetFields()
    navigate('/workspace/' + res.data.id)
  }

  const deleteWorkflow = async (wfId: string) => {
    try {
      await apiClient.delete('/projects/' + projectId + '/workflows/' + wfId)
      message.success('工作流已删除')
      load()
    } catch {
      message.error('删除失败')
    }
  }

  return (
    <AppLayout>
      <div style={{ marginBottom: 16 }}>
        <Button onClick={() => navigate('/projects')} type="link">&larr; 返回项目列表</Button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '8px 0' }}>
          {editingName ? (
            <Input value={projName}
              onChange={(e) => setProjName(e.target.value)}
              onPressEnter={saveProjectName} onBlur={saveProjectName}
              autoFocus style={{ width: 300, fontSize: 18, fontWeight: 600 }} />
          ) : (
            <>
              <h3 style={{ margin: 0 }}>{project.name}</h3>
              <Button type="text" size="small" icon={<EditOutlined />}
                onClick={() => setEditingName(true)} />
            </>
          )}
        </div>
        <p style={{ color: '#666' }}>{project.description}</p>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h4>工作流</h4>
        <Space>
          <Button onClick={() => navigate('/template/weld_quality?project=' + projectId)}
            icon={<ExperimentOutlined />}>使用模板</Button>
          <Button type="primary" icon={<PlusOutlined />}
            onClick={() => setModalOpen(true)}>新建工作流</Button>
        </Space>
      </div>

      <List
        grid={{ gutter: 16, xs: 1, sm: 2, md: 3, lg: 4 }}
        dataSource={workflows}
        renderItem={(item: any) => (
          <List.Item>
            <Card hoverable
              actions={[
                <Button type="link" onClick={() => navigate('/workspace/' + item.id)}>编辑</Button>,
                <Popconfirm
                  title="确认删除"
                  description={"删除工作流 " + item.name + "？"}
                  onConfirm={() => deleteWorkflow(item.id)}
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                >
                  <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
                </Popconfirm>
              ]}>
              <Card.Meta
                avatar={<BranchesOutlined style={{ fontSize: 24, color: '#1890ff' }} />}
                title={item.name}
                description={
                  <div>
                    <Tag color={item.type === 'template' ? 'blue' : 'green'}>{item.type}</Tag>
                    <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                      {item.created_at ? dayjs(item.created_at).format('YYYY-MM-DD') : ''}
                    </div>
                  </div>
                } />
            </Card>
          </List.Item>
        )}
        locale={{ emptyText: '暂无工作流，点击上方按钮创建' }} />

      <Modal title="新建工作流" open={modalOpen} onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}>
        <Form form={form} onFinish={createWorkflow} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="输入工作流名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  )
}
