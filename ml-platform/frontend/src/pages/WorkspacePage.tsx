import { useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { Layout, Button, Space, message } from 'antd'
import { PlayCircleOutlined, SaveOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import { ReactFlowProvider } from 'reactflow'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
import OperatorPanel from '../components/workspace/OperatorPanel'
import WorkflowCanvas from '../components/workspace/WorkflowCanvas'
import NodeConfigPanel from '../components/workspace/NodeConfigPanel'
import ExecutionProgress from '../components/workspace/ExecutionProgress'
import { useWorkflowStore } from '../stores/workflowStore'

const { Sider, Content } = Layout

export default function WorkspacePage() {
  const { workflowId } = useParams<{ workflowId: string }>()
  const navigate = useNavigate()
  const { operators, setOperators, setNodes, setEdges, setIsRunning, setNodeStatus, setNodeResult, nodeStatuses } = useWorkflowStore()

  useEffect(() => {
    apiClient.get('/operators').then((res) => {
      const data = res.data
      setOperators(Array.isArray(data) ? data : data.items || [])
    }).catch(() => {})

    if (workflowId) {
      apiClient.get('/workflows/' + workflowId).then((res) => {
        const wf = res.data
        if (wf.nodes) {
          setNodes(wf.nodes.map((n: any) => ({
            id: String(n.id),
            type: 'custom',
            position: { x: n.position_x || 200, y: n.position_y || 200 },
            data: { operatorId: n.operator_id, label: n.label || '', params: n.params || {} },
          })))
        }
        if (wf.edges) {
          setEdges(wf.edges.map((e: any) => ({
            id: String(e.id),
            source: String(e.source_node_id),
            target: String(e.target_node_id),
            sourceHandle: e.source_port || 'output',
            targetHandle: e.target_port || 'input',
          })))
        }
      }).catch(() => {
        message.warning('无法加载工作流')
      })
    }
  }, [workflowId])

  const handleSave = async () => {
    try {
      const store = useWorkflowStore.getState()
      const payload = {
        name: 'untitled',
        nodes: store.nodes.map((n: any) => ({
          id: n.id,
          operator_id: n.data.operatorId,
          label: n.data.label || '',
          position: { x: n.position.x, y: n.position.y },
          params: n.data.params || {},
        })),
        edges: store.edges.map((e: any) => ({
          id: e.id,
          source: e.source,
          source_port: e.sourceHandle || 'output',
          target: e.target,
          target_port: e.targetHandle || 'input',
        })),
      }

      if (workflowId) {
        // Use the project-wf endpoint
        const pid = window.location.pathname.split('/projects/')[1]?.split('/')[0] || ''
        await apiClient.put('/projects/' + pid + '/workflows/' + workflowId, payload)
      }
      message.success('已保存')
    } catch {
      message.error('保存失败')
    }
  }

  const handleRun = async () => {
    if (!workflowId) return
    setIsRunning(true)
    setNodeStatus('__wf__', 'running')
    try {
      const res = await apiClient.post('/workflows/' + workflowId + '/run')
      const runId = res.data.run_id

      // Connect to WebSocket for real-time updates
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(protocol + '//localhost:8000/ws/runs/' + runId)
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data)
        if (msg.type === 'node_status') {
          setNodeStatus(msg.node_id, msg.status)
          if (msg.result) setNodeResult(msg.node_id, msg.result)
        } else if (msg.type === 'run_completed') {
          setIsRunning(false)
          ws.close()
          if (msg.status === 'completed') {
            message.success('工作流执行完成')
          } else {
            message.error('执行失败: ' + (msg.error || ''))
          }
        }
      }
      ws.onerror = () => {
        setIsRunning(false)
        message.warning('无法连接实时状态，请检查后端是否运行')
      }
    } catch (e: any) {
      setIsRunning(false)
      setNodeStatus('__wf__', 'failed')
      message.error(e.response?.data?.detail || '执行失败')
    }
  }

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    const opData = JSON.parse(event.dataTransfer.getData('application/reactflow'))
    const bounds = event.currentTarget.getBoundingClientRect()
    const position = {
      x: event.clientX - bounds.left - 75,
      y: event.clientY - bounds.top - 30,
    }
    useWorkflowStore.getState().addNode(opData.id, position, opData)
  }, [])

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  return (
    <ReactFlowProvider>
      <Layout style={{ height: '100vh' }}>
        <Sider width={200} style={{ background: '#fff', borderRight: '1px solid #f0f0f0', overflow: 'auto' }}>
          <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', fontWeight: 600, fontSize: 13 }}>
            算子面板
          </div>
          <OperatorPanel />
        </Sider>
        <Content
          onDrop={onDrop}
          onDragOver={onDragOver}
          style={{ position: 'relative', background: '#fafafa' }}
        >
          <WorkflowCanvas />
          <ExecutionProgress />
          <Space style={{ position: 'absolute', top: 8, right: 8, zIndex: 10 }}>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
            <Button icon={<SaveOutlined />} onClick={handleSave}>保存</Button>
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleRun}>运行</Button>
          </Space>
        </Content>
        <Sider width={280} style={{ background: '#fff', borderLeft: '1px solid #f0f0f0', overflow: 'auto' }}>
          <NodeConfigPanel />
        </Sider>
      </Layout>
    </ReactFlowProvider>
  )
}



