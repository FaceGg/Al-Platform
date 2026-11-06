import { useState, useRef, useEffect } from "react";
import { Card, Input, Button, Typography, Space, Spin, Tag, Empty, Divider, Modal, Select, Collapse, Popover, Upload, Slider, message as antdMessage, Dropdown } from "antd";
import {
  SendOutlined, RobotOutlined, UserOutlined, SettingOutlined,
  FileTextOutlined, DownOutlined, PlusOutlined, EllipsisOutlined, CopyOutlined,
  EditOutlined, DeleteOutlined, CloudDownloadOutlined,
} from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import PageHeading from "../components/PageHeading";
import ChatToolsPanel from "../components/ChatToolsPanel";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

const { Text } = Typography;

interface ChatSource { index: number; chunk_id: string; doc_id: string; filename: string; score: number; }
interface ChatMsg { role: "user" | "assistant" | "system"; content: string; time: string; sources?: ChatSource[]; }
interface ChatSession { id: string; title: string; messages: ChatMsg[]; created_at?: string; updated_at?: string; }

export default function AIChatPage() {
  const { t, lang } = useI18n();
  const zh = lang === "zh";
  const text = zh ? {
    settings: "对话设置",
    systemPrompt: "系统提示词",
    start: "开始对话", thinking: "正在思考...",
    placeholder: "输入消息，Enter 发送…", save: "保存配置",
    knowledgeBase: "知识库（RAG）", knowledgeBaseHint: "绑定后回答基于知识库检索内容并标注引用来源",
    noKnowledgeBase: "不使用知识库", citations: "引用来源", noCitations: "本次回答未引用知识库内容",
    emptySources: "知识库中没有检索到相关内容，已按通用助手回答",
    contextManager: "上下文容量",
    newChat: "新建对话", sessions: "会话", rename: "重命名", copyId: "复制 ID",
    delete: "删除", copied: "已复制", attach: "添加数据",
    attachHint: "上传文件到所选项目的数据管理（CSV/Excel）",
    attachDone: "已上传为数据集",
    attachNoProject: "请先选择项目",
    upload: "上传", kbBound: "知识库", clearContext: "清空上下文",
  } : {
    settings: "Chat settings",
    systemPrompt: "System prompt",
    start: "Start a conversation", thinking: "Thinking...",
    placeholder: "Type a message, Enter to send…", save: "Save",
    knowledgeBase: "Knowledge base (RAG)", knowledgeBaseHint: "Answers grounded in retrieved chunks",
    noKnowledgeBase: "No knowledge base", citations: "Citations", noCitations: "No KB content used",
    emptySources: "Nothing relevant retrieved; answered as a general assistant",
    contextManager: "Context",
    newChat: "New chat", sessions: "Sessions", rename: "Rename", copyId: "Copy ID",
    delete: "Delete", copied: "Copied", attach: "Add data",
    attachHint: "Upload file to the selected project (CSV/Excel)",
    attachDone: "Uploaded as dataset",
    attachNoProject: "Select a project first",
    upload: "Upload", kbBound: "KB", clearContext: "Clear context",
  };
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState(() => localStorage.getItem("chat.systemPrompt") || "你是汽车焊接制造领域的智能助手。");
  const [temperature] = useState(() => Number(localStorage.getItem("chat.temperature") || "0.7"));
  const [kbId, setKbId] = useState(() => localStorage.getItem("chat.kbId") || "");
  const [kbs, setKbs] = useState<any[]>([]);
  const [listProjects, setListProjects] = useState(false);
  const [projects, setProjects] = useState<any[]>([]);
  const [attachProject, setAttachProject] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  // 多会话
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // ZCode 式工具条状态
  const [profiles, setProfiles] = useState<any[]>([]);
  const [profileId, setProfileId] = useState(() => localStorage.getItem("chat.profileId") || "");
  const [thinkingLevel, setThinkingLevel] = useState<string>(() => localStorage.getItem("chat.thinkingLevel") || "off");
  const [contextWindow, setContextWindow] = useState<number>(() => Number(localStorage.getItem("chat.contextWindow") || "8"));
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

  const send = async () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    const userMsg: ChatMsg = { role: "user", content: trimmed, time: new Date().toLocaleTimeString() };
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
  // 上下文容量 = 压缩摘要 + 携带窗口内原文（估算 tokens）
  const [compressedSummary, setCompressedSummary] = useState(() => localStorage.getItem("chat.summary") || "");
  const usedTokens = Math.ceil((compressedSummary.length + carried.reduce((sum, m) => sum + m.content.length, 0)) / 4);
  const CONTEXT_BUDGET = 32000;
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
          <Button icon={<PlusOutlined />} onClick={newChat}>{text.newChat}</Button>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: sessions.slice(0, 30).map(s => ({
                key: s.id,
                label: (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 180 }}>
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis" }}>{s.title}</span>
                    <span style={{ color: "var(--v2-dim)", fontSize: 11 }}>{(s.messages || []).length} 条</span>
                  </div>
                ),
                children: [
                  { key: "rename", icon: <EditOutlined />, label: text.rename },
                  { key: "copy", icon: <CopyOutlined />, label: text.copyId },
                  { type: "divider" },
                  { key: "delete", icon: <DeleteOutlined />, label: text.delete, danger: true },
                ],
                onClick: ({ key, domEvent }) => {
                  domEvent.stopPropagation();
                  if (key === "rename") void renameSession(s.id, s.title);
                  if (key === "copy") void copySessionId(s.id);
                  if (key === "delete") void deleteSession(s.id);
                },
              })),
              onClick: ({ key }) => switchSession(key as string),
            }}
          >
            <Button icon={<DownOutlined />}>{text.sessions}</Button>
          </Dropdown>
          <Button icon={<SettingOutlined />} onClick={() => { fetchKbs(); setSettingsOpen(true); }}>{text.settings}</Button>
          </>
        )}
      />
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
            const next = [...messages, { role: "assistant", content: resultText, time: new Date().toLocaleTimeString() } as ChatMsg];
            setMessages(next);
            saveActive(next);
          }} />
          {/* ZCode 式输入框：最左 + 号（数据/知识库/系统提示词/白名单工具），右侧容量圆圈/模型/思考强度/发送 */}
          {(() => {
            return (
              <div style={{
                border: "1px solid var(--v2-line, #d9d9d9)", borderRadius: 16,
                background: "var(--v2-panel2, rgba(22,34,58,.35))",
                padding: "10px 12px 8px", transition: "border-color .15s",
              }}>
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
                  {/* + 号：数据上传 / 知识库 / 系统提示词 / 白名单工具配置 收拢于此 */}
                  <Dropdown
                    trigger={["click"]}
                    menu={{
                      items: [
                        { key: "attach", icon: <CloudDownloadOutlined />, label: text.attach },
                        { key: "kb", icon: <FileTextOutlined />, label: text.knowledgeBase },
                        { key: "system", icon: <SettingOutlined />, label: text.systemPrompt },
                        { type: "divider" },
                        { key: "tools", icon: <EllipsisOutlined />, label: zh ? "白名单工具管理" : "Chat tools config" },
                      ],
                      onClick: ({ key }) => {
                        if (key === "kb" || key === "system") { fetchKbs(); setSettingsOpen(true); }
                        if (key === "tools") {
                          const btn = Array.from(document.querySelectorAll("button")).find(b => (b.innerText || "").includes("白名单工具"));
                          btn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
                        }
                        if (key === "attach") {
                          apiClient.get("/projects").then(r => {
                            const items = r.data?.items ?? r.data;
                            setProjects(Array.isArray(items) ? items : []);
                            setListProjects(true);
                          }).catch(() => {});
                        }
                      },
                    }}
                  >
                    <Button type="text" size="small" icon={<PlusOutlined style={{ fontSize: 16 }} />} aria-label={zh ? "添加" : "Add"} style={{ width: 28, height: 28, color: "var(--v2-sub)" }} />
                  </Dropdown>
                  {/* 附件上传到所选项目（数据管理）——真实上传 */}
                  <Modal
                    title={text.attach}
                    open={listProjects}
                    onCancel={() => setListProjects(false)}
                    footer={null}
                    width={420}
                  >
                    <Select
                      placeholder={zh ? "选择项目" : "Select project"}
                      style={{ width: "100%", marginBottom: 12 }}
                      value={attachProject ?? undefined}
                      onChange={setAttachProject}
                      options={projects.map(p => ({ value: p.id, label: p.name }))}
                    />
                    <Upload
                      beforeUpload={async (file: any) => {
                        if (!attachProject) { antdMessage.error(text.attachNoProject); return false; }
                        setUploading(true);
                        try {
                          const formData = new FormData();
                          formData.append("file", file);
                          await apiClient.post(`/projects/${attachProject}/datasets/upload`, formData);
                          antdMessage.success(text.attachDone);
                        } catch (e: any) {
                          antdMessage.error(e.response?.data?.detail || (zh ? "上传失败" : "Upload failed"));
                        } finally {
                          setUploading(false);
                        }
                        return false;
                      }}
                      showUploadList={false}
                      accept=".csv,.xls,.xlsx,.json,.parquet"
                    >
                      <Button icon={<CloudDownloadOutlined />} loading={uploading} disabled={!attachProject}>{text.upload}</Button>
                    </Upload>
                    <div style={{ fontSize: 12, color: "var(--v2-dim)", marginTop: 8 }}>{text.attachHint}</div>
                  </Modal>
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
                              {fmtK(rowTotal)}/32.0K（{pct}%）
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
                      title={`${text.contextManager}：≈${fmtK(usedTokens)} / 32.0K tokens`}
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
