import { useState, useRef, useEffect } from "react";
import { Card, Input, Button, Typography, Space, Spin, Tag, Empty, Divider, Modal, Select, Collapse, Popover, Upload, Slider, message as antdMessage, Dropdown } from "antd";
import {
  SendOutlined, RobotOutlined, UserOutlined,
  FileTextOutlined, DownOutlined, PlusOutlined,
  EditOutlined, DeleteOutlined, PaperClipOutlined, DatabaseOutlined, ToolOutlined, FileImageOutlined,
} from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import PageHeading from "../components/PageHeading";
import ChatToolsModal from "../components/ChatToolsPanel";
import apiClient from "../api/client";
import { useI18n } from "../i18n";
import { effectiveModelConfig, fmtContextTokens, INPUT_TYPE_LABELS } from "../utils/llmModelConfig";

const { Text } = Typography;

interface ChatSource { index: number; chunk_id: string; doc_id: string; filename: string; score: number; }
interface ChatMsg { role: "user" | "assistant" | "system"; content: string; time: string; sources?: ChatSource[]; }
interface ChatSession { id: string; title: string; messages: ChatMsg[]; created_at?: string; updated_at?: string; }
/** 本轮附件：图片走多模态 content，文本以引述拼进问题（发送后清空） */
interface ChatAttachment { uid: string; name: string; kind: "image" | "text"; data: string; }

