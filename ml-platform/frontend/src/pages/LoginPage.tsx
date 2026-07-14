import { Form, Input, Button, Card, message, Typography } from "antd";
import { UserOutlined, LockOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useNavigate, Link } from "react-router-dom";
import { login } from "../api/auth";
import { useTheme } from "../stores/themeContext";

const { Title, Text } = Typography;

export default function LoginPage() {
  const { theme } = useTheme();
  const navigate = useNavigate();

  const onFinish = async (values: { username: string; password: string }) => {
    try {
      const result = await login(values.username, values.password);
      localStorage.setItem("token", result.access_token);
      localStorage.setItem("userId", result.user_id);
      localStorage.setItem("role", result.role);
      message.success("登录成功");
      navigate("/");
    } catch {
      message.error("用户名或密码错误");
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: theme === "dark" ? "linear-gradient(135deg, #0D1117 0%, #161B22 50%, #0D1117 100%)" : "linear-gradient(135deg, #F5F7FA 0%, #FFFFFF 50%, #F5F7FA 100%)", position: "relative", overflow: "hidden" }}>
      <div style={{ position: "absolute", top: "-20%", right: "-10%", width: 500, height: 500, borderRadius: "50%", background: "radial-gradient(circle, rgba(240,136,62,0.08) 0%, transparent 70%)" }} />
      <div style={{ position: "absolute", bottom: "-15%", left: "-5%", width: 400, height: 400, borderRadius: "50%", background: "radial-gradient(circle, rgba(88,166,255,0.06) 0%, transparent 70%)" }} />

      <Card style={{ width: 420, border: theme === "dark" ? "1px solid #30363D" : "1px solid #D0D7DE", background: theme === "dark" ? "#161B22" : "#FFFFFF", borderRadius: 16, boxShadow: "0 16px 48px rgba(0,0,0,0.4)", position: "relative", zIndex: 1 }} bodyStyle={{ padding: "40px 36px" }}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{ width: 56, height: 56, borderRadius: 14, background: "linear-gradient(135deg, #F0883E, #F5A623)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
            <ThunderboltOutlined style={{ color: "#fff", fontSize: 28 }} />
          </div>
          <Title level={3} style={{ margin: 0, color: "var(--text-primary)", fontWeight: 700 }}>AI模型训练编排平台</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>Precision Forge · 工业智能平台</Text>
        </div>

        <Form onFinish={onFinish} size="large">
          <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input prefix={<UserOutlined style={{ color: "var(--text-tertiary)" }} />} placeholder="用户名" style={{ borderRadius: 8, height: 46 }} />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password prefix={<LockOutlined style={{ color: "var(--text-tertiary)" }} />} placeholder="密码" style={{ borderRadius: 8, height: 46 }} />
          </Form.Item>
          <Form.Item style={{ marginBottom: 12 }}>
            <Button type="primary" htmlType="submit" block style={{ height: 46, borderRadius: 8, fontSize: 15, fontWeight: 600 }}>登录</Button>
          </Form.Item>
          <div style={{ textAlign: "center" }}>
            <Text type="secondary" style={{ fontSize: 13 }}>
              还没有账号？ <Link to="/register" style={{ color: "var(--accent-primary)" }}>立即注册</Link>
            </Text>
          </div>
        </Form>

        <div style={{ marginTop: 24, textAlign: "center" }}>
          <Text type="secondary" style={{ fontSize: 11 }}>默认账号: admin / admin123</Text>
        </div>
      </Card>
    </div>
  );
}
