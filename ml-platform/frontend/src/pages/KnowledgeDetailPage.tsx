import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Tabs, Upload, Button, List, Typography, Input, message, Card, Space, Spin, Tag, Empty, Modal
} from "antd";
import {
  UploadOutlined, DeleteOutlined, SearchOutlined, SendOutlined, PlusOutlined, ArrowLeftOutlined
} from "@ant-design/icons";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text, Paragraph } = Typography;

export default function KnowledgeDetailPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState("docs");
  const [docs, setDocs] = useState<any[]>([]);
  const [chats, setChats] = useState<any[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [messageInput, setMessageInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [chatLoading, setChatLoading] = useState(false);

  const loadDocs = () => {
    apiClient.get("/knowledge/bases/" + kbId + "/documents")
      .then((res) => setDocs(res.data.items || res.data || []))
      .catch(() => {});
  };

  const loadChats = () => {
    apiClient.get("/knowledge/bases/" + kbId + "/chats")
      .then((res) => setChats(res.data.items || res.data || []))
      .catch(() => {});
  };

  useEffect(() => { loadDocs(); loadChats(); }, [kbId]);

  const uploadDoc = async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    try {
      await apiClient.post("/knowledge/bases/" + kbId + "/documents/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      message.success(t.common.success);
      loadDocs();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
    return false;
  };

  const deleteDoc = (docId: string) => {
    Modal.confirm({
      title: t.common.delete + "?",
      okType: "danger",
      cancelText: t.common.cancel,
      onOk: async () => {
        try {
          await apiClient.delete("/knowledge/bases/" + kbId + "/documents/" + docId);
          message.success(t.common.success);
          loadDocs();
        } catch (e: any) {
          message.error(e.response?.data?.detail || t.common.error);
        }
      },
    });
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setLoading(true);
    try {
      const res = await apiClient.post("/knowledge/bases/" + kbId + "/search", { query: searchQuery });
      setSearchResults(res.data.results || res.data || []);
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    } finally {
      setLoading(false);
    }
  };

  const createChat = async () => {
    try {
      const res = await apiClient.post("/knowledge/bases/" + kbId + "/chats", { title: "New Chat" });
      setActiveChatId(res.data.id);
      setChatMessages([]);
      loadChats();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const sendMessage = async () => {
    if (!messageInput.trim()) return;
    setChatLoading(true);
    const userMsg = { role: "user", content: messageInput };
    setChatMessages((prev) => [...prev, userMsg]);
    setMessageInput("");
    try {
      const res = await apiClient.post("/knowledge/bases/" + kbId + "/chat", {
        chat_id: activeChatId,
        message: userMsg.content,
      });
      setChatMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.data.answer || res.data.response || res.data.content, sources: res.data.sources },
      ]);
      if (!activeChatId && res.data.chat_id) {
        setActiveChatId(res.data.chat_id);
        loadChats();
      }
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    } finally {
      setChatLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  const tabItems = [
    {
      key: "docs",
      label: t.knowledge.upload,
      children: (
        <div>
          <Upload beforeUpload={(file) => { uploadDoc(file); return false; }} accept=".txt,.md,.csv" maxCount={1}>
            <Button icon={<UploadOutlined />}>{t.knowledge.upload}</Button>
          </Upload>
          <List
            style={{ marginTop: 16 }}
            dataSource={docs}
            locale={{ emptyText: <Empty description={t.common.loading} /> }}
            renderItem={(doc: any) => (
              <List.Item
                actions={[
                  <Button type="link" danger icon={<DeleteOutlined />}
                    onClick={() => deleteDoc(doc.id)}>{t.common.delete}</Button>,
                ]}
              >
                <List.Item.Meta title={doc.filename || doc.name} description={doc.created_at} />
              </List.Item>
            )}
          />
        </div>
      ),
    },
    {
      key: "search",
      label: t.knowledge.search,
      children: (
        <div>
          <Space.Compact style={{ width: "100%", marginBottom: 16 }}>
            <Input
              placeholder={t.knowledge.search}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }}
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>
              {t.knowledge.search}
            </Button>
          </Space.Compact>
          <Spin spinning={loading}>
            <List
              dataSource={searchResults}
              locale={{ emptyText: <Empty description={t.common.loading} /> }}
              renderItem={(item: any, idx: number) => (
                <Card key={idx} size="small" style={{ marginBottom: 8 }}>
                  <Paragraph>{item.content || item.text || item.chunk}</Paragraph>
                  <Space>
                    {item.score != null && <Tag color="blue">{t.automl.score}: {Number(item.score).toFixed(3)}</Tag>}
                    {item.source && <Text type="secondary">{t.knowledge.sources}: {item.source}</Text>}
                  </Space>
                </Card>
              )}
            />
          </Spin>
        </div>
      ),
    },
    {
      key: "chat",
      label: t.knowledge.chat,
      children: (
        <div style={{ display: "flex", height: "calc(100vh - 280px)", minHeight: 400 }}>
          <div style={{ width: 240, borderRight: "1px solid #f0f0f0", padding: 8, overflowY: "auto" }}>
            <Button type="dashed" block icon={<PlusOutlined />} onClick={createChat} style={{ marginBottom: 8 }}>
              {t.knowledge.chat}
            </Button>
            <List
              size="small"
              dataSource={chats}
              renderItem={(chat: any) => (
                <List.Item
                  style={{
                    cursor: "pointer",
                    background: activeChatId === chat.id ? "#e6f7ff" : undefined,
                    padding: "4px 8px",
                    borderRadius: 4,
                  }}
                  onClick={() => { setActiveChatId(chat.id); setChatMessages([]); }}
                >
                  <Text ellipsis>{chat.title || chat.name || "Chat " + chat.id}</Text>
                </List.Item>
              )}
            />
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", padding: "0 16px" }}>
            <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
              {chatMessages.map((msg: any, i: number) => (
                <div key={i} style={{ marginBottom: 12, textAlign: msg.role === "user" ? "right" : "left" }}>
                  <div style={{
                    display: "inline-block", maxWidth: "80%", padding: "8px 12px", borderRadius: 8,
                    background: msg.role === "user" ? "#1890ff" : "#f0f0f0",
                    color: msg.role === "user" ? "#fff" : "#000",
                    whiteSpace: "pre-wrap", wordBreak: "break-word",
                  }}>
                    {msg.content}
                  </div>
                  {msg.sources && msg.sources.length > 0 && (
                    <div style={{ marginTop: 4 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>{t.knowledge.sources}: </Text>
                      {msg.sources.map((s: any, si: number) => (
                        <Tag key={si} style={{ fontSize: 11 }}>{s.filename || s.source || s}</Tag>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {chatLoading && <Spin style={{ display: "block", textAlign: "center" }} />}
            </div>
            <div style={{ padding: "12px 0", borderTop: "1px solid #f0f0f0" }}>
              <Space.Compact style={{ width: "100%" }}>
                <Input.TextArea
                  value={messageInput}
                  onChange={(e) => setMessageInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={t.knowledge.send + "..."}
                  autoSize={{ minRows: 1, maxRows: 4 }}
                />
                <Button type="primary" icon={<SendOutlined />} onClick={sendMessage} loading={chatLoading}>
                  {t.knowledge.send}
                </Button>
              </Space.Compact>
            </div>
          </div>
        </div>
      ),
    },
  ];

  return (
    <AppLayout>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/knowledge")}>
          {t.workspace.back}
        </Button>
        <h3 style={{ margin: 0 }}>{t.knowledge.title}</h3>
      </div>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </AppLayout>
  );
}
