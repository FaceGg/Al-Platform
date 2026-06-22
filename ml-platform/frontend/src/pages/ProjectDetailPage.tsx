import { useEffect, useState } from 'react'
import { Button, Card, List, Modal, Form, Input, Space, message, Tag } from 'antd'
import { PlusOutlined, ExperimentOutlined, BranchesOutlined, EditOutlined } from '@ant-design/icons'
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
      message.success('\u5df2\u4fdd\u5b58')
      setProject({ ...project, name: projName })
    } catch {
      message.error('\u4fdd\u5b58\u5931\u8d25')
      setProjName(project.name)
    }
  }

  const createWorkflow = async (values: any) => {
    const res = await apiClient.post('/projects/' + projectId + '/workflows', values)
    message.success('\u5de5\u4f5c\u6d41\u5df2\u521b\u5efa')
    setModalOpen(false)
    form.resetFields()
    navigate('/workspace/' + res.data.id)
  }

  return (
    <AppLayout>
      <div style={{ marginBottom: 16 }}>
        <Button onClick={() => navigate('/projects')} type="link">&larr; \u8fd4\u56de\u9879\u76ee\u5217\u8868</Button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '8px 0' }}>
          {editingName ? (
            <Input
              value={projName}
              onChange={(e) => setProjName(e.target.value)}
              onPressEnter={saveProjectName}
              onBlur={saveProjectName}
              autoFocus
              style={{ width: 300, fontSize: 18, fontWeight: 600 }}
            />
          ) : (
            <>
              <h3 style={{ margin: 0 }}>{project.name}</h3>
              <Button type="text" size="small" icon={<EditOutlined />} onClick={() => setEditingName(true)} />
            </>
          )}
        </div>
        <p style={{ color: '#666' }}>{project.description}</p>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h4>\u5de5\u4f5c\u6d41</h4>
        <Space>
          <Button onClick={() => navigate('/template/weld_quality?project=' + projectId)} icon={<ExperimentOutlined />}>
            \u4f7f\u7528\u6a21\u677f
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
            \u65b0\u5efa\u5de5\u4f5c\u6d41
          </Button>
        </Space>
      </div>

      <List
        grid={{ gutter: 16, xs: 1, sm: 2, md: 3, lg: 4 }}
        dataSource={workflows}
        renderItem={(item: any) => (
          <List.Item>
            <Card
              hoverable
              actions={[
                <Button type="link" onClick={() => navigate('/workspace/' + item.id)}>\u7f16\u8f91</Button>,
              ]}
            >
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
                }
              />
            </Card>
          </List.Item>
        )}
        locale={{ emptyText: '\u6682\u65e0\u5de5\u4f5c\u6d41\uff0c\u70b9\u51fb\u4e0a\u65b9\u6309\u94ae\u521b\u5efa' }}
      />

      <Modal title="\u65b0\u5efa\u5de5\u4f5c\u6d41" open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => form.submit()}>
        <Form form={form} onFinish={createWorkflow} layout="vertical">
          <Form.Item name="name" label="\u540d\u79f0" rules={[{ required: true }]}>
            <Input placeholder="\u8f93\u5165\u5de5\u4f5c\u6d41\u540d\u79f0" />
          </Form.Item>
          <Form.Item name="description" label="\u63cf\u8ff0">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  )
}
