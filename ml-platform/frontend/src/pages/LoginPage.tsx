import { Form, Input, Button, Card, message } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/client'

export default function LoginPage() {
  const navigate = useNavigate()
  const onFinish = async (values: { username: string; password: string }) => {
    try {
      const formData = new FormData()
      formData.append('username', values.username)
      formData.append('password', values.password)
      const res = await apiClient.post('/auth/login', formData)
      localStorage.setItem('token', res.data.access_token)
      localStorage.setItem('userId', res.data.user_id)
      localStorage.setItem('role', res.data.role)
      message.success('登录成功')
      navigate('/')
    } catch {
      message.error('用户名或密码错误')
    }
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f0f2f5' }}>
      <Card title="ML 算法平台" style={{ width: 400, boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }}>
        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>登录</Button>
        </Form>
      </Card>
    </div>
  )
}
