import { useState, useRef, useEffect } from "react";
import { Card, Input, Button, Typography, Space, Spin, Tag, Empty, Divider } from "antd";
import { SendOutlined, RobotOutlined, UserOutlined, ClearOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

const { Text, Title } = Typography;

interface ChatMsg { role: "user" | "assistant" | "system"; content: string; time: string; }

export default function AIChatPage() {
  const { t } = useI18n();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<any>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    apiClient.get("/chat/status").then(r => setStatus(r.data)).catch(() => {});
  }, []);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text) return;
    const userMsg: ChatMsg = { role: "user", content: text, time: new Date().toLocaleTimeString() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const res = await apiClient.post("/chat", { message: text });
      const reply = res.data.reply || "No response.";
      setMessages(prev => [...prev, { role: "assistant", content: reply, time: new Date().toLocaleTimeString() }]);
    } catch (e: any) {
      setMessages(prev => [...prev, { role: "system", content: "Error: " + (e.response?.data?.detail || e.message), time: new Date().toLocaleTimeString() }]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  return (
    <AppLayout>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}><RobotOutlined /> AI Chat</Title>
        <Space>
          {status?.configured ? <Tag color="green">Connected: {status.model}</Tag> : <Tag color="red">{t.ai_chat.not_configured}</Tag>}
          <Button icon={<ClearOutlined />} onClick={() => setMessages([])} disabled={messages.length === 0}>{t.ai_chat.clear}</Button>
        </Space>
      </div>
      <Card bodyStyle={{ height: "calc(100vh - 260px)", display: "flex", flexDirection: "column", padding: 0 }}>
        <div ref={listRef} style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {messages.length === 0 && <Empty description="Start a conversation" style={{ marginTop: 100 }} />}
          {messages.map((msg, i) => (
            <div key={i} style={{ marginBottom: 16, display: "flex", flexDirection: msg.role === "user" ? "row-reverse" : "row", alignItems: "flex-start", gap: 8 }}>
              <div style={{ width: 32, height: 32, borderRadius: "50%", background: msg.role === "user" ? "#1890ff" : msg.role === "system" ? "#ff4d4f" : "#52c41a", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                {msg.role === "user" ? <UserOutlined style={{ color: "#fff", fontSize: 14 }} /> : <RobotOutlined style={{ color: "#fff", fontSize: 14 }} />}
              </div>
              <div style={{ maxWidth: "75%" }}>
                <div style={{
                  padding: "10px 14px", borderRadius: 12,
                  background: msg.role === "user" ? "#1890ff" : msg.role === "system" ? "#fff1f0" : "#f5f5f5",
                  color: msg.role === "user" ? "#fff" : "#000",
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                }}>
                  {msg.content}
                </div>
                <Text type="secondary" style={{ fontSize: 11, marginTop: 2, display: "block", textAlign: msg.role === "user" ? "right" : "left" }}>{msg.time}</Text>
              </div>
            </div>
          ))}
          {loading && <div style={{ textAlign: "center", padding: 12 }}><Spin /><Text style={{ marginLeft: 8 }} type="secondary">Thinking...</Text></div>}
        </div>
        <Divider style={{ margin: 0 }} />
        <div style={{ padding: "12px 16px" }}>
          <Space.Compact style={{ width: "100%" }}>
            <Input.TextArea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything about welding manufacturing..."
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={loading}
            />
            <Button type="primary" icon={<SendOutlined />} onClick={send} loading={loading} style={{ height: "auto" }}>{t.ai_chat.send}</Button>
          </Space.Compact>
        </div>
      </Card>
    </AppLayout>
  );
}
