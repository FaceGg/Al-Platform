import { Form, Input, Button, Card, message, Select, Typography } from "antd";
import { UserOutlined, LockOutlined } from "@ant-design/icons";
import { useNavigate, Link } from "react-router-dom";
import apiClient from "../api/client";

const { Title, Text } = Typography;

export default function RegisterPage() {
  const navigate = useNavigate();

  const onFinish = async (values: { username: string; password: string; role: string }) => {
    try {
      await apiClient.post("/auth/register", values);
      message.success("注册成功，请登录");
      navigate("/login");
    } catch (error: any) {
      message.error(error.response?.data?.detail || "注册失败");
    }
  };

  return (
    <main className="auth-screen">
      <Card className="auth-card" styles={{ body: { padding: "42px 38px" } }}>
        <div className="auth-heading">
          <Title level={3}>注册新账号</Title>
          <Text type="secondary">创建您的智擎账户</Text>
        </div>
        <Form onFinish={onFinish} size="large" initialValues={{ role: "engineer" }}>
          <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" className="auth-input" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, min: 6, message: "密码至少6位" }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" className="auth-input" />
          </Form.Item>
          <Form.Item name="role" label={<Text type="secondary">角色</Text>}>
            <Select
              options={[{ value: "engineer", label: "工程师" }, { value: "viewer", label: "查看者" }]}
              className="auth-select"
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 12 }}>
            <Button type="primary" htmlType="submit" block className="auth-submit">注册</Button>
          </Form.Item>
          <div className="auth-link">
            <Text type="secondary">已有账号？ <Link to="/login">返回登录</Link></Text>
          </div>
        </Form>
      </Card>
    </main>
  );
}
