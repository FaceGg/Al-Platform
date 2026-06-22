import { useEffect, useState } from 'react'
import { useParams, useSearchParams, useNavigate } from 'react-router-dom'
import { Card, Form, Input, InputNumber, Button, Steps, message, Descriptions } from 'antd'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'

export default function TemplateWizardPage() {
  const { templateId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [template, setTemplate] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()
  const [projectForm] = Form.useForm()
  const [step, setStep] = useState(0)
  const [projectId, setProjectId] = useState(searchParams.get('project') || '')

  useEffect(() => {
    apiClient.get('/templates/' + templateId).then((res) => {
      setTemplate(res.data)
    }).catch(() => message.error('无法加载模板'))
  }, [templateId])

  const handleStart = async () => {
    const values = await projectForm.validateFields()
    if (!projectId) {
      const res = await apiClient.post('/projects', { name: values.projectName, description: values.projectDesc || '' })
      setProjectId(res.data.id)
    }
    setStep(1)
  }

  const handleRun = async (values: any) => {
    setLoading(true)
    try {
      const res = await apiClient.post('/templates/' + templateId + '/instantiate', null, {
        params: { project_id: projectId, ...values }
      })
      message.success('工作流已创建')
      navigate('/workspace/' + res.data.workflow_id)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '创建失败')
    } finally {
      setLoading(false)
    }
  }

  if (!template) return <AppLayout><Card loading /></AppLayout>

  const tpl = template || {
    name: '模板',
    description: '',
    params: [
      { name: 'target_column', label: '目标列', type: 'text', default: 'quality' },
      { name: 'n_estimators', label: '树的数量', type: 'int', default: 100 },
    ],
  }

  return (
    <AppLayout>
      <Card title={'模板向导: ' + tpl.name} style={{ maxWidth: 700, margin: '0 auto' }}>
        <Steps current={step} style={{ marginBottom: 24 }}>
          <Steps.Step title="项目" />
          <Steps.Step title="参数配置" />
          <Steps.Step title="完成" />
        </Steps>

        {step === 0 && (
          <Form form={projectForm} layout="vertical">
            <Form.Item name="projectName" label="项目名称" rules={[{ required: true }]} initialValue={tpl.name + ' 分析'}>
              <Input />
            </Form.Item>
            <Form.Item name="projectDesc" label="项目描述">
              <Input.TextArea rows={2} />
            </Form.Item>
            <Descriptions column={1} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="模板">{tpl.name}</Descriptions.Item>
              <Descriptions.Item label="说明">{tpl.description}</Descriptions.Item>
            </Descriptions>
            <Button type="primary" onClick={handleStart}>下一步</Button>
          </Form>
        )}

        {step === 1 && (
          <Form form={form} layout="vertical" onFinish={handleRun}>
            {tpl.params.map((p: any) => (
              <Form.Item key={p.name} name={p.name} label={p.label} initialValue={p.default}>
                {p.type === 'int' ? <InputNumber style={{ width: '100%' }} /> :
                 p.type === 'float' ? <InputNumber style={{ width: '100%' }} step={0.1} /> :
                 <Input />}
              </Form.Item>
            ))}
            <Button type="primary" htmlType="submit" loading={loading}>
              创建并运行
            </Button>
            <Button style={{ marginLeft: 8 }} onClick={() => setStep(0)}>返回</Button>
          </Form>
        )}
      </Card>
    </AppLayout>
  )
}
