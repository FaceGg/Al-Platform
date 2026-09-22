import { useEffect, useState, type Key } from 'react'
import { Table, Tag, Button, Modal, Descriptions, Form, Input, message, Popconfirm, Space, Card, Select } from 'antd'
import { EyeOutlined, LockOutlined, DeleteOutlined, CheckOutlined, CloseOutlined, ReloadOutlined, KeyOutlined, StopOutlined, SafetyOutlined } from '@ant-design/icons'
import apiClient, { formatApiError } from '../api/client'
import { grantAnnotatorProject, listAnnotatorProjectGrants, revokeAnnotatorProject } from '../api/annotatorAssignments'
import AppLayout from '../components/AppLayout'
import { useI18n } from '../i18n'
import { formatLocalTime } from '../utils/time'

interface User {
  id: string
  username: string
  role: string
  created_at: string
}

interface AnnotatorAccount {
  id: string
  subject_id: string
  username: string
  email?: string | null
  status: 'pending' | 'active' | 'rejected' | 'disabled'
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
  const [annotators, setAnnotators] = useState<AnnotatorAccount[]>([])
  const [annotatorsLoading, setAnnotatorsLoading] = useState(false)
  const [resetPwdTarget, setResetPwdTarget] = useState<AnnotatorAccount | null>(null)
  const [resetPwdForm] = Form.useForm()
  const [resetPwdLoading, setResetPwdLoading] = useState(false)
  const [grantTarget, setGrantTarget] = useState<AnnotatorAccount | null>(null)
  const [grantProjects, setGrantProjects] = useState<{ id: string; name: string }[]>([])
  const [grantActiveIds, setGrantActiveIds] = useState<string[]>([])
  const [grantSelected, setGrantSelected] = useState<string[]>([])
  const [grantLoading, setGrantLoading] = useState(false)
  const [grantSaving, setGrantSaving] = useState(false)

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

  const loadAnnotators = async () => {
    if (currentUserRole !== 'admin') return
    setAnnotatorsLoading(true)
    try {
      const response = await apiClient.get('/admin/annotators')
      setAnnotators(response.data.items || [])
    } catch (error: any) {
      message.error(error.response?.data?.detail?.message || error.response?.data?.detail || '标注员账号加载失败')
    } finally {
      setAnnotatorsLoading(false)
    }
  }

  useEffect(() => { void loadAnnotators() }, [currentUserRole])

  const updateAnnotatorStatus = async (account: AnnotatorAccount, status: 'active' | 'rejected' | 'disabled') => {
    try {
      await apiClient.patch(`/admin/annotators/${account.subject_id}/status`, { status })
      const successText = status === 'active' ? '标注员账号已启用' : status === 'disabled' ? '标注员账号已停用' : '标注员账号已拒绝'
      message.success(successText)
      await loadAnnotators()
    } catch (error: any) {
      message.error(error.response?.data?.detail?.message || error.response?.data?.detail || '操作失败')
    }
  }

  const deleteAnnotatorAccount = async (account: AnnotatorAccount) => {
    try {
      await apiClient.delete(`/admin/annotators/${account.subject_id}`)
      message.success('标注员账号已删除')
      await loadAnnotators()
    } catch (error: any) {
      message.error(error.response?.data?.detail?.message || error.response?.data?.detail || '删除失败')
    }
  }

  const resetAnnotatorPassword = async (values: { password: string }) => {
    if (!resetPwdTarget) return
    setResetPwdLoading(true)
    try {
      await apiClient.post(`/internal/annotators/${resetPwdTarget.subject_id}/reset-password`, { password: values.password })
      message.success('标注员密码已重置')
      setResetPwdTarget(null)
      resetPwdForm.resetFields()
    } catch (error: any) {
      message.error(error.response?.data?.detail?.message || error.response?.data?.detail || '重置密码失败')
    } finally {
      setResetPwdLoading(false)
    }
  }

