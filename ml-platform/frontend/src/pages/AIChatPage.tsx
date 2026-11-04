import { useState, useRef, useEffect } from "react";
import { Card, Input, Button, Typography, Space, Spin, Tag, Empty, Divider, Modal, Slider, Select, Collapse, Popover, message as antdMessage } from "antd";
import { SendOutlined, RobotOutlined, UserOutlined, ClearOutlined, SettingOutlined, ShareAltOutlined, FileTextOutlined, BlockOutlined, DownOutlined, PlusOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import ChatToolsPanel from "../components/ChatToolsPanel";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

const { Text, Title } = Typography;

interface ChatSource { index: number; chunk_id: string; doc_id: string; filename: string; score: number; }
interface ChatMsg { role: "user" | "assistant" | "system"; content: string; time: string; sources?: ChatSource[]; }

export default function AIChatPage() {
  const { t, lang } = useI18n();
  const zh = lang === "zh";
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
          {/* ZCode 式输入框（对齐参考布局）：+ | 权限选择 …… 模型+思考强度 | 圆形发送；上下文容量条内嵌 */}
          {(() => {
            const carried = messages.filter(m => m.role === "user" || m.role === "assistant").slice(-contextWindow);
            const usedTokens = Math.ceil(carried.reduce((sum, m) => sum + m.content.length, 0) / 4);
            const CONTEXT_BUDGET = 32000;
            const pct = Math.min(100, Math.round((usedTokens / CONTEXT_BUDGET) * 100));
            const fmtK = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n));
            const activeModel = profiles.find(p => p.id === profileId);
            return (
              <div style={{
                border: "1px solid var(--v2-line, #d9d9d9)", borderRadius: 16,
                background: "var(--v2-panel2, rgba(22,34,58,.35))",
                padding: "10px 12px 8px", transition: "border-color .15s",
              }}>
                <Input.TextArea
                  autoComplete="off" value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={text.placeholder}
                  autoSize={{ minRows: 2, maxRows: 8 }}
                  disabled={loading}
                  variant="borderless"
                  style={{ padding: "2px 4px", fontSize: 13.5 }}
                />
                {/* 底部工具行：左=输入提示 …… 右=容量圆圈 | 模型 | 思考强度 | 发送/停止 */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                  {/* 上下文容量：点击展开窗口设置 */}
                  <Popover
                    trigger={["click", "hover"]}
                    title={text.contextManager}
                    content={(() => {
                      const sysTokens = Math.ceil(systemPrompt.length / 4);
                      const userTokens = Math.ceil(input.length / 4);
                      const otherTokens = Math.max(0, usedTokens - carried.reduce((s, m) => s + Math.ceil(m.content.length / 4), 0));
                      const rows: Array<[string, number]> = [
                        [zh ? "消息" : "Messages", usedTokens - sysTokens - userTokens - otherTokens],
                        [zh ? "系统提示词" : "System prompt", sysTokens],
                        [zh ? "正在输入" : "Composing", userTokens],
                        [zh ? "其他" : "Other", otherTokens],
                      ];
                      // 占比分母：分项求和（usedTokens 为 0 时避免除零与 >100%）
                      const total = Math.max(1, rows.reduce((s, [, v]) => s + Math.max(0, v), 0));
                      return (
                        <div style={{ width: 280 }}>
                          {/* 标题行：上下文容量 …… 78.9万/100万（78.9%） */}
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                            <b style={{ fontSize: 13.5, color: "var(--v2-txt)" }}>{text.contextManager}</b>
                            <span style={{ fontSize: 12, color: "var(--v2-sub)", fontVariantNumeric: "tabular-nums" }}>
                              {fmtK(usedTokens)}/32K（{pct}%）
                            </span>
                          </div>
                          {/* 粗进度条 */}
                          <div style={{ height: 8, borderRadius: 4, background: "rgba(128,140,160,.25)", overflow: "hidden", marginBottom: 12 }}>
                            <div style={{ width: `${pct}%`, height: "100%", background: pct > 80 ? "#e66f75" : "#2f9bf5", borderRadius: 4 }} />
                          </div>
                          {/* 分项明细（彩色圆点 + 名称 + 占比） */}
                          {rows.filter(([, v]) => v > 0).map(([name, value], idx) => {
                            const share = Math.round((value / total) * 1000) / 10;
                            return (
                              <div key={name} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: 12.5 }}>
                                <span style={{ width: 7, height: 7, borderRadius: "50%", background: ["#2f9bf5", "#1d6fd0", "#7fd0ff", "#9b7bff"][idx % 4] }} />
                                <span style={{ flex: 1, color: "var(--v2-txt)" }}>{name}</span>
                                <span style={{ color: "var(--v2-sub)", fontVariantNumeric: "tabular-nums" }}>{share.toFixed(1)}%</span>
                              </div>
                            );
                          })}
                          <div style={{ borderTop: "1px solid var(--v2-line, rgba(36,52,79,.6)", marginTop: 8, paddingTop: 8 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, color: "var(--v2-sub)" }}>
                              <span>{zh ? "上下文预算" : "Context budget"}</span>
                              <span>32K</span>
                            </div>
                          </div>
                          <div style={{ borderTop: "1px solid var(--v2-line, rgba(36,52,79,.6)", marginTop: 8, paddingTop: 10 }}>
                            <div style={{ fontSize: 12, marginBottom: 4 }}>{lang === "zh" ? `携带窗口：${contextWindow} 条` : `Window: ${contextWindow}`}</div>
                            <Slider min={0} max={20} step={2} value={contextWindow} onChange={setContextWindow} />
                            <Button size="small" block icon={<ClearOutlined />} onClick={() => setMessages([])} disabled={messages.length === 0} style={{ marginTop: 8 }}>
                              {text.clearContext}
                            </Button>
                          </div>
                        </div>
                      );
                    })()}
                  >
                    <div
                      title={`${text.contextManager}：≈${fmtK(usedTokens)} / 32K tokens`}
                      style={{
                        width: 26, height: 26, borderRadius: "50%", cursor: "pointer", flex: "0 0 auto",
                        background: `conic-gradient(var(--v2-blue) ${pct}%, rgba(128,140,160,.25) ${pct}% 100%)`,
                        display: "inline-flex", alignItems: "center", justifyContent: "center",
                      }}
                    >
                      <BlockOutlined style={{ fontSize: 10, color: "var(--v2-sub)" }} />
                    </div>
                  </Popover>
                  {/* 模型+思考强度合并面板（参考 ZCode 第二图）：供应商头+模型列表带勾+思考强度渐变滑条 */}
                  <Popover
                    trigger="click"
                    placement="topRight"
                    content={(() => {
                      const current = profiles.find(p => p.id === profileId) ?? profiles.find(p => p.is_default);
                      const levels = [
                        { value: "off", label: zh ? "关闭" : "Off" },
                        { value: "low", label: zh ? "低" : "Low" },
                        { value: "medium", label: zh ? "中" : "Med" },
                        { value: "high", label: zh ? "最高" : "Max" },
                      ];
                      const ti = Math.max(0, levels.findIndex(l => l.value === thinkingLevel));
                      return (
                        <div style={{ width: 260 }}>
                          {/* 供应商/档案头 */}
                          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 4px 10px" }}>
                            <span aria-hidden="true" style={{ background: "#3859FF", borderRadius: 7, width: 26, height: 26, display: "inline-flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 12 }}>
                              {(current?.name || "AI").slice(0, 1)}
                            </span>
                            <b style={{ fontSize: 13.5, color: "var(--v2-txt)" }}>{current?.name ?? (zh ? "默认档案" : "Default profile")}</b>
                            <span style={{ marginLeft: "auto", color: "var(--v2-dim)" }}>›</span>
                          </div>
                          <div style={{ fontSize: 12, color: "var(--v2-dim)", margin: "4px 0 2px" }}>{zh ? "模型" : "Model"}</div>
                          {/* 模型列表（一档案一模型），选中带勾 */}
                          {profiles.map((p) => {
                            const selected = p.id === (profileId || profiles.find(x => x.is_default)?.id);
                            return (
                              <div
                                key={p.id}
                                onClick={() => setProfileId(p.id)}
                                style={{
                                  display: "flex", alignItems: "center", gap: 8, padding: "8px 10px",
                                  borderRadius: 8, cursor: "pointer", fontSize: 13,
                                  background: selected ? "rgba(47,155,245,.10)" : "transparent",
                                }}
                              >
                                <span style={{ flex: 1 }}>{p.model_id}</span>
                                {p.is_default ? <Tag style={{ marginRight: 0 }}>{zh ? "默认" : "default"}</Tag> : null}
                                {selected ? <span style={{ color: "var(--v2-blue)" }}>✓</span> : null}
                              </div>
                            );
                          })}
                          <div style={{ borderTop: "1px solid var(--v2-line, rgba(36,52,79,.4))", marginTop: 8, paddingTop: 10 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                              <span style={{ fontSize: 12, color: "var(--v2-sub)" }}>{zh ? "思考强度" : "Thinking"}</span>
                              <b style={{ fontSize: 12.5, color: "var(--v2-txt)" }}>{levels[ti]?.label}</b>
                            </div>
                            <Slider
                              min={0} max={3} step={1} value={ti}
                              onChange={(v) => setThinkingLevel(levels[v]?.value ?? "off")}
                              tooltip={{ open: false }}
                              trackStyle={{ background: "linear-gradient(90deg, #1f9d55, #2f9bf5)", height: 10, borderRadius: 5 }}
                              handleStyle={{ width: 18, height: 18, background: "#fff", borderColor: "#fff", boxShadow: "0 1px 4px rgba(0,0,0,.25)" }}
                            />
                          </div>
                        </div>
                      );
                    })()}
                  >
                    <Button type="text" size="small" style={{ fontSize: 12.5, fontWeight: 600, color: "inherit" }}>
                      {(profiles.find(p => p.id === profileId) ?? profiles.find(p => p.is_default))?.model_id ?? (zh ? "默认模型" : "model")}
                      {" "}
                      {({ low: "低", medium: "中", high: "最高" } as Record<string, string>)[thinkingLevel] ?? ""}
                      <DownOutlined style={{ fontSize: 10, marginLeft: 4 }} />
                    </Button>
                  </Popover>
                  {loading ? (
                    <Button danger shape="circle" onClick={() => { /* 生成不可硬中断，边界生效 */ }} title={zh ? "生成中（阶段边界生效）" : "Generating"} style={{ width: 34, height: 34 }} />
                  ) : (
                    <Button
                      type="primary"
                      shape="circle"
                      icon={<SendOutlined style={{ fontSize: 14 }} />}
                      onClick={send}
                      style={{ width: 34, height: 34 }}
                      aria-label={t.ai_chat.send}
                    />
                  )}
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
