import { useState, useRef, useEffect } from "react";
import { Card, Input, Button, Typography, Space, Spin, Tag, Empty, Divider, Modal, Slider, Select, Collapse, Popover, message as antdMessage } from "antd";
import { SendOutlined, RobotOutlined, UserOutlined, ClearOutlined, SettingOutlined, ShareAltOutlined, FileTextOutlined, BlockOutlined, DownOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import ChatToolsPanel from "../components/ChatToolsPanel";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

const { Text, Title } = Typography;

interface ChatSource { index: number; chunk_id: string; doc_id: string; filename: string; score: number; }
interface ChatMsg { role: "user" | "assistant" | "system"; content: string; time: string; sources?: ChatSource[]; }

export default function AIChatPage() {
  const { t, lang } = useI18n();
  const text = lang === "zh" ? {
    settings: "对话设置",
    systemPrompt: "系统提示词",
    start: "开始对话", thinking: "正在思考...",
    placeholder: "输入消息，Enter 发送…", save: "保存配置",
    knowledgeBase: "知识库（RAG）", knowledgeBaseHint: "绑定后回答基于知识库检索内容并标注引用来源",
    noKnowledgeBase: "不使用知识库", citations: "引用来源", noCitations: "本次回答未引用知识库内容",
    publishAsApi: "发布为 API", publishSuccessPrefix: "已发布为对话 API，",
    publishSuccessLink: "去 API 市场查看", publishFailed: "发布为 API 失败", kbBound: "知识库",
    emptySources: "知识库中没有检索到相关内容，已按通用助手回答",
    contextManager: "上下文", clearContext: "清空上下文（开始新对话）",
    thinkingLevel: "思考强度", modelSelect: "模型",
  } : {
    settings: "Chat Settings",
    systemPrompt: "System prompt",
    start: "Start a conversation", thinking: "Thinking...",
    placeholder: "Type a message, Enter to send…", save: "Save settings",
    knowledgeBase: "Knowledge base (RAG)", knowledgeBaseHint: "Answers are grounded in retrieved chunks with numbered citations",
    noKnowledgeBase: "No knowledge base", citations: "Citations", noCitations: "This answer used no knowledge base content",
    publishAsApi: "Publish as API", publishSuccessPrefix: "Published as a chat API - ",
    publishSuccessLink: "open the API marketplace", publishFailed: "Publish failed", kbBound: "KB",
    emptySources: "Nothing relevant was retrieved from the knowledge base; answered as a general assistant",
    contextManager: "Context", clearContext: "Clear context (new conversation)",
    thinkingLevel: "Thinking", modelSelect: "Model",
  };
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState(() => localStorage.getItem("chat.systemPrompt") || "你是汽车焊接制造领域的智能助手。");
  const [temperature] = useState(() => Number(localStorage.getItem("chat.temperature") || "0.7"));
  const [kbId, setKbId] = useState(() => localStorage.getItem("chat.kbId") || "");
  const [kbs, setKbs] = useState<any[]>([]);
  const [publishing, setPublishing] = useState(false);
  // ZCode 式工具条状态：模型选择 / 思考强度 / 上下文携带条数
  const [profiles, setProfiles] = useState<any[]>([]);
  const [profileId, setProfileId] = useState(() => localStorage.getItem("chat.profileId") || "");
  const [thinkingLevel, setThinkingLevel] = useState<string>(() => localStorage.getItem("chat.thinkingLevel") || "off");
  const [contextWindow, setContextWindow] = useState<number>(() => Number(localStorage.getItem("chat.contextWindow") || "8"));
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    apiClient.get("/knowledge/bases").then(r => setKbs(Array.isArray(r.data) ? r.data : [])).catch(() => {});
    apiClient.get("/llm-profiles").then(r => setProfiles(Array.isArray(r.data) ? r.data : [])).catch(() => {});
  }, []);

  useEffect(() => {
    localStorage.setItem("chat.profileId", profileId);
    localStorage.setItem("chat.thinkingLevel", thinkingLevel);
    localStorage.setItem("chat.contextWindow", String(contextWindow));
  }, [profileId, thinkingLevel, contextWindow]);

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
    // 多轮上下文：携带最近 contextWindow 条对话（user/assistant）
    const history = messages
      .filter(m => m.role === "user" || m.role === "assistant")
      .slice(-contextWindow)
      .map(m => ({ role: m.role, content: m.content }));
    try {
      const res = await apiClient.post("/chat", {
        message: trimmed,
        system_prompt: systemPrompt,
        temperature,
        history,
        thinking_level: thinkingLevel,
        profile_id: profileId || undefined,
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
          {boundKb && <Tag color="purple">{`${text.kbBound}: ${boundKb.name}`}</Tag>}
          <Button icon={<ShareAltOutlined />} onClick={publishApi} disabled={!kbId} loading={publishing}>{text.publishAsApi}</Button>
          <Button icon={<SettingOutlined />} onClick={() => { fetchKbs(); setSettingsOpen(true); }}>{text.settings}</Button>
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
          <ChatToolsPanel onResult={(resultText) => {
            setMessages(prev => [...prev, { role: "assistant", content: resultText, time: new Date().toLocaleTimeString() }]);
          }} />
          {/* ZCode 式输入框：模型/思考强度/上下文容量内嵌在输入框内 */}
          {(() => {
            const carried = messages.filter(m => m.role === "user" || m.role === "assistant").slice(-contextWindow);
            const usedTokens = Math.ceil(carried.reduce((sum, m) => sum + m.content.length, 0) / 4);
            const CONTEXT_BUDGET = 32000;
            const pct = Math.min(100, Math.round((usedTokens / CONTEXT_BUDGET) * 100));
            const fmtK = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n));
            return (
              <div style={{
                border: "1px solid var(--v2-line, #d9d9d9)", borderRadius: 12,
                background: "var(--v2-panel2, rgba(22,34,58,.35))",
                padding: "8px 10px 6px", transition: "border-color .15s",
              }}>
                <Input.TextArea
                  autoComplete="off" value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={text.placeholder}
                  autoSize={{ minRows: 1, maxRows: 6 }}
                  disabled={loading}
                  variant="borderless"
                  style={{ padding: "2px 4px", fontSize: 13.5 }}
                />
                {/* 底部工具行（输入框内）：左=模型+思考强度，右=上下文容量+发送 */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
                  <Select
                    size="small" variant="borderless"
                    value={profileId || undefined}
                    onChange={(v) => setProfileId(v || "")}
                    placeholder={lang === "zh" ? "默认模型" : "Default model"}
                    style={{ minWidth: 60, maxWidth: 210, flex: "0 1 auto", fontSize: 12 }}
                    suffixIcon={<DownOutlined style={{ fontSize: 10 }} />}
                    allowClear
                    options={profiles.map(p => ({ value: p.id, label: p.model_id }))}
                  />
                  <Select
                    size="small" variant="borderless"
                    value={thinkingLevel}
                    onChange={setThinkingLevel}
                    style={{ width: 96, fontSize: 12 }}
                    suffixIcon={<DownOutlined style={{ fontSize: 10 }} />}
                    options={[
                      { value: "off", label: lang === "zh" ? "✦ 思考 关" : "✦ off" },
                      { value: "low", label: lang === "zh" ? "✦ 思考 低" : "✦ low" },
                      { value: "medium", label: lang === "zh" ? "✦ 思考 中" : "✦ med" },
                      { value: "high", label: lang === "zh" ? "✦ 思考 高" : "✦ high" },
                    ]}
                  />
                  {/* 上下文容量条（点击展开窗口设置）：占用/预算 + 清理 */}
                  <Popover
                    trigger="click"
                    title={text.contextManager}
                    content={(
                      <div style={{ width: 250 }}>
                        <div style={{ fontSize: 12, marginBottom: 8 }}>
                          {lang === "zh"
                            ? `对话 ${messages.filter(m => m.role !== "system").length} 条；发送携带最近 ${contextWindow} 条（≈${fmtK(usedTokens)} tokens）。`
                            : `${messages.length} msgs; last ${contextWindow} ride along (≈${fmtK(usedTokens)} tokens).`}
                        </div>
                        <div style={{ fontSize: 12, marginBottom: 4 }}>{lang === "zh" ? `携带窗口：${contextWindow} 条` : `Window: ${contextWindow}`}</div>
                        <Slider min={0} max={20} step={2} value={contextWindow} onChange={setContextWindow} />
                        <Button size="small" block icon={<ClearOutlined />} onClick={() => setMessages([])} disabled={messages.length === 0} style={{ marginTop: 8 }}>
                          {text.clearContext}
                        </Button>
                      </div>
                    )}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", minWidth: 130 }} title={text.contextManager}>
                      <BlockOutlined style={{ fontSize: 11, color: "var(--v2-dim)" }} />
                      <div style={{ width: 64, height: 4, borderRadius: 2, background: "rgba(128,140,160,.3)", overflow: "hidden" }}>
                        <div style={{ width: `${pct}%`, height: "100%", background: pct > 80 ? "#e66f75" : "var(--v2-blue)" }} />
                      </div>
                      <span style={{ fontSize: 11, color: "var(--v2-dim)", fontVariantNumeric: "tabular-nums" }}>{fmtK(usedTokens)} / {fmtK(CONTEXT_BUDGET)}</span>
                    </div>
                  </Popover>
                  <div style={{ marginLeft: "auto" }}>
                    <Button type="primary" size="small" icon={<SendOutlined />} onClick={send} loading={loading}>
                      {t.ai_chat.send}
                    </Button>
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      </Card>
      <Modal title={text.settings} open={settingsOpen} onCancel={() => setSettingsOpen(false)} okText={text.save} onOk={() => {
        localStorage.setItem("chat.systemPrompt", systemPrompt);
        localStorage.setItem("chat.kbId", kbId);
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
        <Text strong>{text.systemPrompt}</Text>
        <Input.TextArea autoComplete="off" value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} rows={5} style={{ marginTop: 8 }} />
      </Modal>
    </AppLayout>
  );
}
