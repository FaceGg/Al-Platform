import { useEffect, useState } from 'react'
import { Table, Select, message, Tag } from 'antd'
import apiClient from '../api/client'
import AppLayout from '../components/AppLayout'
import { useI18n } from '../i18n'

interface User {
  id: number
  username: string
  role: string
  created_at: string
}

export default function UserManagementPage() {
  const { t } = useI18n()
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    apiClient.get('/admin/users').then((res) => {
      setUsers(res.data.items || res.data.users || [])
    }).catch(() => {
      message.error(t.common.error)
    }).finally(() => setLoading(false))
  }, [])

  const handleRoleChange = async (userId: number, newRole: string) => {
    try {
      await apiClient.put('/admin/users/' + userId + '/role', { role: newRole })
      message.success(t.common.success)
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, role: newRole } : u))
    } catch {
      message.error(t.common.error)
    }
  }

  const columns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (role: string) => (
        <Tag color={role === 'admin' ? 'red' : role === 'engineer' ? 'blue' : 'default'}>
          {t.profile[role as keyof typeof t.profile] || role}
        </Tag>
      ),
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at' },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: User) => {
        const currentUserId = localStorage.getItem('userId')
        if (record.id.toString() === currentUserId) return <span>-</span>
        return (
          <Select
            value={record.role}
            style={{ width: 120 }}
            onChange={(val) => handleRoleChange(record.id, val)}
            options={[
              { value: 'admin', label: t.profile.admin },
              { value: 'engineer', label: t.profile.engineer },
            ]}
          />
        )
      },
    },
  ]

  return (
    <AppLayout>
      <Table
        dataSource={users}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20 }}
      />
    </AppLayout>
  )
}
