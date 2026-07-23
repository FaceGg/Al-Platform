import { useState, useRef, useEffect } from "react";
import { Card, Input, Button, Typography, Space, Spin, Tag, Empty, Divider, Modal, Slider } from "antd";
import { SendOutlined, RobotOutlined, UserOutlined, ClearOutlined, SettingOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

const { Text, Title } = Typography;

interface ChatMsg { role: "user" | "assistant" | "system"; content: string; time: string; }

export default function AIChatPage() {
  const { t, lang } = useI18n();
  const text = lang === "zh" ? {
    settings: "对话配置", apiKey: "API Key", apiKeyHint: "仅本次浏览器会话使用，不会保存到服务器",
    model: "模型", systemPrompt: "系统提示词", temperature: "生成随机度",
    configured: "已配置", start: "开始对话", thinking: "正在思考...",
    placeholder: "输入有关焊接制造的问题...", save: "保存配置",
  } : {
    settings: "Chat Settings", apiKey: "API Key", apiKeyHint: "Used only for this browser session and never saved on the server",
    model: "Model", systemPrompt: "System prompt", temperature: "Temperature",
    configured: "Configured", start: "Start a conversation", thinking: "Thinking...",
    placeholder: "Ask about welding manufacturing...", save: "Save settings",
  };
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<any>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState(() => localStorage.getItem("chat.systemPrompt") || "你是汽车焊接制造领域的智能助手。");
  const [temperature, setTemperature] = useState(() => Number(localStorage.getItem("chat.temperature") || "0.7"));
  const [apiKey, setApiKey] = useState(() => sessionStorage.getItem("chat.apiKey") || "");
  const [model, setModel] = useState(() => sessionStorage.getItem("chat.model") || "");
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
      const res = await apiClient.post("/chat", {
        message: text,
        system_prompt: systemPrompt,
        temperature,
        api_key: apiKey || undefined,
        model: model || undefined,
      });
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
        <Title level={4} style={{ margin: 0 }}><RobotOutlined /> {t.ai_chat.title}</Title>
        <Space>
          {apiKey || status?.configured ? <Tag color="green">{text.configured}: {model || status?.model}</Tag> : <Tag color="red">{t.ai_chat.not_configured}</Tag>}
          <Button icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>{text.settings}</Button>
          <Button icon={<ClearOutlined />} onClick={() => setMessages([])} disabled={messages.length === 0}>{t.ai_chat.clear}</Button>
        </Space>
      </div>
      <Card styles={{ body: { height: "calc(100vh - 260px)", display: "flex", flexDirection: "column", padding: 0 } }}>
        <div ref={listRef} style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {messages.length === 0 && <Empty description={text.start} style={{ marginTop: 100 }} />}
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
          {loading && <div style={{ textAlign: "center", padding: 12 }}><Spin /><Text style={{ marginLeft: 8 }} type="secondary">{text.thinking}</Text></div>}
        </div>
        <Divider style={{ margin: 0 }} />
        <div style={{ padding: "12px 16px" }}>
          <Space.Compact style={{ width: "100%" }}>
            <Input.TextArea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={text.placeholder}
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={loading}
            />
            <Button type="primary" icon={<SendOutlined />} onClick={send} loading={loading} style={{ height: "auto" }}>{t.ai_chat.send}</Button>
          </Space.Compact>
        </div>
      </Card>
      <Modal title={text.settings} open={settingsOpen} onCancel={() => setSettingsOpen(false)} okText={text.save} onOk={() => {
        localStorage.setItem("chat.systemPrompt", systemPrompt);
        localStorage.setItem("chat.temperature", String(temperature));
        sessionStorage.setItem("chat.apiKey", apiKey);
        sessionStorage.setItem("chat.model", model);
        setSettingsOpen(false);
      }}>
        <Text strong>{text.apiKey}</Text>
        <Input.Password value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="off"
          placeholder="sk-..." style={{ marginTop: 8, marginBottom: 4 }} />
        <Text type="secondary" style={{ display: "block", fontSize: 12, marginBottom: 16 }}>{text.apiKeyHint}</Text>
        <Text strong>{text.model}</Text>
        <Input value={model} onChange={(event) => setModel(event.target.value)} placeholder={status?.model || "gpt-4o-mini"}
          style={{ marginTop: 8, marginBottom: 16 }} />
        <Text strong>{text.systemPrompt}</Text>
        <Input.TextArea value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} rows={5} style={{ marginTop: 8, marginBottom: 16 }} />
        <Text strong>{text.temperature}: {temperature.toFixed(1)}</Text>
        <Slider min={0} max={1} step={0.1} value={temperature} onChange={setTemperature} />
      </Modal>
    </AppLayout>
  );
}
