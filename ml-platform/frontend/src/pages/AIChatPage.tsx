import { useState, useRef, useEffect } from "react";
import { Card, Input, Button, Typography, Space, Spin, Tag, Empty, Divider, Modal, Slider, Select, Collapse, message as antdMessage } from "antd";
import { SendOutlined, RobotOutlined, UserOutlined, ClearOutlined, SettingOutlined, ShareAltOutlined, FileTextOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

const { Text, Title } = Typography;

interface ChatSource { index: number; chunk_id: string; doc_id: string; filename: string; score: number; }
interface ChatMsg { role: "user" | "assistant" | "system"; content: string; time: string; sources?: ChatSource[]; }

export default function AIChatPage() {
  const { t, lang } = useI18n();
  const text = lang === "zh" ? {
    settings: "对话配置", apiKey: "API Key", apiKeyHint: "仅本次浏览器会话使用，不会保存到服务器",
    model: "模型", systemPrompt: "系统提示词", temperature: "生成随机度",
    configured: "已配置", start: "开始对话", thinking: "正在思考...",
    placeholder: "输入有关焊接制造的问题...", save: "保存配置",
    knowledgeBase: "知识库（RAG）", knowledgeBaseHint: "绑定后回答基于知识库检索内容并标注引用来源",
    noKnowledgeBase: "不使用知识库", citations: "引用来源", noCitations: "本次回答未引用知识库内容",
    publishAsApi: "发布为 API", publishSuccessPrefix: "已发布为对话 API，",
    publishSuccessLink: "去 API 市场查看", publishFailed: "发布为 API 失败", kbBound: "知识库",
    emptySources: "知识库中没有检索到相关内容，已按通用助手回答",
  } : {
    settings: "Chat Settings", apiKey: "API Key", apiKeyHint: "Used only for this browser session and never saved on the server",
    model: "Model", systemPrompt: "System prompt", temperature: "Temperature",
    configured: "Configured", start: "Start a conversation", thinking: "Thinking...",
    placeholder: "Ask about welding manufacturing...", save: "Save settings",
    knowledgeBase: "Knowledge base (RAG)", knowledgeBaseHint: "Answers are grounded in retrieved chunks with numbered citations",
    noKnowledgeBase: "No knowledge base", citations: "Citations", noCitations: "This answer used no knowledge base content",
    publishAsApi: "Publish as API", publishSuccessPrefix: "Published as a chat API - ",
    publishSuccessLink: "open the API marketplace", publishFailed: "Publish failed", kbBound: "KB",
    emptySources: "Nothing relevant was retrieved from the knowledge base; answered as a general assistant",
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
  const [kbId, setKbId] = useState(() => localStorage.getItem("chat.kbId") || "");
  const [kbs, setKbs] = useState<any[]>([]);
  const [publishing, setPublishing] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    apiClient.get("/chat/status").then(r => setStatus(r.data)).catch(() => {});
    apiClient.get("/knowledge/bases").then(r => setKbs(Array.isArray(r.data) ? r.data : [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages]);

  const fetchKbs = () => {
    apiClient.get("/knowledge/bases").then(r => setKbs(Array.isArray(r.data) ? r.data : [])).catch(() => setKbs([]));
  };

  const send = async () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    const userMsg: ChatMsg = { role: "user", content: trimmed, time: new Date().toLocaleTimeString() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    try {
      const res = await apiClient.post("/chat", {
        message: trimmed,
        system_prompt: systemPrompt,
        temperature,
        api_key: apiKey || undefined,
        model: model || undefined,
        kb_id: kbId || undefined,
      });
      const reply = res.data.reply || "No response.";
      const assistantMsg: ChatMsg = {
        role: "assistant", content: reply, time: new Date().toLocaleTimeString(),
        sources: kbId ? (res.data.sources || []) : undefined,
      };
      if (kbId && res.data.kb_warning && (res.data.sources || []).length === 0) {
        setMessages(prev => [...prev, assistantMsg, { role: "system", content: text.emptySources, time: new Date().toLocaleTimeString() }]);
      } else {
        setMessages(prev => [...prev, assistantMsg]);
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      const detailText = typeof detail === "object" ? (detail?.message || detail?.code) : detail;
      setMessages(prev => [...prev, { role: "system", content: "Error: " + (detailText || e.message), time: new Date().toLocaleTimeString() }]);
    } finally {
      setLoading(false);
    }
  };

  const publishApi = async () => {
    if (!kbId || publishing) return;
    setPublishing(true);
    try {
      await apiClient.post("/platform/apis/publish/chat/" + kbId);
      antdMessage.success(
        <span>
          {`${text.publishSuccessPrefix} `}
          {/* antd message renders outside the Router portal, so a plain
              anchor is used for the marketplace jump. */}
          <a href="/api-marketplace">{text.publishSuccessLink}</a>
        </span>,
      );
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      const detailText = typeof detail === "object" ? (detail?.message || detail?.code) : detail;
      antdMessage.error(text.publishFailed + ": " + (detailText || e.message));
    } finally {
      setPublishing(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const boundKb = kbs.find(kb => kb.id === kbId);

  return (
    <AppLayout>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}><RobotOutlined /> {t.ai_chat.title}</Title>
        <Space>
          {apiKey || status?.configured ? <Tag color="green">{text.configured}: {model || status?.model}</Tag> : <Tag color="red">{t.ai_chat.not_configured}</Tag>}
          {boundKb && <Tag color="purple">{`${text.kbBound}: ${boundKb.name}`}</Tag>}
          <Button icon={<ShareAltOutlined />} onClick={publishApi} disabled={!kbId} loading={publishing}>{text.publishAsApi}</Button>
          <Button icon={<SettingOutlined />} onClick={() => { fetchKbs(); setSettingsOpen(true); }}>{text.settings}</Button>
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
                {msg.role === "assistant" && msg.sources && (
                  msg.sources.length > 0 ? (
                    <Collapse size="small" style={{ marginTop: 6, background: "#fafafa" }}
                      items={[{
                        key: "sources",
                        label: <Space size={4}><FileTextOutlined /> {`${text.citations} (${msg.sources.length})`}</Space>,
                        children: (
                          <ul style={{ margin: 0, paddingLeft: 16 }}>
                            {msg.sources.map(src => (
                              <li key={src.index} style={{ marginBottom: 4 }}>
                                <Text style={{ fontSize: 12 }}>[{src.index}] {src.filename || src.doc_id}</Text>
                                <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>score {src.score}</Text>
                              </li>
                            ))}
                          </ul>
                        ),
                      }]} />
                  ) : (
                    <Text type="secondary" style={{ fontSize: 11, marginTop: 4, display: "block" }}>{text.noCitations}</Text>
                  )
                )}
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
              autoComplete="off" value={input}
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
        localStorage.setItem("chat.kbId", kbId);
        sessionStorage.setItem("chat.apiKey", apiKey);
        sessionStorage.setItem("chat.model", model);
        setSettingsOpen(false);
      }}>
        <Text strong>{text.knowledgeBase}</Text>
        <Select
          value={kbId || undefined}
          allowClear
          placeholder={text.noKnowledgeBase}
          onChange={(value) => setKbId(value || "")}
          style={{ width: "100%", marginTop: 8, marginBottom: 4 }}
          options={kbs.map(kb => ({ value: kb.id, label: kb.name }))}
        />
        <Text type="secondary" style={{ display: "block", fontSize: 12, marginBottom: 16 }}>{text.knowledgeBaseHint}</Text>
        <Text strong>{text.apiKey}</Text>
        <Input.Password value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="off"
          placeholder="sk-..." style={{ marginTop: 8, marginBottom: 4 }} />
        <Text type="secondary" style={{ display: "block", fontSize: 12, marginBottom: 16 }}>{text.apiKeyHint}</Text>
        <Text strong>{text.model}</Text>
              <Input autoComplete="off" value={model} onChange={(event) => setModel(event.target.value)} placeholder={status?.model || "gpt-4o-mini"}
          style={{ marginTop: 8, marginBottom: 16 }} />
        <Text strong>{text.systemPrompt}</Text>
              <Input.TextArea autoComplete="off" value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} rows={5} style={{ marginTop: 8, marginBottom: 16 }} />
        <Text strong>{text.temperature}: {temperature.toFixed(1)}</Text>
        <Slider min={0} max={1} step={0.1} value={temperature} onChange={setTemperature} />
      </Modal>
    </AppLayout>
  );
}
