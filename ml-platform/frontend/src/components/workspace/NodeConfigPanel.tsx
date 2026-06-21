import { Input, InputNumber, Select, Switch, Form, Divider, Button, message } from 'antd'
import { useWorkflowStore } from '../../stores/workflowStore'
import { useEffect, useState } from 'react'

export default function NodeConfigPanel() {
  const { selectedNode, operators, updateNodeParams, nodeResults, nodeStatuses } = useWorkflowStore()
  const [params, setParams] = useState<Record<string, any>>({})

  useEffect(() => {
    if (selectedNode) {
      setParams(selectedNode.data.params || {})
    }
  }, [selectedNode])

  if (!selectedNode) {
    return (
      <div style={{ padding: 16, color: '#999' }}>
        <Divider>节点属性</Divider>
        <p style={{ textAlign: 'center', marginTop: 40 }}>选择一个节点查看属性</p>
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

  return (
    <div style={{ padding: 12, overflow: 'auto', height: '100%' }}>
      <Divider plain>{selectedNode.data.label || selectedNode.data.operatorId}</Divider>

      <h4 style={{ marginBottom: 8 }}>参数配置</h4>
      {operator?.parameters?.length > 0 ? (
        <Form layout="vertical" size="small">
          {operator.parameters.map((p: any) => (
            <Form.Item key={p.name} label={p.label || p.name}>
              {p.type === 'int' || p.type === 'float' ? (
                <InputNumber
                  style={{ width: '100%' }}
                  value={params[p.name] ?? p.default}
                  onChange={(v) => handleParamChange(p.name, v)}
                  min={p.range_min} max={p.range_max}
                />
              ) : p.type === 'select' ? (
                <Select
                  style={{ width: '100%' }}
                  value={params[p.name] ?? p.default}
                  onChange={(v) => handleParamChange(p.name, v)}
                  options={p.options?.map((o: string) => ({ label: o, value: o }))}
                />
              ) : p.type === 'boolean' ? (
                <Switch
                  checked={params[p.name] ?? p.default}
                  onChange={(v) => handleParamChange(p.name, v)}
                />
              ) : (
                <Input
                  value={params[p.name] ?? p.default}
                  onChange={(e) => handleParamChange(p.name, e.target.value)}
                />
              )}
            </Form.Item>
          ))}
        </Form>
      ) : (
        <p style={{ color: '#999', fontSize: 12 }}>无参数配置</p>
      )}

      {status && (
        <>
          <Divider plain>执行状态</Divider>
          <p style={{ fontSize: 13 }}>
            状态: <span style={{ color: status === 'completed' ? '#52c41a' : status === 'running' ? '#1890ff' : status === 'failed' ? '#ff4d4f' : '#999' }}>
              {status === 'completed' ? '已完成' : status === 'running' ? '运行中' : status === 'failed' ? '失败' : '待运行'}
            </span>
          </p>
        </>
      )}

      {result && (
        <>
          <Divider plain>结果预览</Divider>
          <pre style={{ fontSize: 12, background: '#f5f5f5', padding: 8, borderRadius: 4, maxHeight: 200, overflow: 'auto' }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        </>
      )}
    </div>
  )
}
