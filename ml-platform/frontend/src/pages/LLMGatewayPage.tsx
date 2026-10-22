import { useEffect, useState } from 'react'
import { Table, Tag, Button, Modal, Form, Input, InputNumber, message, Popconfirm, Space, Select, Card, Switch } from 'antd'
import { PlusOutlined, ReloadOutlined, ApiOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useI18n } from '../i18n'
import AppLayout from '../components/AppLayout'
import {
  LLMProfile,
  LLMProfilePayload,
  createLlmProfile,
  deleteLlmProfile,
  listLlmProfiles,
  testLlmProfile,
  updateLlmProfile,
} from '../api/llmProfiles'
import { formatApiError } from '../api/client'

const PURPOSE_OPTIONS = ['chat', 'agent', 'embedding']

export default function LLMGatewayPage() {
  const { t } = useI18n()
  const text = t.llm
  const [profiles, setProfiles] = useState<LLMProfile[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<LLMProfile | null>(null)
  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [form] = Form.useForm()

  const load = () => {
    setLoading(true)
    listLlmProfiles()
      .then(setProfiles)
      .catch((error) => message.error(formatApiError(error, text.loadFailed)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ provider: 'openai_compatible', deployment: 'cloud', timeout_seconds: 60, purpose_tags: ['chat', 'agent'] })
    setModalOpen(true)
  }

  const openEdit = (profile: LLMProfile) => {
    setEditing(profile)
    form.resetFields()
    form.setFieldsValue({
      name: profile.name,
      provider: profile.provider,
      api_url: profile.api_url,
      model_id: profile.model_id,
      temperature: profile.temperature,
      max_tokens: profile.max_tokens,
      timeout_seconds: profile.timeout_seconds,
      purpose_tags: profile.purpose_tags,
      deployment: profile.deployment,
      is_default: profile.is_default,
    })
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const payload: LLMProfilePayload = {
        name: values.name,
        provider: values.provider,
        api_url: values.api_url,
        model_id: values.model_id,
        temperature: values.temperature ?? null,
        max_tokens: values.max_tokens ?? null,
        timeout_seconds: values.timeout_seconds,
        purpose_tags: values.purpose_tags || [],
        deployment: values.deployment,
        is_default: !!values.is_default,
      }
      if (values.api_key) payload.api_key = values.api_key
      if (editing) {
        await updateLlmProfile(editing.id, payload)
        message.success(text.updateOk)
      } else {
        await createLlmProfile(payload)
        message.success(text.createOk)
      }
      setModalOpen(false)
      load()
    } catch (error) {
      message.error(formatApiError(error, editing ? text.updateFailed : text.createFailed))
    } finally {
      setSaving(false)
    }
  }

  const runProbe = async (profile: LLMProfile) => {
    setTestingId(profile.id)
    try {
      const result = await testLlmProfile(profile.id)
      if (result.ok) {
        message.success(`${text.probeOk} (${result.latency_ms ?? '?'} ms)`)
      } else {
        message.warning(`${text.probeFailed}: ${result.error || result.status_code || ''}`)
      }
    } catch (error) {
      message.error(formatApiError(error, text.probeFailed))
    } finally {
      setTestingId(null)
    }
  }

  const remove = async (profile: LLMProfile) => {
    try {
      await deleteLlmProfile(profile.id)
      message.success(text.deleteOk)
      load()
    } catch (error) {
      message.error(formatApiError(error, text.deleteFailed))
    }
  }

  const columns = [
    {
      title: text.colName,
      dataIndex: 'name',
      render: (value: string, record: LLMProfile) => (
        <Space>
          <span>{value}</span>
          {record.is_default && <Tag color="blue">{text.defaultTag}</Tag>}
        </Space>
      ),
    },
    { title: text.colProvider, dataIndex: 'provider' },
    { title: 'URL', dataIndex: 'api_url', ellipsis: true },
    { title: text.colModel, dataIndex: 'model_id' },
    {
      title: text.colDeployment,
      dataIndex: 'deployment',
      render: (value: string) => (
        <Tag color={value === 'private' ? 'purple' : 'green'}>
          {value === 'private' ? text.deploymentPrivate : text.deploymentCloud}
        </Tag>
      ),
    },
    { title: text.colKey, dataIndex: 'api_key_masked', render: (value: string | null) => value || '-' },
    {
      title: text.colPurposes,
      dataIndex: 'purpose_tags',
      render: (value: string[]) => (value || []).map((tag) => <Tag key={tag}>{tag}</Tag>),
    },
    {
      title: text.colActions,
      render: (_: unknown, record: LLMProfile) => (
        <Space>
          <Button size="small" icon={<ApiOutlined />} loading={testingId === record.id} onClick={() => runProbe(record)}>
            {text.probe}
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            {text.edit}
          </Button>
          <Popconfirm title={text.deleteConfirm} onConfirm={() => remove(record)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              {text.delete}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <AppLayout>
      <Card
        title={text.title}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>
              {text.refresh}
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              {text.create}
            </Button>
          </Space>
        }
      >
        <Table rowKey="id" columns={columns as never} dataSource={profiles} loading={loading} pagination={false} />
      </Card>
      <Modal
        title={editing ? text.editTitle : text.createTitle}
        open={modalOpen}
        onOk={submit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        width={640}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label={text.colName} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="provider" label={text.colProvider} rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'openai_compatible', label: 'OpenAI 兼容' },
                { value: 'custom', label: text.providerCustom },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="api_url"
            label="URL"
            rules={[{ required: true }, { pattern: /^https:\/\//, message: text.httpsOnly }]}
          >
            <Input placeholder="https://..." />
          </Form.Item>
          <Form.Item
            name="api_key"
            label={text.colKey}
            extra={editing ? text.keyKeepBlank : text.keyWriteOnly}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="model_id" label={text.colModel} rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="deployment" label={text.colDeployment} rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'cloud', label: text.deploymentCloud },
                { value: 'private', label: text.deploymentPrivate },
              ]}
            />
          </Form.Item>
          <Form.Item name="purpose_tags" label={text.colPurposes}>
            <Select mode="multiple" options={PURPOSE_OPTIONS.map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Space size="large">
            <Form.Item name="timeout_seconds" label={text.colTimeout}>
              <InputNumber min={1} max={600} />
            </Form.Item>
            <Form.Item name="temperature" label="temperature">
              <InputNumber min={0} max={2} step={0.1} />
            </Form.Item>
            <Form.Item name="max_tokens" label="max_tokens">
              <InputNumber min={1} />
            </Form.Item>
          </Space>
          <Form.Item name="is_default" label={text.setDefault} valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  )
}
