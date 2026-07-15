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
    } catch (e: any) {
      message.error(e.response?.data?.detail || "注册失败");
    }
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "linear-gradient(135deg, #0D1117 0%, #161B22 50%, #0D1117 100%)" }}>
      <div style={{ position: "absolute", top: "30%", left: "50%", transform: "translate(-50%, -50%)", width: 600, height: 600, borderRadius: "50%", background: "radial-gradient(circle, rgba(163,113,247,0.06) 0%, transparent 70%)" }} />
      <Card style={{ width: 420, border: "1px solid var(--border-default)", background: "var(--bg-surface)", borderRadius: 16, boxShadow: "0 16px 48px rgba(0,0,0,0.4)", position: "relative", zIndex: 1 }} styles={{ body: { padding: "40px 36px" } }}>
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <Title level={3} style={{ margin: 0, color: "var(--text-primary)", fontWeight: 700 }}>注册新账号</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>创建您的 Precision Forge 账户</Text>
        </div>
        <Form onFinish={onFinish} size="large" initialValues={{ role: "engineer" }}>
          <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input prefix={<UserOutlined style={{ color: "var(--text-tertiary)" }} />} placeholder="用户名" style={{ borderRadius: 8, height: 46 }} />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, min: 6, message: "密码至少6位" }]}>
            <Input.Password prefix={<LockOutlined style={{ color: "var(--text-tertiary)" }} />} placeholder="密码" style={{ borderRadius: 8, height: 46 }} />
          </Form.Item>
          <Form.Item name="role" label={<Text type="secondary" style={{ fontSize: 12 }}>角色</Text>}>
            <Select options={[{ value: "engineer", label: "工程师" }, { value: "viewer", label: "查看者" }]} style={{ borderRadius: 8 }} />
          </Form.Item>
          <Form.Item style={{ marginBottom: 12 }}>
            <Button type="primary" htmlType="submit" block style={{ height: 46, borderRadius: 8, fontSize: 15, fontWeight: 600 }}>注册</Button>
          </Form.Item>
          <div style={{ textAlign: "center" }}>
            <Text type="secondary" style={{ fontSize: 13 }}>已有账号？ <Link to="/login" style={{ color: "var(--accent-primary)" }}>返回登录</Link></Text>
          </div>
        </Form>
      </Card>
    </div>
  );
}
