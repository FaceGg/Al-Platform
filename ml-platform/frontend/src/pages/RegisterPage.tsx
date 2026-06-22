import { Form, Input, Button, Card, message } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate, Link } from 'react-router-dom'
import apiClient from '../api/client'

export default function RegisterPage() {
  const navigate = useNavigate()
  const onFinish = async (values: { username: string; password: string; confirm: string }) => {
    if (values.password !== values.confirm) {
      message.error('两次密码输入不一致')
      return
    }
    try {
      await apiClient.post('/auth/register', {
        username: values.username,
        password: values.password,
      })
      message.success('注册成功，请登录')
      navigate('/login')
    } catch {
      message.error('注册失败，用户名可能已存在')
    }
  }

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', background: '#f0f2f5' }}>
      <Card title="ML 算法平台 - 注册" style={{ width: 400, boxShadow: '0 2px 8px rgba(0,0,0,0.1)' }}>
        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item name="confirm" rules={[{ required: true, message: '请确认密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="确认密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>注册</Button>
          <div style={{ textAlign: 'center', marginTop: 12 }}>
            已有账号？<Link to="/login">立即登录</Link>
          </div>
        </Form>
      </Card>
    </div>
  )
}