  const openGrantModal = async (account: AnnotatorAccount) => {
    setGrantTarget(account)
    setGrantProjects([])
    setGrantSelected([])
    setGrantActiveIds([])
    setGrantLoading(true)
    try {
      const [projectsResponse, grants] = await Promise.all([
        apiClient.get('/projects'),
        listAnnotatorProjectGrants(account.subject_id),
      ])
      const projects = projectsResponse.data.items || projectsResponse.data || []
      setGrantProjects(projects)
      const activeIds = grants.filter((grant) => grant.status === 'active').map((grant) => grant.project_id)
      setGrantActiveIds(activeIds)
      setGrantSelected(activeIds)
    } catch (error: any) {
      message.error(formatApiError(error, '授权信息加载失败'))
    } finally {
      setGrantLoading(false)
    }
  }

  const saveAnnotatorGrants = async () => {
    if (!grantTarget) return
    setGrantSaving(true)
    try {
      const previous = new Set(grantActiveIds)
      const next = new Set(grantSelected)
      const toGrant = [...next].filter((id) => !previous.has(id))
      const toRevoke = [...previous].filter((id) => !next.has(id))
      for (const projectId of toGrant) {
        await grantAnnotatorProject(projectId, grantTarget.subject_id)
      }
      for (const projectId of toRevoke) {
        await revokeAnnotatorProject(projectId, grantTarget.subject_id)
      }
      message.success('项目授权已更新')
      setGrantTarget(null)
    } catch (error: any) {
      message.error(formatApiError(error, '项目授权更新失败'))
    } finally {
      setGrantSaving(false)
    }
  }

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
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => formatLocalTime(v) },
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
      {currentUserRole === 'admin' && (
        <Card
          title="标注员账号审核"
          extra={<Button icon={<ReloadOutlined />} onClick={() => void loadAnnotators()}>刷新</Button>}
          style={{ marginBottom: 24 }}
        >
          <Table
            rowKey="id"
            size="small"
            loading={annotatorsLoading}
            dataSource={annotators.filter(a => a.status === 'pending' || a.status === 'rejected')}
            pagination={{ pageSize: 10 }}
            locale={{ emptyText: '暂无待审核的注册申请' }}
            columns={[
              { title: '用户名', dataIndex: 'username' },
              { title: '邮箱', dataIndex: 'email', render: (value: string | null) => value || '-' },
              { title: '申请时间', dataIndex: 'created_at', render: (value: string) => formatLocalTime(value) },
              { title: '状态', dataIndex: 'status', render: (status: AnnotatorAccount['status']) => <Tag color={status === 'pending' ? 'gold' : 'red'}>{status === 'pending' ? '待审核' : '已拒绝'}</Tag> },
              {
                title: '操作',
                render: (_: unknown, account: AnnotatorAccount) => (
                  <Space>
                    {account.status === 'pending' && (
                      <>
                        <Popconfirm title="确认通过该标注员账号？" onConfirm={() => void updateAnnotatorStatus(account, 'active')} okText="通过" cancelText="取消">
                          <Button type="primary" size="small" icon={<CheckOutlined />}>通过</Button>
                        </Popconfirm>
                        <Popconfirm title="确认拒绝该注册申请？" onConfirm={() => void updateAnnotatorStatus(account, 'rejected')} okText="拒绝" cancelText="取消">
                          <Button danger size="small" icon={<CloseOutlined />}>拒绝</Button>
                        </Popconfirm>
                      </>
                    )}
                    <Popconfirm title="确认删除该标注员账号？删除后不可恢复。" onConfirm={() => void deleteAnnotatorAccount(account)} okText="删除" cancelText="取消">
                      <Button danger size="small" icon={<DeleteOutlined />}>删除</Button>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      )}
      {currentUserRole === 'admin' && (
        <Card
          title="标注员管理"
          extra={<Button icon={<ReloadOutlined />} onClick={() => void loadAnnotators()}>刷新</Button>}
          style={{ marginBottom: 24 }}
        >
          <Table
            rowKey="id"
            size="small"
            loading={annotatorsLoading}
            dataSource={annotators.filter(a => a.status === 'active' || a.status === 'disabled')}
            pagination={{ pageSize: 10 }}
            locale={{ emptyText: '暂无已审核通过的标注员' }}
            columns={[
              { title: '用户名', dataIndex: 'username' },
              { title: '邮箱', dataIndex: 'email', render: (value: string | null) => value || '-' },
              { title: '创建时间', dataIndex: 'created_at', render: (value: string) => formatLocalTime(value) },
              { title: '状态', dataIndex: 'status', render: (status: AnnotatorAccount['status']) => <Tag color={status === 'active' ? 'green' : 'default'}>{status === 'active' ? '已启用' : '已停用'}</Tag> },
              {
                title: '操作',
                render: (_: unknown, account: AnnotatorAccount) => (
                  <Space>
                    {account.status === 'active' ? (
                      <Popconfirm title="确认停用该标注员？停用后将无法登录门户。" onConfirm={() => void updateAnnotatorStatus(account, 'disabled')} okText="停用" cancelText="取消">
                        <Button size="small" icon={<StopOutlined />}>停用</Button>
                      </Popconfirm>
                    ) : (
                      <Popconfirm title="确认启用该标注员账号？" onConfirm={() => void updateAnnotatorStatus(account, 'active')} okText="启用" cancelText="取消">
                        <Button type="primary" size="small" icon={<CheckOutlined />}>启用</Button>
                      </Popconfirm>
                    )}
                    {account.status === 'active' && (
                      <Button size="small" icon={<SafetyOutlined />} onClick={() => { void openGrantModal(account) }}>授权项目</Button>
                    )}
                    <Button size="small" icon={<KeyOutlined />} onClick={() => { setResetPwdTarget(account); resetPwdForm.resetFields() }}>重置密码</Button>
                    <Popconfirm title="确认删除该标注员账号？删除后不可恢复，其所有指派将被撤销。" onConfirm={() => void deleteAnnotatorAccount(account)} okText="删除" cancelText="取消">
                      <Button danger size="small" icon={<DeleteOutlined />}>删除</Button>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      )}
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
            <Descriptions.Item label="创建时间">{formatLocalTime(selectedUser.created_at, true)}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

      {/* 修改密码弹窗 */}
      <Modal title="修改密码" open={pwdOpen} onCancel={() => setPwdOpen(false)} onOk={() => pwdForm.submit()} confirmLoading={pwdLoading}>
        <Form form={pwdForm} onFinish={changePassword} layout="vertical" autoComplete="off">
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
      {/* 标注员重置密码弹窗 */}
      <Modal
        title={`重置标注员密码${resetPwdTarget ? `：${resetPwdTarget.username}` : ''}`}
        open={resetPwdTarget !== null}
        onCancel={() => setResetPwdTarget(null)}
        onOk={() => resetPwdForm.submit()}
        confirmLoading={resetPwdLoading}
      >
        <Form form={resetPwdForm} onFinish={resetAnnotatorPassword} layout="vertical" autoComplete="off">
          <Form.Item name="password" label="新密码" rules={[{ required: true, message: '请输入新密码' }, { min: 8, message: '密码至少8位' }]}>
            <Input.Password placeholder="请输入新密码（8-128位）" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            dependencies={['password']}
            rules={[
              { required: true, message: '请确认新密码' },
              ({ getFieldValue }) => ({
                validator(_: any, value: string) {
                  if (!value || getFieldValue('password') === value) return Promise.resolve()
                  return Promise.reject(new Error('两次密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password placeholder="请再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>
      {/* 标注员项目授权弹窗 */}
      <Modal
        title={`项目授权${grantTarget ? `：${grantTarget.username}` : ''}`}
        open={grantTarget !== null}
        onCancel={() => setGrantTarget(null)}
        onOk={() => { void saveAnnotatorGrants() }}
        confirmLoading={grantSaving}
        okText="保存"
        cancelText="取消"
      >
        <p>勾选该标注员可访问的项目；取消勾选将撤销授权，并撤回其在该项目下的所有指派。</p>
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          placeholder="选择要授权的项目"
          value={grantSelected}
          onChange={setGrantSelected}
          loading={grantLoading}
          options={grantProjects.map((project) => ({ value: project.id, label: project.name }))}
        />
      </Modal>
    </AppLayout>
  )
}