export default function AIChatPage() {
  const { t, lang } = useI18n();
  const zh = lang === "zh";
  const text = zh ? {
    systemPrompt: "系统提示词",
    start: "开始对话", thinking: "正在思考...",
    placeholder: "输入消息，Enter 发送…", save: "保存",
    knowledgeBase: "知识库", knowledgeBaseHint: "绑定后回答基于知识库检索内容并标注引用来源",
    noKnowledgeBase: "不使用知识库", citations: "引用来源", noCitations: "本次回答未引用知识库内容",
    emptySources: "知识库中没有检索到相关内容，已按通用助手回答",
    contextManager: "上下文容量",
    attach: "附件",
    attachHint: "图片（png/jpg/gif/webp，≤5MB）随消息作为多模态输入；文本类（txt/md/csv/json/log/代码，≤512KB）内容以引述注入提问。发送时一并交给大模型，最多 6 个。",
    attachFull: "附件最多 6 个",
    attachImageTooLarge: "图片超过 5MB 上限",
    attachTextTooLarge: "文本文件超过 512KB 上限",
    attachNotText: "不是可读文本文件",
    kbBound: "知识库",
  } : {
    systemPrompt: "System prompt",
    start: "Start a conversation", thinking: "Thinking...",
    placeholder: "Type a message, Enter to send…", save: "Save",
    knowledgeBase: "Knowledge base", knowledgeBaseHint: "Answers grounded in retrieved chunks",
    noKnowledgeBase: "No knowledge base", citations: "Citations", noCitations: "No KB content used",
    emptySources: "Nothing relevant retrieved; answered as a general assistant",
    contextManager: "Context",
    attach: "Attachments",
    attachHint: "Images (png/jpg/gif/webp, ≤5MB) go to the LLM as multimodal input; text files (txt/md/csv/json/log/code, ≤512KB) are quoted into the question. Sent with the message, max 6.",
    attachFull: "Max 6 attachments",
    attachImageTooLarge: "Image exceeds the 5MB limit",
    attachTextTooLarge: "Text file exceeds the 512KB limit",
    attachNotText: "Not a readable text file",
    kbBound: "KB",
  };
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // 「+」菜单弹窗：附件 / 知识库 / 系统提示词 / 白名单工具管理（各自独立弹窗）
  const [modal, setModal] = useState<"attach" | "kb" | "prompt" | "tools" | null>(null);
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  // 白名单工具编排往返：助手追问/确认期间保存 tool_call，下轮作为
  // tool_context 带回（后端合并参数或确认执行）；取消按钮清空即放弃
  const [pendingToolCall, setPendingToolCall] = useState<{ tool: string; params?: Record<string, unknown>; status: string } | null>(null);
  const [systemPrompt, setSystemPrompt] = useState(() => localStorage.getItem("chat.systemPrompt") || "你是汽车焊接制造领域的智能助手。");
  const [temperature] = useState(() => Number(localStorage.getItem("chat.temperature") || "0.7"));
  const [kbId, setKbId] = useState(() => localStorage.getItem("chat.kbId") || "");
  const [kbs, setKbs] = useState<any[]>([]);
  // 多会话
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // ZCode 式工具条状态
  const [profiles, setProfiles] = useState<any[]>([]);
  const [profileId, setProfileId] = useState(() => localStorage.getItem("chat.profileId") || "");
  const [thinkingLevel, setThinkingLevel] = useState<string>(() => localStorage.getItem("chat.thinkingLevel") || "off");
  // 供应商飞出面板：悬停/点击供应商头时显示（默认不展开）
  const [providerFlyout, setProviderFlyout] = useState(false);
  const [contextWindow, setContextWindow] = useState<number>(() => Number(localStorage.getItem("chat.contextWindow") || "8"));
  // 所选模型的 ZCode 风格配置（上下文窗口/推理等级/输入类型，来自「编辑模型配置」弹窗；
  // effectiveModelConfig 对未配置模型回退推荐默认值——与模型选择弹层口径一致）
  const currentProfile = profiles.find((p) => p.id === profileId) ?? profiles.find((p) => p.is_default) ?? null;
  const modelCfg = effectiveModelConfig(currentProfile ?? undefined);
  const modelReasoningLevels = modelCfg.reasoning_levels.length ? modelCfg.reasoning_levels : null;
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    apiClient.get("/knowledge/bases").then(r => setKbs(Array.isArray(r.data) ? r.data : [])).catch(() => {});
    apiClient.get("/llm-profiles").then(r => setProfiles(Array.isArray(r.data) ? r.data : [])).catch(() => {});
    apiClient.get("/chat-sessions").then(r => {
      const items = Array.isArray(r.data) ? r.data : [];
      setSessions(items);
      if (items.length > 0) {
        setActiveSessionId(items[0].id);
        setMessages(items[0].messages || []);
      }
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  // 消息变化时同步到当前会话（防抖交由调用时机：发送完成/清空/切换时手动保存）
  const saveActive = (msgs: ChatMsg[]) => {
    if (!activeSessionId) return;
    apiClient.put(`/chat-sessions/${activeSessionId}`, { messages: msgs }).catch(() => {});
  };

  const newChat = async () => {
    try {
      const res = await apiClient.post("/chat-sessions", { title: zh ? "新对话" : "New chat" });
      const session: ChatSession = res.data;
      setSessions(prev => [{ ...session }, ...prev]);
      setActiveSessionId(session.id);
      setMessages([]);
      antdMessage.success(zh ? "已新建对话" : "New chat created");
    } catch (e: any) {
      antdMessage.error(e.response?.data?.detail?.message || (zh ? "创建失败" : "Failed"));
    }
  };

  const switchSession = (id: string) => {
    const target = sessions.find(s => s.id === id);
    if (!target) return;
    setActiveSessionId(id);
    setMessages(target.messages || []);
  };

  const renameSession = async (id: string, current: string) => {
    // 用输入对话框简洁重命名
    const input = document.createElement("input");
    input.value = current;
    input.style.position = "fixed";
    input.style.top = "-100px";
    document.body.appendChild(input);
    // 借助 antd Modal 不可行（需要受控），用 window.prompt 简洁实现
    input.remove();
    const next = window.prompt(zh ? "重命名会话" : "Rename session", current);
    if (!next || next === current) return;
    await apiClient.put(`/chat-sessions/${id}`, { title: next }).catch(() => {});
    setSessions(prev => prev.map(s => (s.id === id ? { ...s, title: next } : s)));
  };

  const copySessionId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id);
      antdMessage.success(zh ? "已复制 ID" : "ID copied");
    } catch {
      antdMessage.error(zh ? "复制失败" : "Copy failed");
    }
  };

  const deleteSession = async (id: string) => {
    await apiClient.delete(`/chat-sessions/${id}`).catch(() => {});
    setSessions(prev => prev.filter(s => s.id !== id));
    if (activeSessionId === id) {
      setActiveSessionId(null);
      setMessages([]);
    }
  };

  // 附件解析：图片转 data URL（多模态输入），文本读内容（引述注入提问）
  const addAttachment = (file: File) => {
    if (attachments.length >= 6) { antdMessage.error(text.attachFull); return; }
    const uid = `${file.name}-${file.size}-${Date.now()}`;
    if (/^image\/(png|jpe?g|gif|webp|bmp)$/i.test(file.type)) {
      if (file.size > 5 * 1024 * 1024) { antdMessage.error(`${file.name}：${text.attachImageTooLarge}`); return; }
      const reader = new FileReader();
      reader.onload = () => {
        setAttachments(prev => [...prev, { uid, name: file.name, kind: "image", data: String(reader.result || "") }]);
      };
      reader.readAsDataURL(file);
      return;
    }
    if (file.size > 512 * 1024) { antdMessage.error(`${file.name}：${text.attachTextTooLarge}`); return; }
    const reader = new FileReader();
    reader.onload = () => {
      const content = String(reader.result ?? "");
      if (content.includes("\u0000")) { antdMessage.error(`${file.name}：${text.attachNotText}`); return; }
      setAttachments(prev => [...prev, { uid, name: file.name, kind: "text", data: content.slice(0, 80000) }]);
    };
    reader.readAsText(file);
  };

  const send = async () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    // 展示层带附件标记（历史/上下文也由此字符串承载）
    const display = attachments.length
      ? `${trimmed}\n〔附件：${attachments.map(a => a.name).join("、")}〕`
      : trimmed;
    const userMsg: ChatMsg = { role: "user", content: display, time: new Date().toLocaleTimeString() };
    const history = [
      // 压缩摘要注入历史头部（LLM 由此知晓更早的对话内容）
      ...(compressedSummary ? [{ role: "assistant", content: "【此前对话摘要】" + compressedSummary }] : []),
      ...messages
        .filter(m => m.role === "user" || m.role === "assistant")
        .slice(-contextWindow)
        .map(m => ({ role: m.role, content: m.content })),
    ];
    const next = [...messages, userMsg];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const res = await apiClient.post("/chat", {
        message: trimmed,
        system_prompt: systemPrompt,
        temperature,
        history,
        thinking_level: thinkingLevel,
        profile_id: profileId || undefined,
        kb_id: kbId || undefined,
        attachments: attachments.map(({ name, kind, data }) => ({ name, kind, data })),
        tool_context: pendingToolCall ?? undefined,
      });
      const reply = res.data.reply || "No response.";
      const assistantMsg: ChatMsg = {
        role: "assistant", content: reply, time: new Date().toLocaleTimeString(),
        sources: kbId ? (res.data.sources || []) : undefined,
      };
      const final = [...next, assistantMsg];
      if (kbId && res.data.kb_warning && (res.data.sources || []).length === 0) {
        setMessages([...final, { role: "system", content: text.emptySources, time: new Date().toLocaleTimeString() }]);
      } else {
        setMessages(final);
      }
      saveActive(final);
      setAttachments([]); // 发送完成 → 本轮附件随消息已交付
      // 工具编排往返：追问/确认中 → 保存状态供下轮带回；终态 → 清空
      const toolCall = res.data.tool_call;
      if (toolCall && (toolCall.status === "clarify" || toolCall.status === "confirm")) {
        setPendingToolCall({ tool: toolCall.tool, params: toolCall.params, status: toolCall.status });
      } else {
        setPendingToolCall(null);
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      const detailText = typeof detail === "object" ? (detail?.message || detail?.code) : detail;
      const errNext = [...next, { role: "system", content: "Error: " + (detailText || e.message), time: new Date().toLocaleTimeString() } as ChatMsg];
      setMessages(errNext);
      saveActive(errNext);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const boundKb = kbs.find(kb => kb.id === kbId);
  const carried = messages.filter(m => m.role === "user" || m.role === "assistant").slice(-contextWindow);
  // 上下文容量 = 压缩摘要 + 携带窗口内原文 + 待发送文本附件（估算 tokens）
  const [compressedSummary, setCompressedSummary] = useState(() => localStorage.getItem("chat.summary") || "");
  const attachTokens = Math.ceil(attachments.filter(a => a.kind === "text").reduce((sum, a) => sum + a.data.length, 0) / 4);
  const usedTokens = Math.ceil((compressedSummary.length + carried.reduce((sum, m) => sum + m.content.length, 0)) / 4) + attachTokens;
  // 上下文容量预算读所选模型配置的 context_window（effectiveModelConfig
  // 兜底 128K，与模型选择弹层显示同一口径）；容量 100% 自动压缩（LLM
  // 摘要算法）：旧消息摘要化替换原文，压缩后容量回落。
  const CONTEXT_BUDGET = modelCfg.context_window || 32000;
  const pct = Math.min(100, Math.round((usedTokens / CONTEXT_BUDGET) * 100));
  // 容量 100% 自动压缩（LLM 摘要算法）：旧消息摘要化替换原文，压缩后容量回落。
  const compressingRef = useRef(false);
  const compressFailedRef = useRef(false);
  useEffect(() => {
    compressFailedRef.current = false; // 新消息到达 → 允许重试压缩
    if (usedTokens < CONTEXT_BUDGET || compressingRef.current) return;
    const old = messages.slice(0, Math.max(0, messages.length - contextWindow));
    if (old.length === 0) return;
    compressingRef.current = true;
    apiClient.post("/chat/compress", {
      messages: old.map(m => ({ role: m.role, content: m.content })),
    }).then((res) => {
      const s = res.data?.summary;
      if (s) {
        setCompressedSummary(prev => (prev ? prev + "\n" : "") + s);
        const prevStore = localStorage.getItem("chat.summary") || "";
        localStorage.setItem("chat.summary", prevStore ? prevStore + "\n" + s : s);
        // 摘要已承接旧消息信息 → 移除原文，保留最近窗口
        setMessages(msgs => msgs.slice(-contextWindow));
        antdMessage.info(zh ? "上下文已自动压缩" : "Context auto-compressed");
      }
      compressingRef.current = false;
    }).catch(() => { compressFailedRef.current = true; compressingRef.current = false; });
  }, [usedTokens, messages, contextWindow, zh]);
  const fmtK = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n));

  return (
    <AppLayout>
      <PageHeading
        section="agent"
        navKey="chat"
        actions={(
          <>
          {boundKb && <Tag color="purple">{`${text.kbBound}: ${boundKb.name}`}</Tag>}
          </>
        )}
      />
      {/* 页面级双栏：左会话栏（Card 外）+ 右聊天区 */}
      <div style={{ display: "flex", gap: 14, alignItems: "stretch" }}>
      {/* 会话栏（页面左侧，Card 外）：新建会话按钮 + 会话列表（单击切换/双击重命名/删除） */}
      <div className="v2-panel" style={{ width: 210, flex: "0 0 210px", display: "flex", flexDirection: "column", padding: 12 }}>
        <Button icon={<PlusOutlined />} onClick={newChat} block>{zh ? "新建会话" : "New chat"}</Button>
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
          {sessions.slice(0, 50).map(s => (
            <div
              key={s.id}
              onClick={() => switchSession(s.id)}
              onDoubleClick={() => void renameSession(s.id, s.title)}
              title={zh ? "单击切换 · 双击重命名" : "Click to switch · double-click to rename"}
              style={{
                display: "flex", alignItems: "center", gap: 6, padding: "7px 8px",
                borderRadius: 8, cursor: "pointer", fontSize: 12.5,
                background: s.id === activeSessionId ? "rgba(47,155,245,.10)" : "transparent",
              }}
            >
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title}</span>
              <span style={{ color: "var(--v2-dim)", fontSize: 11 }}>{(s.messages || []).length}</span>
              <Button
                type="text" size="small" danger
                icon={<DeleteOutlined style={{ fontSize: 11 }} />}
                onClick={(e) => { e.stopPropagation(); void deleteSession(s.id); }}
                style={{ width: 20, height: 20, minWidth: 20 }}
              />
            </div>
          ))}
          {sessions.length === 0 ? (
            <span style={{ fontSize: 12, color: "var(--v2-dim)", padding: "4px 8px" }}>{zh ? "暂无会话" : "No sessions"}</span>
          ) : null}
        </div>
      </div>
      <Card style={{ flex: 1, minWidth: 0 }} styles={{ body: { height: "calc(100vh - 260px)", display: "flex", flexDirection: "column", padding: 0 } }}>
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
          {/* 工具编排进行中状态条（追问/确认期间常显；取消即放弃调用） */}
          {pendingToolCall && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8, marginBottom: 8, padding: "6px 10px",
              borderRadius: 10, border: "1px solid rgba(92,178,255,.35)", background: "rgba(47,155,245,.08)",
              fontSize: 12.5,
            }}>
              <ToolOutlined style={{ color: "var(--v2-blue)" }} />
              <span style={{ fontWeight: 600 }}>{zh ? "工具调用进行中" : "Tool call pending"}</span>
              <span style={{ color: "var(--v2-sub)" }}>
                {pendingToolCall.tool}
                {pendingToolCall.params && Object.keys(pendingToolCall.params).length > 0
                  ? `（${Object.entries(pendingToolCall.params).map(([k, v]) => `${k}=${String(v)}`).join("，")}）`
                  : ""}
                · {pendingToolCall.status === "clarify" ? (zh ? "等待补充参数" : "awaiting params") : zh ? "等待确认" : "awaiting confirmation"}
              </span>
              <Button type="text" size="small" danger onClick={() => setPendingToolCall(null)} style={{ marginLeft: "auto", height: 22, padding: "0 8px" }}>
                {zh ? "取消" : "Cancel"}
              </Button>
            </div>
          )}
          {/* ZCode 式输入框：最左 + 号（附件/知识库/系统提示词/白名单工具管理），右侧容量圆圈/模型/思考强度/发送 */}
          {(() => {
            return (
              <div style={{
                border: "1px solid var(--v2-line, #d9d9d9)", borderRadius: 16,
                background: "var(--v2-panel2, rgba(22,34,58,.35))",
                padding: "10px 12px 8px", transition: "border-color .15s",
              }}>
                {/* 待发送附件 chips（图片/文本，可移除；发送后清空） */}
                {attachments.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
                    {attachments.map(a => (
                      <Tag
                        key={a.uid}
                        closable
                        onClose={(e) => { e.preventDefault(); setAttachments(prev => prev.filter(x => x.uid !== a.uid)); }}
                        style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, padding: "2px 8px", borderRadius: 8 }}
                      >
                        {a.kind === "image" ? <FileImageOutlined /> : <FileTextOutlined />}
                        <span style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</span>
                      </Tag>
                    ))}
                  </div>
                )}
                {/* 原生 textarea：彻底去掉 antd 白底圆角嵌套块，融入容器 */}
                <textarea
                  autoComplete="off"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={text.placeholder}
                  disabled={loading}
                  rows={2}
                  style={{
                    width: "100%", border: "none", outline: "none", resize: "none",
                    background: "transparent", color: "var(--v2-txt, #142a33)",
                    fontSize: 13.5, lineHeight: 1.6, padding: "2px 6px",
                    fontFamily: "inherit",
                  }}
                />
                {/* 底部工具行：左=+ … 右=容量圆圈 | 模型 | 思考强度 | 发送 */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                  {/* + 号：附件 / 知识库 / 系统提示词 / 白名单工具管理（统一格式，各自弹窗） */}
                  <Dropdown
                    trigger={["click"]}
                    menu={{
                      items: [
                        { key: "attach", icon: <PaperClipOutlined />, label: text.attach },
                        { key: "kb", icon: <DatabaseOutlined />, label: text.knowledgeBase },
                        { key: "system", icon: <EditOutlined />, label: text.systemPrompt },
                        { key: "tools", icon: <ToolOutlined />, label: zh ? "白名单工具管理" : "Whitelist tools" },
                      ],
                      onClick: ({ key }) => {
                        if (key === "attach") setModal("attach");
                        if (key === "kb") { fetchKbs(); setModal("kb"); }
                        if (key === "system") setModal("prompt");
                        if (key === "tools") setModal("tools");
                      },
                    }}
                  >
                    <Button type="text" size="small" icon={<PlusOutlined style={{ fontSize: 16 }} />} aria-label={zh ? "添加" : "Add"} style={{ width: 28, height: 28, color: "var(--v2-sub)" }} />
                  </Dropdown>
                  {/* 上下文容量圆圈（悬停/点击展开） */}
                  <Popover
                    trigger={["click", "hover"]}
                    content={(() => {
                      const sysTokens = Math.ceil(systemPrompt.length / 4);
                      const kbTokens = kbId ? 1200 : 0;
                      const rows: Array<[string, number, string]> = [
                        [zh ? "消息" : "Messages", usedTokens, "#2f9bf5"],
                        [zh ? "知识库RAG" : "KB RAG", kbTokens, "#47c3a0"],
                        [zh ? "系统提示词" : "System prompt", sysTokens, "#9b7bff"],
                      ];
                      const rowTotal = Math.max(1, rows.reduce((s, [, v]) => s + v, 0));
                      return (
                        <div style={{ width: 280 }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                            <b style={{ fontSize: 13.5, color: "var(--v2-txt)" }}>{text.contextManager}</b>
                            <span style={{ fontSize: 12, color: "var(--v2-sub)", fontVariantNumeric: "tabular-nums" }}>
                              {fmtK(rowTotal)}/{fmtContextTokens(CONTEXT_BUDGET) ?? "32K"}（{pct}%）
                            </span>
                          </div>
                          <div style={{ height: 8, borderRadius: 4, background: "rgba(128,140,160,.25)", overflow: "hidden", marginBottom: 12 }}>
                            <div style={{ width: `${pct}%`, height: "100%", background: pct > 80 ? "#e66f75" : "#2f9bf5", borderRadius: 4 }} />
                          </div>
                          {rows.map(([name, value, color]) => {
                            const share = Math.round((value / rowTotal) * 1000) / 10;
                            return (
                              <div key={name} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: 12.5 }}>
                                <span style={{ width: 7, height: 7, borderRadius: "50%", background: color, flex: "0 0 auto" }} />
                                <span style={{ flex: 1, color: "var(--v2-txt)" }}>{name}</span>
                                <span style={{ color: "var(--v2-sub)", fontVariantNumeric: "tabular-nums" }}>{share.toFixed(1)}%</span>
                              </div>
                            );
                          })}
                          {/* 保留平均缓存命中率行；窗口滑条与清空按钮已按用户要求移除 */}
                          <div style={{ borderTop: "1px solid var(--v2-line, rgba(128,140,160,.4))", marginTop: 8, paddingTop: 8 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, color: "var(--v2-sub)" }}>
                              <span>{zh ? "平均缓存命中率" : "Avg cache hit"}</span>
                              <span>—</span>
                            </div>
                          </div>
                        </div>
                      );
                    })()}
                  >
                    {/* 空心环形进度（用量以环带颜色表示，中心镂空）；marginLeft:auto 推到右侧 */}
                    <div
                      title={`${text.contextManager}：≈${fmtK(usedTokens)} / ${fmtContextTokens(CONTEXT_BUDGET) ?? "32K"} tokens`}
                      style={{
                        width: 14, height: 14, borderRadius: "50%", cursor: "pointer", flex: "0 0 auto",
                        marginLeft: "auto",
                        background: `conic-gradient(var(--v2-blue) ${pct}%, rgba(128,140,160,.25) ${pct}% 100%)`,
                        display: "inline-flex", alignItems: "center", justifyContent: "center",
                      }}
                    >
                      <div style={{ width: 12, height: 12, borderRadius: "50%", background: "var(--v2-panel2, rgb(22,34,58))" }} />
                    </div>
                  </Popover>
                  {/* 模型+思考强度合并面板（参考 ZCode 第二图）：供应商头+模型列表带勾+思考强度渐变滑条 */}
                  <Popover
                    trigger="click"
                    placement="topRight"
                    content={(() => {
                      // 供应商分组（provider_group 优先，无组按档案名兜底）；
                      // 组名取组内最短档案名（克隆体名带 ·model_id 后缀，主档案最短）
                      const providerGroups: Array<{ key: string; label: string; items: any[] }> = [];
                      for (const p of profiles) {
                        const key = p.provider_group || `n:${p.name}`;
                        let bucket = providerGroups.find((g) => g.key === key);
                        if (!bucket) {
                          bucket = { key, label: p.name, items: [] };
                          providerGroups.push(bucket);
                        }
                        if (p.name && p.name.length < bucket.label.length) bucket.label = p.name;
                        bucket.items.push(p);
                      }
                      const activeProfile = profiles.find((p) => p.id === profileId) ?? profiles.find((p) => p.is_default) ?? null;
                      const activeKey = activeProfile ? (activeProfile.provider_group || `n:${activeProfile.name}`) : providerGroups[0]?.key;
                      const activeGroup = providerGroups.find((g) => g.key === activeKey) ?? providerGroups[0] ?? null;
                      // 模型列表只显示所选供应商下「开启」的模型（ZCode 语义）
                      const enabledModels = (activeGroup?.items ?? []).filter((p) => p.enabled !== false);
                      const modelCfg = effectiveModelConfig(activeProfile ?? undefined);
                      // 思考强度读所选供应商默认模型的 reasoning_levels 配置（未配置用默认档位）
                      const levels = [
                        ...(Array.isArray(modelCfg.reasoning_levels) && modelCfg.reasoning_levels.length
                          ? (modelCfg.reasoning_levels as string[]).map((level) => ({ value: level, label: level }))
                          : [
                              { value: "off", label: zh ? "关闭" : "Off" },
                              { value: "low", label: zh ? "低" : "Low" },
                              { value: "medium", label: zh ? "中" : "Med" },
                              { value: "high", label: zh ? "最高" : "Max" },
                            ]),
                      ];
                      // 所选等级不在模型等级列表中（切换模型后遗留）→ 归位到最低档
                      const fallbackIndex = thinkingLevel && levels.some(l => l.value === thinkingLevel)
                        ? levels.findIndex(l => l.value === thinkingLevel)
                        : 0;
                      const ti = Math.max(0, fallbackIndex);
                      const fmtTokens = fmtContextTokens;
                      const inputTypeLabels = INPUT_TYPE_LABELS;
                      return (
                        <div style={{ position: "relative", width: 250 }}>
                          {/* 供应商飞出面板：悬停/点击供应商头时出现在主面板左侧（ZCode 式） */}
                          {providerFlyout ? (
                            <div
                              onMouseLeave={() => setProviderFlyout(false)}
                              style={{
                                position: "absolute", top: 0, right: "calc(100% + 10px)",
                                width: 168, background: "var(--v2-panel, #fff)",
                                border: "1px solid var(--v2-line, #e5e7eb)", borderRadius: 10,
                                boxShadow: "0 4px 16px rgba(0,0,0,.12)", padding: "6px 6px 8px",
                              }}
                            >
                              {providerGroups.map((group) => {
                                const active = activeGroup?.key === group.key;
                                const groupOn = group.items.some((p) => p.enabled !== false);
                                return (
                                  <div
                                    key={group.key}
                                    onClick={() => {
                                      const target = group.items.find((x) => x.is_default) ?? group.items[0];
                                      if (target) setProfileId(target.id);
                                      setProviderFlyout(false);
                                    }}
                                    style={{
                                      display: "flex", alignItems: "center", gap: 6, padding: "8px 8px",
                                      borderRadius: 8, cursor: "pointer", fontSize: 13,
                                      background: active ? "rgba(47,155,245,.10)" : "transparent",
                                    }}
                                  >
                                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{group.label}</span>
                                    <span
                                      aria-hidden="true"
                                      title={groupOn ? (zh ? "已启用" : "enabled") : (zh ? "未启用" : "disabled")}
                                      style={{ width: 7, height: 7, borderRadius: "50%", flex: "0 0 auto", background: groupOn ? "#52c41a" : "#d9d9d9" }}
                                    />
                                    {active ? <span style={{ color: "var(--v2-blue)" }}>✓</span> : null}
                                  </div>
                                );
                              })}
                              <div style={{ borderTop: "1px solid var(--v2-line, rgba(36,52,79,.4))", marginTop: 6, paddingTop: 8 }}>
                                <a href="/llm-gateway" style={{ fontSize: 12, color: "var(--v2-dim)" }}>{zh ? "管理模型" : "Manage models"}</a>
                              </div>
                            </div>
                          ) : null}
                          {/* 主面板：供应商头 + 模型列表 + 思考强度 + 上下文容量 */}
                          <div>
                            <div
                              onMouseEnter={() => setProviderFlyout(true)}
                              onClick={() => setProviderFlyout((v) => !v)}
                              style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", cursor: "pointer", borderRadius: 8, border: "1px solid var(--v2-line, #e5e7eb)", marginBottom: 8 }}
                            >
                              <span aria-hidden="true" style={{ background: "#3859FF", borderRadius: 7, width: 26, height: 26, display: "inline-flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 12, flex: "0 0 auto" }}>
                                {(activeGroup?.label || "AI").slice(0, 1)}
                              </span>
                              <b style={{ fontSize: 13.5, color: "var(--v2-txt)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{activeGroup?.label ?? (zh ? "默认档案" : "Default profile")}</b>
                              <span className="v2-badge v2-bgray">{zh ? "API" : "API"}</span>
                              <span style={{ color: "var(--v2-dim)" }}>›</span>
                            </div>
                            <div style={{ fontSize: 12, color: "var(--v2-dim)", margin: "2px 0 4px" }}>{zh ? "模型" : "Model"}</div>
                            {enabledModels.map((p) => {
                              const selected = p.id === (profileId || profiles.find((x) => x.is_default)?.id);
                              const pCfg = effectiveModelConfig(p);
                              // 只保留输入类型徽标（视觉/视频/PDF）：容量/默认字样按用户要求移除
                              const extraTypes = (pCfg.input_types ?? []).filter((t) => t !== "text").map((t) => inputTypeLabels[t] ?? t);
                              return (
                                <div
                                  key={p.id}
                                  onClick={() => setProfileId(p.id)}
                                  style={{
                                    display: "flex", alignItems: "center", gap: 6, padding: "8px 10px",
                                    borderRadius: 8, cursor: "pointer", fontSize: 13,
                                    background: selected ? "rgba(47,155,245,.10)" : "transparent",
                                  }}
                                >
                                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.model_id}</span>
                                  {extraTypes.map((label) => <Tag key={label} style={{ marginRight: 0 }}>{label}</Tag>)}
                                  {selected ? <span style={{ color: "var(--v2-blue)" }}>✓</span> : null}
                                </div>
                              );
                            })}
                            {enabledModels.length === 0 ? (
                              <div className="v2-empty" style={{ padding: 12 }}>
                                {zh ? "该供应商暂无开启的模型" : "No enabled models"}
                              </div>
                            ) : null}
                            <div style={{ borderTop: "1px solid var(--v2-line, rgba(36,52,79,.4))", marginTop: 8, paddingTop: 10 }}>
                              {modelCfg.context_window ? (
                                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, fontSize: 12, color: "var(--v2-sub)" }}>
                                  <span>{zh ? "上下文容量" : "Context"}</span>
                                  <b style={{ color: "var(--v2-txt)" }}>{fmtTokens(modelCfg.context_window ?? null)}</b>
                                  <span style={{ marginLeft: "auto", color: "var(--v2-dim)", fontSize: 11 }}>{zh ? "来自模型配置" : "from model config"}</span>
                                </div>
                              ) : null}
                              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
                                <span style={{ fontSize: 12, color: "var(--v2-sub)" }}>{zh ? "思考强度" : "Thinking"}</span>
                                <b style={{ fontSize: 12.5, color: "var(--v2-txt)" }}>{levels[ti]?.label}</b>
                              </div>
                              <Slider
                                min={0} max={Math.max(0, levels.length - 1)} step={1} value={ti}
                                onChange={(v) => setThinkingLevel(levels[v]?.value ?? "off")}
                                tooltip={{ open: false }}
                                trackStyle={{ background: "linear-gradient(90deg, #1f9d55, #2f9bf5)", height: 10, borderRadius: 5 }}
                                handleStyle={{ width: 20, height: 20, background: "#fff", border: "none", boxShadow: "none" }}
                                styles={{ handle: { width: 20, height: 20, border: "none", boxShadow: "none" }, tracks: { background: "linear-gradient(90deg, #1f9d55, #2f9bf5)" } }}
                              />
                            </div>
                          </div>
                        </div>
                      );
                    })()}
                  >
                    <Button type="text" size="small" style={{ fontSize: 12.5, fontWeight: 600, color: "inherit" }}>
                      {(profiles.find(p => p.id === profileId) ?? profiles.find(p => p.is_default))?.model_id ?? (zh ? "默认模型" : "model")}
                      {" "}
                      {({ low: "低", medium: "中", high: "最高", off: "", disabled: "关" } as Record<string, string>)[thinkingLevel] ?? (modelReasoningLevels?.includes(thinkingLevel) ? thinkingLevel : "")}
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
      </div>
      {/* 附件弹窗：本地文档/图像加入本轮输入（随消息发给大模型） */}
      <Modal
        title={text.attach}
        open={modal === "attach"}
        onCancel={() => setModal(null)}
        footer={null}
        width={460}
      >
        <Upload.Dragger
          multiple
          showUploadList={false}
          accept=".txt,.md,.csv,.json,.log,.xml,.yaml,.yml,.py,.js,.ts,.tsx,.sql,.ini,.toml,image/png,image/jpeg,image/gif,image/webp,image/bmp"
          beforeUpload={(file: any) => { addAttachment(file as File); return false; }}
        >
          <p className="ant-upload-drag-icon" style={{ marginBottom: 6 }}><PaperClipOutlined style={{ fontSize: 26, color: "var(--v2-blue)" }} /></p>
          <p style={{ margin: 0, fontSize: 13 }}>{zh ? "点击或拖拽文件到此处添加附件" : "Click or drag files here"}</p>
          <div style={{ fontSize: 12, color: "var(--v2-dim)", marginTop: 4, padding: "0 12px" }}>{text.attachHint}</div>
        </Upload.Dragger>
        {attachments.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <Text strong style={{ fontSize: 12.5 }}>{zh ? "待发送附件" : "Pending attachments"}</Text>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
              {attachments.map(a => (
                <div key={a.uid} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, padding: "6px 8px", borderRadius: 8, border: "1px solid var(--v2-line, rgba(36,52,79,.5))" }}>
                  {a.kind === "image" ? <FileImageOutlined style={{ color: "var(--v2-blue)" }} /> : <FileTextOutlined style={{ color: "#47c3a0" }} />}
                  <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</span>
                  <Tag style={{ marginRight: 0 }}>{a.kind === "image" ? (zh ? "多模态输入" : "image") : zh ? "文本注入" : "text"}</Tag>
                  <Button type="text" size="small" danger icon={<DeleteOutlined style={{ fontSize: 12 }} />}
                    onClick={() => setAttachments(prev => prev.filter(x => x.uid !== a.uid))}
                    style={{ width: 22, height: 22, minWidth: 22 }} />
                </div>
              ))}
            </div>
            <Text type="secondary" style={{ display: "block", fontSize: 11.5, marginTop: 8 }}>
              {zh ? "附件显示在输入框上方，随下一条消息一起发送。" : "Attachments sit above the input and go with the next message."}
            </Text>
          </div>
        )}
      </Modal>
      {/* 知识库弹窗（绑定 RAG 检索） */}
      <Modal
        title={text.knowledgeBase}
        open={modal === "kb"}
        onCancel={() => setModal(null)}
        okText={text.save}
        onOk={() => { localStorage.setItem("chat.kbId", kbId); setModal(null); }}
        width={460}
      >
        <Select
          value={kbId || undefined}
          allowClear
          placeholder={text.noKnowledgeBase}
          onChange={(value) => setKbId(value || "")}
          style={{ width: "100%" }}
          options={kbs.map(kb => ({ value: kb.id, label: kb.name }))}
        />
        <Text type="secondary" style={{ display: "block", fontSize: 12, marginTop: 10 }}>{text.knowledgeBaseHint}</Text>
      </Modal>
      {/* 系统提示词弹窗（每轮注入的角色设定） */}
      <Modal
        title={text.systemPrompt}
        open={modal === "prompt"}
        onCancel={() => setModal(null)}
        okText={text.save}
        onOk={() => { localStorage.setItem("chat.systemPrompt", systemPrompt); setModal(null); }}
        width={520}
      >
        <Input.TextArea autoComplete="off" value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} rows={6} />
        <Text type="secondary" style={{ display: "block", fontSize: 12, marginTop: 10 }}>
          {zh ? "每轮对话开头注入的角色设定；保存后下次发送生效。" : "Injected at the start of every turn; applies from the next message."}
        </Text>
      </Modal>
      {/* 白名单工具管理弹窗（全局启停配置；对话内调用走自然语言编排） */}
      <ChatToolsModal open={modal === "tools"} onClose={() => setModal(null)} />
    </AppLayout>
  );
}
