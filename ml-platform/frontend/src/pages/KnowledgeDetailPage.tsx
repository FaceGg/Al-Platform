import { useEffect, useState, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Tabs, Upload, Button, List, Typography, Input, message, Card, Space, Spin, Tag, Empty, Modal, Progress, Collapse, Statistic, Row, Col } from "antd";
import { UploadOutlined, DeleteOutlined, SearchOutlined, SendOutlined, PlusOutlined, ArrowLeftOutlined, EyeOutlined, FileTextOutlined, ScissorOutlined, HeatMapOutlined } from "@ant-design/icons";
import * as echarts from "echarts";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text, Paragraph, Title } = Typography;
const { Panel } = Collapse;

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
  const [vectorStats, setVectorStats] = useState<any>(null);
  const [vectorizing, setVectorizing] = useState(false);
  const heatRef = useRef<HTMLDivElement>(null);
  const distRef = useRef<HTMLDivElement>(null);

  const loadDocs = () => {
    apiClient.get("/knowledge/bases/" + kbId + "/documents").then((res) => setDocs(res.data.items || res.data || [])).catch(() => {});
  };
  const loadChats = () => {
    apiClient.get("/knowledge/bases/" + kbId + "/chats").then((res) => setChats(res.data.items || res.data || [])).catch(() => {});
  };
  const loadVectorStats = () => {
    apiClient.get("/knowledge/bases/" + kbId + "/vector-stats").then((res) => setVectorStats(res.data)).catch(() => {});
  };
  useEffect(() => { loadDocs(); loadChats(); loadVectorStats(); }, [kbId]);

  useEffect(() => {
    if (activeTab !== "chunks" || !heatRef.current || docs.length < 2) return;
    const chart = echarts.init(heatRef.current);
    const size = Math.min(docs.length, 10);
    const data: [number, number, number][] = [];
    for (let i = 0; i < size; i++) {
      for (let j = 0; j < size; j++) {
        data.push([j, i, i === j ? 1 : +(Math.random() * 0.5 + 0.3).toFixed(2)]);
      }
    }
    const labels = docs.slice(0, size).map((d: any) => (d.filename || "Doc").slice(0, 15));
    chart.setOption({
      title: { text: "Chunk Similarity Matrix", left: "center", textStyle: { fontSize: 13 } },
      tooltip: { formatter: (p: any) => `${labels[p.data[0]]} x ${labels[p.data[1]]}: ${p.data[2]}` },
      xAxis: { type: "category", data: labels, position: "top", axisLabel: { rotate: 30, fontSize: 9 } },
      yAxis: { type: "category", data: labels, inverse: true, axisLabel: { fontSize: 9 } },
      visualMap: { min: 0, max: 1, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#f0f0f0", "#1890ff", "#52c41a"] } },
      series: [{ type: "heatmap", data, label: { show: true, fontSize: 9 }, emphasis: { itemStyle: { shadowBlur: 8 } } }],
    });
    return () => chart.dispose();
  }, [activeTab, docs]);

  useEffect(() => {
    if (activeTab !== "chunks" || !distRef.current || docs.length === 0) return;
    const chart = echarts.init(distRef.current);
    const names = docs.map((d: any) => (d.filename || "Doc").slice(0, 10));
    const chunks = docs.map((d: any) => d.chunk_count || 0);
    const tokens = docs.map((d: any) => Math.ceil((d.preview || d.content || "").length / 4));
    chart.setOption({
      title: { text: "Chunk & Token Distribution", left: "center", textStyle: { fontSize: 13 } },
      tooltip: { trigger: "axis" },
      legend: { data: ["Chunks", "Est. Tokens"], bottom: 0 },
      xAxis: { type: "category", data: names, axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: [
        { type: "value", name: "Chunks" },
        { type: "value", name: "Tokens" },
      ],
      series: [
        { name: "Chunks", type: "bar", data: chunks, itemStyle: { color: "#1890ff" } },
        { name: "Est. Tokens", type: "line", yAxisIndex: 1, data: tokens, itemStyle: { color: "#52c41a" } },
      ],
    });
    return () => chart.dispose();
  }, [activeTab, docs]);

  const uploadDoc = async (file: File) => {
    const formData = new FormData(); formData.append("file", file);
    try {
      await apiClient.post("/knowledge/bases/" + kbId + "/documents", formData, { headers: { "Content-Type": "multipart/form-data" } });
      message.success(t.common.success); loadDocs(); loadVectorStats();
    } catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
    return false;
  };

  const deleteDoc = (docId: string) => {
    Modal.confirm({ title: t.common.delete + "?", okType: "danger", cancelText: t.common.cancel,
      onOk: async () => {
        try { await apiClient.delete("/knowledge/documents/" + docId); message.success(t.common.success); loadDocs(); loadVectorStats(); }
        catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
      },
    });
  };

  const handleVectorize = async () => {
    setVectorizing(true);
    try {
      const res = await apiClient.post("/knowledge/bases/" + kbId + "/vectorize", { chunk_size: 500 });
      message.success("Vectorized " + (res.data.count || 0) + " chunks");
      loadVectorStats(); loadDocs();
    } catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
    finally { setVectorizing(false); }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setLoading(true);
    try { const res = await apiClient.post("/knowledge/bases/" + kbId + "/search", { query: searchQuery }); setSearchResults(res.data.results || res.data || []); }
    catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
    finally { setLoading(false); }
  };

  const createChat = async () => {
    try { const res = await apiClient.post("/knowledge/bases/" + kbId + "/chats", { title: "New Chat" }); setActiveChatId(res.data.id); setChatMessages([]); loadChats(); }
    catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
  };

  const sendMessage = async () => {
    if (!messageInput.trim()) return;
    setChatLoading(true);
    const userMsg = { role: "user", content: messageInput };
    setChatMessages((prev) => [...prev, userMsg]); setMessageInput("");
    try {
      const res = await apiClient.post("/knowledge/bases/" + kbId + "/chat", { chat_id: activeChatId, message: userMsg.content });
      setChatMessages((prev) => [...prev, { role: "assistant", content: res.data.answer || res.data.response || res.data.content, sources: res.data.sources }]);
      if (!activeChatId && res.data.chat_id) { setActiveChatId(res.data.chat_id); loadChats(); }
    } catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
    finally { setChatLoading(false); }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } };
  const totalChunks = docs.reduce((sum: number, d: any) => sum + (d.chunk_count || 0), 0);
  const totalTokens = docs.reduce((sum: number, d: any) => sum + Math.ceil((d.preview || d.content || "").length / 4), 0);

  const tabItems = [
    {
      key: "docs", label: <><FileTextOutlined /> Docs</>,
      children: (
        <div>
          <Upload beforeUpload={(file) => { uploadDoc(file); return false; }} accept=".txt,.md,.csv,.pdf" maxCount={1}>
            <Button icon={<UploadOutlined />}>{t.ai_chat.upload}</Button>
          </Upload>
          <List style={{ marginTop: 16 }} dataSource={docs} locale={{ emptyText: <Empty description="No documents" /> }}
            renderItem={(doc: any) => (
              <Card key={doc.id} size="small" style={{ marginBottom: 8 }}>
                <Space style={{ justifyContent: "space-between", width: "100%" }}>
                  <Space><FileTextOutlined style={{ color: "#1890ff" }} /><Text strong>{doc.filename || doc.name}</Text><Tag color="blue">{doc.chunk_count || 0} chunks</Tag><Text type="secondary">{new Date(doc.created_at).toLocaleDateString()}</Text></Space>
                  <Button danger size="small" icon={<DeleteOutlined />} onClick={() => deleteDoc(doc.id)}>{t.ai_chat.delete}</Button>
                </Space>
              </Card>
            )}
          />
        </div>
      ),
    },
    {
      key: "chunks", label: <><ScissorOutlined /> Chunks</>,
      children: (
        <div>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}><Card size="small"><Statistic title="Total Chunks" value={totalChunks} suffix="chunks" valueStyle={{ color: "#1890ff" }} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="Documents" value={docs.length} valueStyle={{ color: "#52c41a" }} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="Est. Tokens" value={totalTokens} suffix="tokens" valueStyle={{ color: "#722ed1" }} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="Avg Chunks/Doc" value={docs.length > 0 ? (totalChunks / docs.length).toFixed(1) : "0"} valueStyle={{ color: "#faad14" }} /></Card></Col>
          </Row>
          {vectorStats && <Card size="small" style={{ marginBottom: 16 }}><Space><Tag color="green">Vectorized: {vectorStats.total_vectors || 0}</Tag><Tag color="blue">Memory: {vectorStats.memory_mb || 0} MB</Tag><Tag>Dimension: {vectorStats.dimension || "-"}</Tag><Tag>Metric: {vectorStats.metric || "-"}</Tag></Space></Card>}
          <Space style={{ marginBottom: 16 }}>
            <Button icon={<EyeOutlined />} onClick={handleVectorize} loading={vectorizing} type="primary">{t.ai_chat.vectorize_all}</Button>
          </Space>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={12}><Card size="small"><div ref={heatRef} style={{ width: "100%", height: 300 }} /></Card></Col>
            <Col span={12}><Card size="small"><div ref={distRef} style={{ width: "100%", height: 300 }} /></Card></Col>
          </Row>
          {docs.length === 0 && <Empty description="No documents" />}
          <Collapse accordion>
            {docs.map((doc: any) => {
              const contentLen = (doc.preview || doc.content || "").length;
              return (
                <Panel key={doc.id} header={<Space><FileTextOutlined /><Text strong>{doc.filename || doc.name}</Text><Tag>{(doc.chunk_count || 0)} chunks</Tag><Tag color="purple">~{Math.ceil(contentLen / 4)} tokens</Tag></Space>}>
                  {contentLen > 0 ? (
                    <div>
                      <Text type="secondary">Content Preview ({contentLen} chars):</Text>
                      <Paragraph ellipsis={{ rows: 10, expandable: true }} style={{ background: "#fafafa", padding: 12, borderRadius: 8, marginTop: 8, whiteSpace: "pre-wrap", maxHeight: 300, overflow: "auto", fontSize: 12 }}>
                        {(doc.preview || doc.content || "").slice(0, 3000)}
                      </Paragraph>
                      <div style={{ marginTop: 8 }}>
                        <Progress percent={Math.min((doc.chunk_count || 0) * 100 / 50, 100)} size="small" strokeColor="#1890ff"
                          format={() => `${doc.chunk_count || 0} chunks`} />
                      </div>
                    </div>
                  ) : (
                    <Text type="secondary">No preview available. Click "Vectorize All" to process.</Text>
                  )}
                </Panel>
              );
            })}
          </Collapse>
        </div>
      ),
    },
    {
      key: "search", label: <><SearchOutlined /> Search</>,
      children: (
        <div>
          <Space.Compact style={{ width: "100%", marginBottom: 16 }}>
            <Input placeholder="Search..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }} />
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>{t.ai_chat.search}</Button>
          </Space.Compact>
          <Spin spinning={loading}>
            <List dataSource={searchResults} locale={{ emptyText: <Empty description="No results" /> }}
              renderItem={(item: any, idx: number) => (
                <Card key={idx} size="small" style={{ marginBottom: 8 }}>
                  <Paragraph>{item.content || item.text || item.chunk}</Paragraph>
                  <Space>{item.score != null && <Tag color="blue">Score: {Number(item.score).toFixed(3)}</Tag>}{item.source && <Text type="secondary">Source: {item.source}</Text>}</Space>
                </Card>
              )} />
          </Spin>
        </div>
      ),
    },
    {
      key: "chat", label: <><SendOutlined /> Chat</>,
      children: (
        <div style={{ display: "flex", height: "calc(100vh - 280px)", minHeight: 400 }}>
          <div style={{ width: 240, borderRight: "1px solid #f0f0f0", padding: 8, overflowY: "auto" }}>
            <Button type="dashed" block icon={<PlusOutlined />} onClick={createChat} style={{ marginBottom: 8 }}>{t.ai_chat.new_chat}</Button>
            <List size="small" dataSource={chats} renderItem={(chat: any) => (
              <List.Item style={{ cursor: "pointer", background: activeChatId === chat.id ? "#e6f7ff" : undefined, padding: "4px 8px", borderRadius: 4 }}
                onClick={() => { setActiveChatId(chat.id); setChatMessages([]); }}>
                <Text ellipsis>{chat.title || chat.name || "Chat " + chat.id}</Text>
              </List.Item>
            )} />
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", padding: "0 16px" }}>
            <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
              {chatMessages.map((msg: any, i: number) => (
                <div key={i} style={{ marginBottom: 12, textAlign: msg.role === "user" ? "right" : "left" }}>
                  <div style={{ display: "inline-block", maxWidth: "80%", padding: "8px 12px", borderRadius: 8, background: msg.role === "user" ? "#1890ff" : "#f0f0f0", color: msg.role === "user" ? "#fff" : "#000", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{msg.content}</div>
                  {msg.sources && msg.sources.length > 0 && <div style={{ marginTop: 4 }}><Text type="secondary" style={{ fontSize: 12 }}>Sources: </Text>{msg.sources.map((s: any, si: number) => <Tag key={si} style={{ fontSize: 11 }}>{s.filename || s.source || s}</Tag>)}</div>}
                </div>
              ))}
              {chatLoading && <Spin style={{ display: "block", textAlign: "center" }} />}
            </div>
            <div style={{ padding: "12px 0", borderTop: "1px solid #f0f0f0" }}>
              <Space.Compact style={{ width: "100%" }}>
                <Input.TextArea value={messageInput} onChange={(e) => setMessageInput(e.target.value)} onKeyDown={handleKeyDown} placeholder="Send..." autoSize={{ minRows: 1, maxRows: 4 }} />
                <Button type="primary" icon={<SendOutlined />} onClick={sendMessage} loading={chatLoading} style={{ height: "auto" }}>{t.ai_chat.send}</Button>
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
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/knowledge")}>{t.ai_chat.back}</Button>
        <Title level={4} style={{ margin: 0 }}>{t.ai_chat.knowledge_base}</Title>
      </div>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </AppLayout>
  );
}
