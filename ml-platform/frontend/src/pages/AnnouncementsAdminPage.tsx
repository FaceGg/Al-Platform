import { useCallback, useEffect, useState } from 'react'
import { App as AntApp, Button, Form, Input, Modal, Popconfirm, Space, Switch, Table } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'
import { useI18n } from '../i18n'

interface Announcement {
  id: string
  title: string
  content: string
  pinned: boolean
  created_by?: string | null
  created_at?: string | null
  updated_at?: string | null
}

interface AnnouncementFormValues {
  title: string
  content?: string
  pinned?: boolean
}

/** 系统管理→公告管理：门户「平台公告」面板数据的维护入口。 */
export default function AnnouncementsAdminPage() {
  const { message } = AntApp.useApp()
  const { lang } = useI18n()
  const zh = lang === 'zh'
  const [items, setItems] = useState<Announcement[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState<Announcement | null>(null)
  const [form] = Form.useForm<AnnouncementFormValues>()

  const load = useCallback(() => {
    setLoading(true)
    apiClient.get('/announcements').then((res) => {
      setItems(Array.isArray(res.data) ? res.data : [])
    }).catch(() => setItems([])).finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const openCreate = () => {
    setEditing(null)
    form.setFieldsValue({ title: '', content: '', pinned: false })
    setModalOpen(true)
  }

  const openEdit = (item: Announcement) => {
    setEditing(item)
    form.setFieldsValue({ title: item.title, content: item.content, pinned: item.pinned })
    setModalOpen(true)
  }

  const submit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        await apiClient.patch(`/announcements/${editing.id}`, values)
        message.success(zh ? '公告已更新' : 'Notice updated')
      } else {
        await apiClient.post('/announcements', values)
        message.success(zh ? '公告已发布' : 'Notice published')
      }
      setModalOpen(false)
      load()
    } catch {
      message.error(zh ? '保存失败' : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (item: Announcement) => {
    try {
      await apiClient.delete(`/announcements/${item.id}`)
      message.success(zh ? '公告已删除' : 'Notice deleted')
      load()
    } catch {
      message.error(zh ? '删除失败' : 'Delete failed')
    }
  }

  return (
    <AppLayout>
      <div className="v2-crumb">{zh ? '系统管理 / ' : 'Administration / '}<b>{zh ? '公告管理' : 'Notices'}</b></div>
      <div className="v2-pagehead">
        <div>
          <h2>{zh ? '公告管理' : 'Notice Management'}</h2>
          <div className="v2-pdesc">
            {zh
              ? '维护门户首页「平台公告」面板：新增、编辑、置顶与删除公告。'
              : 'Maintain the portal notices panel: publish, edit, pin and delete notices.'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 9 }}>
          <button type="button" className="v2-btn" onClick={load}>
            <ReloadOutlined spin={loading} /> {zh ? '刷新' : 'Refresh'}
          </button>
          <button type="button" className="v2-btn primary" onClick={openCreate}>
            <PlusOutlined /> {zh ? '发布公告' : 'New Notice'}
          </button>
        </div>
      </div>

      <div className="v2-panel">
        <Table<Announcement>
          rowKey="id"
          size="middle"
          loading={loading}
          dataSource={items}
          pagination={items.length > 10 ? { pageSize: 10, showSizeChanger: false } : false}
          locale={{ emptyText: zh ? '暂无公告' : 'No notices' }}
          columns={[
            {
              title: zh ? '标题' : 'Title',
              dataIndex: 'title',
              render: (value: string, record) => (
                <span className="tt">
                  {record.pinned ? '📌 ' : ''}{value}
                </span>
              ),
            },
            {
              title: zh ? '内容' : 'Content',
              dataIndex: 'content',
              ellipsis: true,
              render: (value: string) => value || '—',
            },
            {
              title: zh ? '发布者' : 'Publisher',
              dataIndex: 'created_by',
              width: 120,
              render: (value: string | null) => value || '—',
            },
            {
              title: zh ? '发布时间' : 'Published',
              dataIndex: 'created_at',
              width: 160,
              render: (value: string | null) =>
                value ? new Date(value).toLocaleString(zh ? 'zh-CN' : 'en-US') : '—',
            },
            {
              title: zh ? '操作' : 'Actions',
              key: 'actions',
              width: 150,
              render: (_: unknown, record) => (
                <Space size={4}>
                  <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
                    {zh ? '编辑' : 'Edit'}
                  </Button>
                  <Popconfirm
                    title={zh ? '确认删除该公告？' : 'Delete this notice?'}
                    onConfirm={() => remove(record)}
                  >
                    <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                      {zh ? '删除' : 'Delete'}
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </div>

      <Modal
        title={editing ? (zh ? '编辑公告' : 'Edit Notice') : zh ? '发布公告' : 'New Notice'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={submit}
        confirmLoading={saving}
        okText={zh ? '保存' : 'Save'}
        cancelText={zh ? '取消' : 'Cancel'}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="title"
            label={zh ? '标题' : 'Title'}
            rules={[{ required: true, message: zh ? '请输入公告标题' : 'Title is required' }]}
          >
            <Input maxLength={200} placeholder={zh ? '公告标题' : 'Notice title'} />
          </Form.Item>
          <Form.Item name="content" label={zh ? '内容' : 'Content'}>
            <Input.TextArea rows={4} maxLength={4000} placeholder={zh ? '公告内容（可选）' : 'Notice content (optional)'} />
          </Form.Item>
          <Form.Item name="pinned" label={zh ? '置顶' : 'Pinned'} valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  )
}
