import { App as AntApp, Form, Input, Button, Card, Typography } from "antd";
import { UserOutlined, LockOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useNavigate, Link } from "react-router-dom";
import { login } from "../api/auth";
import { useTheme } from "../stores/themeContext";

const { Title, Text } = Typography;

export default function LoginPage() {
  const { message } = AntApp.useApp();
  const { theme } = useTheme();
  const navigate = useNavigate();

  const onFinish = async (values: { username: string; password: string }) => {
    try {
      const result = await login(values.username, values.password);
      localStorage.setItem("token", result.access_token);
      localStorage.setItem("userId", result.user_id);
      localStorage.setItem("username", values.username);
      localStorage.setItem("role", result.role);
      message.success("登录成功");
      navigate("/");
    } catch {
      message.error("用户名或密码错误");
    }
  };

  return (
    <main className="auth-screen" data-theme={theme}>
      <Card className="auth-card" styles={{ body: { padding: "42px 38px" } }}>
        <div className="auth-heading">
          <div className="auth-mark">
            <ThunderboltOutlined />
          </div>
          <Title level={3}>灵工</Title>
          <Text type="secondary">工业智能平台</Text>
        </div>

        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" className="auth-input" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" className="auth-input" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 12 }}>
            <Button type="primary" htmlType="submit" block className="auth-submit">登录</Button>
          </Form.Item>
          <div className="auth-link">
            <Text type="secondary">还没有账号？ <Link to="/register">立即注册</Link></Text>
          </div>
        </Form>

        <div className="auth-note">
          <Text type="secondary">默认账号: admin / admin123</Text>
        </div>
      </Card>
    </main>
  );
}
