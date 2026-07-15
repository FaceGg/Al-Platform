import { useEffect, useState } from 'react'
import { Card, Table, Select, Button, Space, message, Modal, Tag, Row, Col, List } from 'antd'
import { DownloadOutlined, DeleteOutlined, EyeOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'
import { useI18n } from '../i18n'

interface Model {
  id: number
  name: string
  model_type: string
  created_at: string
  project_id: number
  project_name?: string
}

interface Project {
  id: number
  name: string
}

export default function ModelLibraryPage() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [models, setModels] = useState<Model[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  useEffect(() => {
    apiClient.get('/projects').then((res) => {
      setProjects(res.data.items || [])
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedProjectId) return
    setLoading(true)
    apiClient.get('/projects/' + selectedProjectId + '/models')
      .then((res) => {
        setModels(res.data.items || res.data.models || [])
      })
      .catch(() => {
        message.error(t.common.error)
      })
      .finally(() => setLoading(false))
  }, [selectedProjectId])

  const handleBatchDelete = () => {
    if (selectedRowKeys.length === 0) return
    Modal.confirm({
      title: '批量删除选中的 ' + selectedRowKeys.length + ' 个模型？',
      icon: <ExclamationCircleOutlined />,
      content: '删除后不可恢复，请谨慎操作。',
      okText: '确认删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await apiClient.post('/model-library/batch-delete', { ids: selectedRowKeys })
          message.success('成功删除 ' + selectedRowKeys.length + ' 个模型')
          setSelectedRowKeys([])
          setModels((prev) => prev.filter((m) => selectedRowKeys.includes(m.id)))
        } catch {
          message.error('批量删除失败')
        }
      },
    })
  }

    const handleDownload = async (modelId: number) => {
    try {
      const res = await apiClient.get('/models/' + modelId + '/download', { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'model-' + modelId + '.bin'
      a.click()
      URL.revokeObjectURL(url)
      message.success(t.common.success)
    } catch {
      message.error(t.common.error)
    }
  }

  const handleDelete = (modelId: number) => {
    Modal.confirm({
      title: t.common.confirm,
      content: '确定删除此模型？',
      onOk: async () => {
        try {
          await apiClient.delete('/models/' + modelId)
          message.success(t.common.success)
          setModels((prev) => prev.filter((m) => m.id !== modelId))
        } catch {
          message.error(t.common.error)
        }
      },
    })
  }

  const rowSelection = {
    selectedRowKeys,
    onChange: (newSelectedRowKeys: React.Key[]) => {
      setSelectedRowKeys(newSelectedRowKeys)
    },
  }

    const columns = [
    { title: t.model.title, dataIndex: 'name', key: 'name' },
    { title: '类型', dataIndex: 'model_type', key: 'model_type' },
    { title: t.model.created, dataIndex: 'created_at', key: 'created_at' },
    {
      title: t.model.actions,
      key: 'actions',
      render: (_: unknown, record: Model) => (
        <Space>
          <Button icon={<DownloadOutlined />} size="small" onClick={() => handleDownload(record.id)}>
            {'下载'}
          </Button>
          <Button icon={<DeleteOutlined />} size="small" danger onClick={() => handleDelete(record.id)}>
            {t.common.delete}
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <AppLayout>
      <Card title={t.model.title}>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Select
              style={{ width: '100%' }}
              placeholder={selectedProjectId ? '' : (t.common.loading === '加载中...' ? '请选择项目' : 'Select Project')}
              value={selectedProjectId}
              onChange={(val) => setSelectedProjectId(val)}
              options={projects.map((p) => ({ value: p.id, label: p.name }))}
              allowClear
            />
          </Col>
        </Row>

        {!selectedProjectId ? (
          <List
            header={<div>{t.project.list}</div>}
            dataSource={projects}
            renderItem={(item: Project) => (
              <List.Item
                actions={[
                  <Button type="link" onClick={() => setSelectedProjectId(item.id)}>
                    {t.model.title}
                  </Button>,
                ]}
              >
                <List.Item.Meta title={item.name} />
              </List.Item>
            )}
          />
        ) : (
          <>
            {selectedRowKeys.length > 0 && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col>
                <Button icon={<DeleteOutlined />} danger type='primary' onClick={handleBatchDelete}>
                  批量删除 ({selectedRowKeys.length})
                </Button>
              </Col>
            </Row>
          )}
            <Table
            dataSource={models}
            columns={columns}
            rowKey="id"
          rowSelection={rowSelection}
            loading={loading}
            pagination={{ pageSize: 10 }}
          />
          </>
        )}
      </Card>
    </AppLayout>
  )
}

