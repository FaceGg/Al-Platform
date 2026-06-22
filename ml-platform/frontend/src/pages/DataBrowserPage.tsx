import { useEffect, useState } from 'react'
import { Card, Select, Table, Button, Upload, message, Modal, Row, Col } from 'antd'
import { UploadOutlined, EyeOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd/es/upload/interface'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'
import { useI18n } from '../i18n'

interface Project {
  id: number
  name: string
}

interface Dataset {
  id: number
  name: string
  file_type: string
  created_at: string
  row_count?: number
}

export default function DataBrowserPage() {
  const { t } = useI18n()
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(false)
  const [previewVisible, setPreviewVisible] = useState(false)
  const [previewData, setPreviewData] = useState<string[][]>([])
  const [previewColumns, setPreviewColumns] = useState<string[]>([])
  const [uploading, setUploading] = useState(false)

  useEffect(() => {
    apiClient.get('/projects').then((res) => {
      setProjects(res.data.items || [])
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedProjectId) return
    setLoading(true)
    apiClient.get('/projects/' + selectedProjectId + '/datasets')
      .then((res) => {
        setDatasets(res.data.items || res.data.datasets || [])
      })
      .catch(() => {
        message.error(t.common.error)
      })
      .finally(() => setLoading(false))
  }, [selectedProjectId])

  const handlePreview = async (datasetId: number) => {
    try {
      const res = await apiClient.get('/datasets/' + datasetId + '/preview')
      const data = res.data
      setPreviewColumns(data.columns || [])
      setPreviewData(data.rows || data.data || [])
      setPreviewVisible(true)
    } catch {
      message.error(t.common.error)
    }
  }

  const handleUpload = async (file: File) => {
    if (!selectedProjectId) {
      message.error('请先选择项目')
      return false
    }
    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)
    try {
      await apiClient.post('/projects/' + selectedProjectId + '/datasets/upload', formData)
      message.success(t.common.success)
      // refresh
      const res = await apiClient.get('/projects/' + selectedProjectId + '/datasets')
      setDatasets(res.data.items || res.data.datasets || [])
    } catch {
      message.error(t.common.error)
    } finally {
      setUploading(false)
    }
    return false
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '类型', dataIndex: 'file_type', key: 'file_type' },
    { title: t.model.created, dataIndex: 'created_at', key: 'created_at' },
    {
      title: t.model.actions,
      key: 'actions',
      render: (_: unknown, record: Dataset) => (
        <Button icon={<EyeOutlined />} size="small" onClick={() => handlePreview(record.id)}>
          预览
        </Button>
      ),
    },
  ]

  return (
    <AppLayout>
      <Card title={t.nav.data}>
        <Row gutter={16} style={{ marginBottom: 16 }} align="middle">
          <Col span={8}>
            <Select
              style={{ width: '100%' }}
              placeholder="请选择项目"
              value={selectedProjectId}
              onChange={(val) => setSelectedProjectId(val)}
              options={projects.map((p) => ({ value: p.id, label: p.name }))}
              allowClear
            />
          </Col>
          <Col>
            <Upload
              accept=".csv,.xlsx,.xls"
              showUploadList={false}
              beforeUpload={handleUpload}
              disabled={!selectedProjectId || uploading}
            >
              <Button icon={<UploadOutlined />} loading={uploading} disabled={!selectedProjectId}>
                上传文件
              </Button>
            </Upload>
          </Col>
        </Row>

        <Table
          dataSource={datasets}
          columns={columns}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10 }}
        />

        <Modal
          title="数据预览"
          open={previewVisible}
          onCancel={() => setPreviewVisible(false)}
          footer={null}
          width={800}
        >
          <Table
            dataSource={previewData.map((row, i) => {
              const obj: Record<string, string> = { _index: String(i) }
              previewColumns.forEach((col, ci) => { obj[col] = row[ci] })
              return obj
            })}
            columns={[
              { title: '#', dataIndex: '_index', key: '_index', width: 50 },
              ...previewColumns.map((col) => ({ title: col, dataIndex: col, key: col })),
            ]}
            rowKey="_index"
            pagination={{ pageSize: 20 }}
            scroll={{ x: 'max-content' }}
            size="small"
          />
        </Modal>
      </Card>
    </AppLayout>
  )
}
