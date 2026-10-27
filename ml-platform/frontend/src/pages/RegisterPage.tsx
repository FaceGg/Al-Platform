import { Form, Input, Button, Card, message, Select, Typography } from "antd";
import { UserOutlined, LockOutlined } from "@ant-design/icons";
import { useNavigate, Link } from "react-router-dom";
import apiClient, { formatApiError } from "../api/client";

const { Title, Text } = Typography;

const PASSWORD_POLICY_MESSAGE = "密码必须包含数字、大写字母、小写字母、符号中的至少 3 种";

// 与后端 app/services/security.py 的注册口令策略保持一致
function passwordCharacterClasses(value: string): number {
  let hasDigit = false;
  let hasLower = false;
  let hasUpper = false;
  let hasSymbol = false;
  for (const char of value) {
    if (char >= "0" && char <= "9") hasDigit = true;
    else if (char >= "a" && char <= "z") hasLower = true;
    else if (char >= "A" && char <= "Z") hasUpper = true;
    else hasSymbol = true;
  }
  return [hasDigit, hasLower, hasUpper, hasSymbol].filter(Boolean).length;
}

export default function RegisterPage() {
  const navigate = useNavigate();

  const onFinish = async (values: { username: string; password: string; role: string }) => {
    try {
      await apiClient.post("/auth/register", values);
      message.success("注册成功，请登录");
      navigate("/login");
    } catch (error: any) {
      message.error(formatApiError(error, "注册失败"));
    }
  };

  return (
    <main className="auth-screen">
      <Card className="auth-card" styles={{ body: { padding: "42px 38px" } }}>
        <div className="auth-heading">
          <Title level={3}>注册新账号</Title>
          <Text type="secondary">创建您的灵工账户</Text>
        </div>
        <Form onFinish={onFinish} size="large" initialValues={{ role: "engineer" }} autoComplete="off">
          <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" className="auth-input" autoComplete="new-username" />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[
              { required: true, message: "请输入密码" },
              { min: 8, message: "密码至少 8 位" },
              {
                validator: (_rule, value: string) =>
                  !value || passwordCharacterClasses(value) >= 3
                    ? Promise.resolve()
                    : Promise.reject(new Error(PASSWORD_POLICY_MESSAGE)),
              },
            ]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码" className="auth-input" autoComplete="new-password" />
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
