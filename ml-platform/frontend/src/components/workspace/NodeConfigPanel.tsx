import { Input, InputNumber, Select, Switch, Form, Divider, Button, message, Upload } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { useI18n } from '../../i18n'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useEffect, useState } from 'react'
import apiClient from '../../api/client'

export default function NodeConfigPanel() {
  const { t } = useI18n()
  const { selectedNode, operators, updateNodeParams, nodeResults, nodeStatuses } = useWorkflowStore()
  const [params, setParams] = useState<Record<string, any>>({})
  const [uploading, setUploading] = useState(false)

  useEffect(() => {
    if (selectedNode) {
      setParams(selectedNode.data.params || {})
    }
  }, [selectedNode])

  if (!selectedNode) {
    return (
      <div style={{ padding: 16, color: '#999' }}>
        <Divider>{t.workspace.node_properties}</Divider>
        <p style={{ textAlign: 'center', marginTop: 40 }}>{t.workspace.select_node_hint}</p>
      </div>
    )
  }

  const operator = operators.find((op: any) => op.id === selectedNode.data.operatorId)
  const result = nodeResults[selectedNode.id]
  const status = nodeStatuses[selectedNode.id]

  const handleParamChange = (name: string, value: any) => {
    const newParams = { ...params, [name]: value }
    setParams(newParams)
    updateNodeParams(selectedNode.id, newParams)
  }

  const handleFileUpload = async (file: File, paramName: string) => {
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await apiClient.post('/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const filePath = res.data.file_path
      handleParamChange(paramName, filePath)
      message.success(`文件已上传: ${file.name}`)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '文件上传失败')
    } finally {
      setUploading(false)
    }
    return false // prevent default upload behavior
  }

  // Determine if the operator is CSV Import (has source param)
  const isCSVImport = operator?.id === 'csv_import'
  const sourceValue = params['source'] || 'local'

  const renderParamField = (p: any) => {
    const value = params[p.name] ?? p.default

    // For CSV import: file_path only shows when source is 'local'
    if (isCSVImport && p.name === 'file_path' && sourceValue !== 'local') {
      return null
    }
    // For CSV import: url only shows when source is 'url'
    if (isCSVImport && p.name === 'url' && sourceValue !== 'url') {
      return null
    }

    if (p.type === 'file') {
      return (
        <div>
          {value && (
            <div style={{ fontSize: 11, color: '#888', marginBottom: 4, wordBreak: 'break-all' }}>
              当前: {value.length > 60 ? value.slice(-60) : value}
            </div>
          )}
          <Upload
            beforeUpload={(file) => handleFileUpload(file, p.name)}
            showUploadList={false}
            accept=".csv,.xls,.xlsx,.txt"
          >
            <Button icon={<UploadOutlined />} loading={uploading} block>
              {value ? '重新选择文件' : '选择本地文件'}
            </Button>
          </Upload>
        </div>
      )
    }

    if (p.type === 'int' || p.type === 'float') {
      return (
        <InputNumber
          style={{ width: '100%' }}
          value={value}
          onChange={(v) => handleParamChange(p.name, v)}
          min={p.range_min} max={p.range_max}
        />
      )
    }

    if (p.type === 'select') {
      return (
        <Select
          style={{ width: '100%' }}
          value={value}
          onChange={(v) => handleParamChange(p.name, v)}
          options={p.options?.map((o: string) => ({ label: o, value: o }))}
        />
      )
    }

    if (p.type === 'boolean') {
      return (
        <Switch
          checked={value}
          onChange={(v) => handleParamChange(p.name, v)}
        />
      )
    }

    return (
      <Input
        value={value}
        onChange={(e) => handleParamChange(p.name, e.target.value)}
      />
    )
  }

  return (
    <div style={{ padding: 12, overflow: 'auto', height: '100%' }}>
      <Divider plain>{selectedNode.data.label || selectedNode.data.operatorId}</Divider>

      <h4 style={{ marginBottom: 8 }}>{t.workspace.params_config}</h4>
      {operator?.parameters?.length > 0 ? (
        <Form layout="vertical" size="small">
          {operator.parameters.map((p: any) => {
            const field = renderParamField(p)
            if (!field) return null
            return (
              <Form.Item key={p.name} label={p.label || p.name}>
                {field}
              </Form.Item>
            )
          })}
        </Form>
      ) : (
        <p style={{ color: '#999', fontSize: 12 }}>{t.workspace.no_params}</p>
      )}

      {status && (
        <>
          <Divider plain>{t.workspace.execution_status}</Divider>
          <p style={{ fontSize: 13 }}>
            {t.workspace.status}{' '}
            <span style={{
              color: status === 'completed' ? '#52c41a' :
                     status === 'running' ? '#1890ff' :
                     status === 'failed' ? '#ff4d4f' : '#999'
            }}>
              {status === 'completed' ? '已完成' :
               status === 'running' ? '运行中' :
               status === 'failed' ? '失败' : '待运行'}
            </span>
          </p>
        </>
      )}

      {result && (
        <>
          <Divider plain>{t.workspace.result_preview}</Divider>
          <pre style={{
            fontSize: 12, background: '#f5f5f5', padding: 8,
            borderRadius: 4, maxHeight: 200, overflow: 'auto'
          }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        </>
      )}
    </div>
  )
}
