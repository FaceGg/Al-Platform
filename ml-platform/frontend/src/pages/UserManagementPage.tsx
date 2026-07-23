import { useEffect, useState, type Key } from 'react'
import { Table, Tag, Button, Modal, Descriptions, Form, Input, message, Popconfirm, Space } from 'antd'
import { EyeOutlined, LockOutlined, DeleteOutlined } from '@ant-design/icons'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'
import { useI18n } from '../i18n'

interface User {
  id: string
  username: string
  role: string
  created_at: string
}

export default function UserManagementPage() {
  const { t } = useI18n()
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(false)
  const [currentUserRole, setCurrentUserRole] = useState('')
  const [currentUserId, setCurrentUserId] = useState('')
  const [infoOpen, setInfoOpen] = useState(false)
  const [pwdOpen, setPwdOpen] = useState(false)
  const [selectedUser, setSelectedUser] = useState<User | null>(null)
  const [pwdForm] = Form.useForm()
  const [pwdLoading, setPwdLoading] = useState(false)
  const [selectedUserIds, setSelectedUserIds] = useState<Key[]>([])

  useEffect(() => {
    setCurrentUserRole(localStorage.getItem('role') || '')
    setCurrentUserId(localStorage.getItem('userId') || '')
  }, [])

  useEffect(() => {
    if (!currentUserRole) return
    setLoading(true)
    const fetchUrl = currentUserRole === 'admin' ? '/admin/users' : '/auth/me'
    apiClient.get(fetchUrl)
      .then(res => {
        const data = res.data.items || res.data.users || (Array.isArray(res.data) ? res.data : [res.data])
        setUsers(data)
      })
      .catch(() => message.error(t.common.error))
      .finally(() => setLoading(false))
  }, [currentUserRole, t.common.error])

  const showInfo = (user: User) => { setSelectedUser(user); setInfoOpen(true) }

  const showPwd = (user: User) => { setSelectedUser(user); setPwdOpen(true); pwdForm.resetFields() }

  const changePassword = async (values: any) => {
    setPwdLoading(true)
    try {
      await apiClient.put('/auth/change-password', values)
      message.success(t.common.success)
      setPwdOpen(false)
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error)
    } finally {
      setPwdLoading(false)
    }
  }

  const deleteUser = async (userId: string) => {
    try {
      await apiClient.delete('/admin/users/' + userId)
      message.success('用户已删除')
      setUsers(prev => prev.filter(u => u.id !== userId))
    } catch (e: any) {
      message.error(e.response?.data?.detail || '删除失败')
    }
  }

  const batchDeleteUsers = () => {
    const userIds = selectedUserIds.map(String)
    if (userIds.length === 0) return
    Modal.confirm({
      title: `${t.common.batch_delete} (${userIds.length})`,
      content: t.common.delete,
      okType: 'danger',
      onOk: async () => {
        try {
          const response = await apiClient.post('/admin/users/batch-delete', { user_ids: userIds })
          const deletedIds = new Set<string>(response.data?.deleted_ids || [])
          setUsers(prev => prev.filter(user => !deletedIds.has(user.id)))
          setSelectedUserIds([])
          message.success(t.common.success)
        } catch (error: any) {
          message.error(error.response?.data?.detail || t.common.error)
        }
      },
    })
  }

  const columns = [
    { title: t.profile.username || '用户名', dataIndex: 'username', key: 'username' },
    {
      title: t.profile.role || '角色', dataIndex: 'role', key: 'role',
      render: (role: string) => {
        const color = role === 'admin' ? 'red' : role === 'engineer' ? 'blue' : 'green'
        return <Tag color={color}>{role === 'admin' ? t.profile.admin : role === 'engineer' ? t.profile.engineer : t.profile.user}</Tag>
      },
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v ? new Date(v).toLocaleDateString() : '-' },
    {
      title: '操作', key: 'actions',
      render: (_: any, record: User) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => showInfo(record)}>查看</Button>
          {record.id === currentUserId && (
            <Button size="small" icon={<LockOutlined />} onClick={() => showPwd(record)}>修改密码</Button>
          )}
          {currentUserRole === 'admin' && record.id !== currentUserId && (
            <Popconfirm title="确定要删除此用户吗？" onConfirm={() => deleteUser(record.id)} okText="删除" cancelText="取消">
              <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <AppLayout>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3>{t.nav.users || '用户管理'}</h3>
        {currentUserRole === 'admin' && selectedUserIds.length > 0 && (
          <Button danger icon={<DeleteOutlined />} onClick={batchDeleteUsers}>
            {t.common.batch_delete} ({selectedUserIds.length})
          </Button>
        )}
      </div>
      <Table
        rowKey="id"
        dataSource={users}
        columns={columns}
        loading={loading}
        pagination={{ pageSize: 20 }}
        rowSelection={currentUserRole === 'admin' ? {
          selectedRowKeys: selectedUserIds,
          onChange: setSelectedUserIds,
          getCheckboxProps: (record: User) => ({ disabled: record.id === currentUserId }),
        } : undefined}
      />

      {/* 用户信息弹窗 */}
      <Modal title="用户信息" open={infoOpen} onCancel={() => setInfoOpen(false)} footer={null}>
        {selectedUser && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID">{selectedUser.id}</Descriptions.Item>
            <Descriptions.Item label="用户名">{selectedUser.username}</Descriptions.Item>
            <Descriptions.Item label="角色">
              <Tag color={selectedUser.role === 'admin' ? 'red' : 'blue'}>{selectedUser.role}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">{selectedUser.created_at ? new Date(selectedUser.created_at).toLocaleString() : '-'}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

      {/* 修改密码弹窗 */}
      <Modal title="修改密码" open={pwdOpen} onCancel={() => setPwdOpen(false)} onOk={() => pwdForm.submit()} confirmLoading={pwdLoading}>
        <Form form={pwdForm} onFinish={changePassword} layout="vertical">
          <Form.Item name="old_password" label="旧密码" rules={[{ required: true, message: '请输入旧密码' }]}>
            <Input.Password placeholder="请输入旧密码" />
          </Form.Item>
          <Form.Item name="new_password" label="新密码" rules={[{ required: true, message: '请输入新密码' }, { min: 6, message: '密码至少6位' }]}>
            <Input.Password placeholder="请输入新密码" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请确认新密码' },
              ({ getFieldValue }) => ({
                validator(_: any, value: string) {
                  if (!value || getFieldValue('new_password') === value) return Promise.resolve()
                  return Promise.reject(new Error('两次密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password placeholder="请再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  )
}
