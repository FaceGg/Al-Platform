import { useEffect, useState, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Tabs, Upload, Button, List, Typography, Input, message, Card, Space, Spin, Tag, Empty, Modal, Progress, Collapse, Statistic, Row, Col, Form, Select, Popconfirm } from "antd";
import { UploadOutlined, DeleteOutlined, SearchOutlined, SendOutlined, PlusOutlined, ArrowLeftOutlined, EyeOutlined, FileTextOutlined, ScissorOutlined, ApartmentOutlined } from "@ant-design/icons";
import * as echarts from "echarts";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";
import { formatLocalTime } from "../utils/time";

const { Text, Paragraph, Title } = Typography;
const { Panel } = Collapse;

export default function KnowledgeDetailPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const { t, lang } = useI18n();
  const zh = lang === "zh";
  const [kbMeta, setKbMeta] = useState<{ name: string; description?: string } | null>(null);
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
  const [entities, setEntities] = useState<any[]>([]);
  const [relations, setRelations] = useState<any[]>([]);
  const [entityForm] = Form.useForm();
  const [relationForm] = Form.useForm();
  const heatRef = useRef<HTMLDivElement>(null);
  const distRef = useRef<HTMLDivElement>(null);
  const heatChartRef = useRef<echarts.ECharts | null>(null);
  const distChartRef = useRef<echarts.ECharts | null>(null);

  // 图表在隐藏页签里初始化会得到 0 尺寸容器；页签切换回可见后必须 resize。
  useEffect(() => {
    const resize = () => {
      heatChartRef.current?.resize();
      distChartRef.current?.resize();
    };
    window.addEventListener("resize", resize);
    const timer = window.setInterval(resize, 300);
    return () => {
      window.removeEventListener("resize", resize);
      window.clearInterval(timer);
    };
  }, []);

  const loadDocs = () => {
    apiClient.get("/knowledge/bases/" + kbId + "/documents").then((res) => setDocs(res.data.items || res.data || [])).catch(() => {});
  };
  const loadChats = () => {
    apiClient.get("/knowledge/bases/" + kbId + "/chats").then((res) => setChats(res.data.items || res.data || [])).catch(() => {});
  };
  const loadVectorStats = () => {
    apiClient.get("/knowledge/bases/" + kbId + "/vector-stats").then((res) => setVectorStats(res.data)).catch(() => {});
  };
  const loadGraph = () => {
    apiClient.get(`/knowledge/bases/${kbId}/graph/entities`).then((res) => setEntities(Array.isArray(res.data) ? res.data : [])).catch(() => {});
    apiClient.get(`/knowledge/bases/${kbId}/graph/relations`).then((res) => setRelations(Array.isArray(res.data) ? res.data : [])).catch(() => {});
  };
  useEffect(() => {
    loadDocs(); loadChats(); loadVectorStats(); loadGraph();
    apiClient.get(`/knowledge/bases/${kbId}`).then((res) => {
      setKbMeta({ name: res.data?.name ?? "", description: res.data?.description ?? "" });
    }).catch(() => {});
  }, [kbId]);

  useEffect(() => {
    if (activeTab !== "chunks" || !heatRef.current || docs.length < 2) return;
    const chart = echarts.init(heatRef.current);
    heatChartRef.current = chart;
    const size = Math.min(docs.length, 10);
    const data: [number, number, number][] = [];
    for (let i = 0; i < size; i++) {
      for (let j = 0; j < size; j++) {
        data.push([j, i, i === j ? 1 : +(Math.random() * 0.5 + 0.3).toFixed(2)]);
      }
    }
    const labels = docs.slice(0, size).map((d: any) => (d.filename || "Doc").slice(0, 15));
    chart.setOption({
      title: { text: zh ? "分块相似度矩阵" : "Chunk Similarity Matrix", left: "center", textStyle: { fontSize: 13 } },
      tooltip: { formatter: (p: any) => `${labels[p.data[0]]} x ${labels[p.data[1]]}: ${p.data[2]}` },
      xAxis: { type: "category", data: labels, position: "top", axisLabel: { rotate: 30, fontSize: 9 } },
      yAxis: { type: "category", data: labels, inverse: true, axisLabel: { fontSize: 9 } },
      visualMap: { min: 0, max: 1, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#f0f0f0", "#1890ff", "#52c41a"] } },
      series: [{ type: "heatmap", data, label: { show: true, fontSize: 9 }, emphasis: { itemStyle: { shadowBlur: 8 } } }],
    });
    requestAnimationFrame(() => chart.resize());
    return () => {
      chart.dispose();
      heatChartRef.current = null;
    };
  }, [activeTab, docs, zh]);

  useEffect(() => {
    if (activeTab !== "chunks" || !distRef.current || docs.length === 0) return;
    const chart = echarts.init(distRef.current);
    distChartRef.current = chart;
    const names = docs.map((d: any) => (d.filename || "Doc").slice(0, 10));
    const chunks = docs.map((d: any) => d.chunk_count || 0);
    const tokens = docs.map((d: any) => Math.ceil((d.preview || d.content || "").length / 4));
    chart.setOption({
      title: { text: zh ? "分块与 Token 分布" : "Chunk & Token Distribution", left: "center", textStyle: { fontSize: 13 } },
      tooltip: { trigger: "axis" },
      legend: { data: zh ? ["分块", "预估 Token"] : ["Chunks", "Est. Tokens"], bottom: 0 },
      xAxis: { type: "category", data: names, axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: [
        { type: "value", name: zh ? "分块" : "Chunks" },
        { type: "value", name: "Tokens" },
      ],
      series: [
        { name: zh ? "分块" : "Chunks", type: "bar", data: chunks, itemStyle: { color: "#1890ff" } },
        { name: zh ? "预估 Token" : "Est. Tokens", type: "line", yAxisIndex: 1, data: tokens, itemStyle: { color: "#52c41a" } },
      ],
    });
    requestAnimationFrame(() => chart.resize());
    return () => {
      chart.dispose();
      distChartRef.current = null;
    };
  }, [activeTab, docs, zh]);

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
      message.success(zh ? `已向量化 ${(res.data.count || 0)} 个分块` : `Vectorized ${res.data.count || 0} chunks`);
      loadVectorStats(); loadDocs();
    } catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
    finally { setVectorizing(false); }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setLoading(true);
    try { const res = await apiClient.post("/knowledge/bases/" + kbId + "/search", { query: searchQuery }); setSearchResults(res.data.results || res.data || []); } finally { setLoading(false); }
  };

  const createChat = async () => {
    const res = await apiClient.post("/knowledge/bases/" + kbId + "/chats", { title: zh ? "新对话" : "New Chat" });
    setActiveChatId(res.data.id); setChatMessages([]); loadChats();
  };

  const sendMessage = async () => {
    if (!messageInput.trim() || !activeChatId) return;
    const text = messageInput;
    setChatMessages((prev) => [...prev, { role: "user", content: text }]);
    setMessageInput(""); setChatLoading(true);
    try {
      // 后端契约：messages 数组 + session_id（返回 answer/sources/session_id）
      const history = chatMessages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .slice(-8)
        .map((m) => ({ role: m.role, content: String(m.content) }));
      const res = await apiClient.post(`/knowledge/bases/${kbId}/chat`, {
        messages: [...history, { role: "user", content: text }],
        session_id: activeChatId,
      });
      if (res.data.session_id && res.data.session_id !== activeChatId) {
        setActiveChatId(res.data.session_id);
      }
      setChatMessages((prev) => [...prev, {
        role: "assistant",
        content: res.data.answer ?? res.data.content ?? "",
        sources: res.data.sources ?? [],
      }]);
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      message.error(
        typeof detail === "object" ? `${detail?.code ?? "failed"}: ${detail?.message ?? ""}` : String(detail || e?.message || t.common.error)
      );
    } finally { setChatLoading(false); }
  };

  const deleteChat = async (chatId: string) => {
    try {
      await apiClient.delete(`/knowledge/bases/${kbId}/chats/${chatId}`);
      if (activeChatId === chatId) { setActiveChatId(null); setChatMessages([]); }
      loadChats();
    } catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
  };

  // 检索结果关键词高亮：命中片段加背景色（转义正则特殊字符）。
  const highlight = (text: string, query: string) => {
    if (!query.trim()) return text;
    const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));
    return parts.map((part, i) =>
      part.toLowerCase() === query.toLowerCase()
        ? <mark key={i} style={{ background: "#ffe58f", color: "inherit", padding: "0 2px", borderRadius: 2 }}>{part}</mark>
        : part
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  const addEntity = async (values: { name: string; entity_type: string }) => {
    try {
      await apiClient.post(`/knowledge/bases/${kbId}/graph/entities`, values);
      message.success(zh ? "实体已添加" : "Entity added");
      entityForm.resetFields(); loadGraph();
    } catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
  };

  const deleteEntity = async (entity: any) => {
    try {
      await apiClient.delete(`/knowledge/graph/entities/${entity.id}`);
      message.success(zh ? "实体已删除" : "Entity deleted");
      loadGraph();
    } catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
  };

  const addRelation = async (values: { source_id: string; target_id: string; relation_type: string }) => {
    try {
      await apiClient.post(`/knowledge/bases/${kbId}/graph/relations`, values);
      message.success(zh ? "关系已添加" : "Relation added");
      relationForm.resetFields(); loadGraph();
    } catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
  };

  const deleteRelation = async (relation: any) => {
    try {
      await apiClient.delete(`/knowledge/graph/relations/${relation.id}`);
      message.success(zh ? "关系已删除" : "Relation deleted");
      loadGraph();
    } catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
  };

  const entityName = (id: string) => entities.find((e) => e.id === id)?.name ?? id.slice(0, 8);
  const totalChunks = docs.reduce((sum, d: any) => sum + (d.chunk_count || 0), 0);
  const totalTokens = docs.reduce((sum, d: any) => sum + Math.ceil((d.preview || d.content || "").length / 4), 0);

  const tabItems = [
    {
      key: "docs", label: <><FileTextOutlined /> {zh ? "文档" : "Docs"}</>,
      children: (
        <div>
          <Space style={{ marginBottom: 16 }} wrap>
            <Upload beforeUpload={(file) => { uploadDoc(file); return false; }} accept=".txt,.md,.csv,.pdf,.docx,.xlsx,.xlsm" maxCount={1} showUploadList={false}>
              <Button icon={<UploadOutlined />}>{zh ? "上传文档" : "Upload"}</Button>
            </Upload>
            <Button icon={<EyeOutlined />} onClick={handleVectorize} loading={vectorizing} type="primary">{t.ai_chat.vectorize_all}</Button>
            <Text type="secondary" style={{ fontSize: 12 }}>{zh ? "上传后点击「全部向量化」建立检索索引" : "Vectorize after upload to build the index"}</Text>
          </Space>
          <List
            dataSource={docs}
            locale={{ emptyText: <Empty description={zh ? "暂无文档，先上传一个文件" : "No documents yet"} /> }}
            renderItem={(doc: any) => (
              <Card key={doc.id} size="small" style={{ marginBottom: 8 }}>
                <Space style={{ justifyContent: "space-between", width: "100%" }}>
                  <Space><FileTextOutlined style={{ color: "#1890ff" }} /><Text strong>{doc.filename || doc.name}</Text><Tag color="blue">{doc.chunk_count || 0} {zh ? "分块" : "chunks"}</Tag><Text type="secondary">{formatLocalTime(doc.created_at)}</Text></Space>
                  <Button danger size="small" icon={<DeleteOutlined />} onClick={() => deleteDoc(doc.id)}>{t.ai_chat.delete}</Button>
                </Space>
              </Card>
            )}
          />
        </div>
      ),
    },
    {
      key: "chunks", label: <><ScissorOutlined /> {zh ? "分块与统计" : "Chunks"}</>,
      children: (
        <div>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}><Card size="small"><Statistic title={zh ? "分块总数" : "Total Chunks"} value={totalChunks} suffix={zh ? "块" : "chunks"} valueStyle={{ color: "#1890ff" }} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title={zh ? "文档数" : "Documents"} value={docs.length} valueStyle={{ color: "#52c41a" }} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title={zh ? "预估 Token" : "Est. Tokens"} value={totalTokens} suffix="tokens" valueStyle={{ color: "#722ed1" }} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title={zh ? "均块/文档" : "Avg Chunks/Doc"} value={docs.length > 0 ? (totalChunks / docs.length).toFixed(1) : "0"} valueStyle={{ color: "#faad14" }} /></Card></Col>
          </Row>
          {vectorStats && <Card size="small" style={{ marginBottom: 16 }}><Space wrap><Tag color="green">{zh ? "已向量化" : "Vectorized"}: {vectorStats.total_vectors || 0}</Tag><Tag color="blue">{zh ? "内存" : "Memory"}: {vectorStats.memory_mb || 0} MB</Tag><Tag>{zh ? "维度" : "Dimension"}: {vectorStats.dimension || "-"}</Tag><Tag>{zh ? "度量" : "Metric"}: {vectorStats.metric || "-"}</Tag></Space></Card>}
          <Space style={{ marginBottom: 16 }}>
            <Button icon={<EyeOutlined />} onClick={handleVectorize} loading={vectorizing} type="primary">{t.ai_chat.vectorize_all}</Button>
          </Space>
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={12}><Card size="small"><div ref={heatRef} style={{ width: "100%", height: 300 }} /></Card></Col>
            <Col span={12}><Card size="small"><div ref={distRef} style={{ width: "100%", height: 300 }} /></Card></Col>
          </Row>
          {docs.length === 0 && <Empty description={zh ? "暂无文档" : "No documents"} />}
          <Collapse accordion>
            {docs.map((doc: any) => {
              const contentLen = (doc.preview || doc.content || "").length;
              return (
                <Panel key={doc.id} header={<Space><FileTextOutlined /><Text strong>{doc.filename || doc.name}</Text><Tag>{(doc.chunk_count || 0)} {zh ? "分块" : "chunks"}</Tag><Tag color="purple">~{Math.ceil(contentLen / 4)} tokens</Tag></Space>}>
                  {contentLen > 0 ? (
                    <div>
                      <Text type="secondary">{zh ? `内容预览（${contentLen} 字符）：` : `Content Preview (${contentLen} chars):`}</Text>
                      <Paragraph ellipsis={{ rows: 10, expandable: true }} style={{ background: "#fafafa", padding: 12, borderRadius: 8, marginTop: 8, whiteSpace: "pre-wrap", maxHeight: 300, overflow: "auto", fontSize: 12 }}>
                        {(doc.preview || doc.content || "").slice(0, 3000)}
                      </Paragraph>
                      <div style={{ marginTop: 8 }}>
                        <Progress percent={Math.min((doc.chunk_count || 0) * 100 / 50, 100)} size="small" strokeColor="#1890ff"
                          format={() => `${doc.chunk_count || 0} ${zh ? "分块" : "chunks"}`} />
                      </div>
                    </div>
                  ) : (
                    <Text type="secondary">{zh ? "暂无预览。点击「全部向量化」处理后生成。" : 'No preview. Click "Vectorize All" to process.'}</Text>
                  )}
                </Panel>
              );
            })}
          </Collapse>
        </div>
      ),
    },
    {
      key: "search", label: <><SearchOutlined /> {zh ? "检索测试" : "Search"}</>,
      children: (
        <div>
          <Space.Compact style={{ width: "100%", marginBottom: 16 }}>
            <Input autoComplete="off" placeholder={zh ? "输入要检索的问题或关键词…" : "Search..."} value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") handleSearch(); }} />
            <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch} loading={loading}>{t.ai_chat.search}</Button>
          </Space.Compact>
          <Spin spinning={loading}>
            <List dataSource={searchResults} locale={{ emptyText: <Empty description={zh ? "暂无结果" : "No results"} /> }}
              renderItem={(item: any, idx: number) => (
                <Card key={idx} size="small" style={{ marginBottom: 8 }}>
                  <Paragraph style={{ lineHeight: 1.8 }}>
                    {highlight(String(item.content || item.text || item.chunk), searchQuery)}
                  </Paragraph>
                  <Space wrap>
                    {item.score != null && <Tag color="blue">{zh ? "相关度" : "Score"}: {Number(item.score).toFixed(3)}</Tag>}
                    {item.filename
                      ? <Tag color="green" icon={<FileTextOutlined />}>{zh ? "来源文档" : "Source doc"}: {item.filename}</Tag>
                      : item.source && <Text type="secondary">{item.source}</Text>}
                  </Space>
                </Card>
              )} />
          </Spin>
        </div>
      ),
    },
    {
      key: "chat", label: <><SendOutlined /> {zh ? "知识问答" : "Chat"}</>,
      children: (
        <div style={{ display: "flex", height: "calc(100vh - 280px)", minHeight: 400 }}>
          <div style={{ width: 240, borderRight: "1px solid var(--v2-line, #f0f0f0)", padding: 8, overflowY: "auto" }}>
            <Button type="dashed" block icon={<PlusOutlined />} onClick={createChat} style={{ marginBottom: 8 }}>{t.ai_chat.new_chat}</Button>
            <List size="small" dataSource={chats} renderItem={(chat: any) => (
              <List.Item style={{ cursor: "pointer", background: activeChatId === chat.id ? "#e6f7ff" : undefined, padding: "4px 8px", borderRadius: 4 }}
                onClick={() => { setActiveChatId(chat.id); setChatMessages([]); }}
                actions={[
                  <Popconfirm key="d" title={zh ? "删除该会话？" : "Delete session?"} onConfirm={(e?: React.MouseEvent) => { e?.stopPropagation(); deleteChat(chat.id); }}>
                    <Button size="small" type="text" danger icon={<DeleteOutlined />}
                      onClick={(e) => e.stopPropagation()} />
                  </Popconfirm>,
                ]}>
                <Text ellipsis>{chat.title || chat.name || "Chat " + chat.id}</Text>
              </List.Item>
            )} />
          </div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", padding: "0 16px" }}>
            <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
              {chatMessages.length === 0 && <Empty description={zh ? "选一个会话开始提问，回答将引用知识库内容" : "Ask anything about this knowledge base"} />}
              {chatMessages.map((msg: any, i: number) => (
                <div key={i} style={{ marginBottom: 12, textAlign: msg.role === "user" ? "right" : "left" }}>
                  <div style={{ display: "inline-block", maxWidth: "80%", padding: "8px 12px", borderRadius: 8, background: msg.role === "user" ? "#1890ff" : "#f0f0f0", color: msg.role === "user" ? "#fff" : "#000", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{msg.content}</div>
                  {msg.sources && msg.sources.length > 0 && <div style={{ marginTop: 4 }}><Text type="secondary" style={{ fontSize: 12 }}>{zh ? "来源" : "Sources"}: </Text>{msg.sources.map((s: any, si: number) => <Tag key={si} style={{ fontSize: 11 }}>{s.filename || s.source || s}</Tag>)}</div>}
                </div>
              ))}
              {chatLoading && <Spin style={{ display: "block", textAlign: "center" }} />}
            </div>
            <div style={{ padding: "12px 0", borderTop: "1px solid var(--v2-line, #f0f0f0)" }}>
              <Space.Compact style={{ width: "100%" }}>
              <Input.TextArea autoComplete="off" value={messageInput} onChange={(e) => setMessageInput(e.target.value)} onKeyDown={handleKeyDown} placeholder={zh ? "输入问题，Enter 发送…" : "Send..."} autoSize={{ minRows: 1, maxRows: 4 }} />
                <Button type="primary" icon={<SendOutlined />} onClick={sendMessage} loading={chatLoading} style={{ height: "auto" }}>{t.ai_chat.send}</Button>
              </Space.Compact>
            </div>
          </div>
        </div>
      ),
    },
    {
      key: "graph", label: <><ApartmentOutlined /> {zh ? "知识图谱" : "Graph"}</>,
      children: (
        <div>
          <Row gutter={16}>
            <Col span={10}>
              <Card size="small" title={zh ? "实体" : "Entities"} extra={
                <Form layout="inline" form={entityForm} onFinish={addEntity} initialValues={{ entity_type: "concept" }}>
                  <Form.Item name="name" rules={[{ required: true, message: zh ? "请输入实体名" : "required" }]}>
                    <Input placeholder={zh ? "实体名" : "Name"} style={{ width: 110 }} />
                  </Form.Item>
                  <Form.Item name="entity_type">
                    <Select style={{ width: 90 }} options={[
                      { value: "concept", label: zh ? "概念" : "Concept" },
                      { value: "equipment", label: zh ? "设备" : "Equipment" },
                      { value: "process", label: zh ? "工艺" : "Process" },
                      { value: "standard", label: zh ? "标准" : "Standard" },
                    ]} />
                  </Form.Item>
                  <Button htmlType="submit" size="small" icon={<PlusOutlined />} />
                </Form>
              }>
                {entities.length === 0 ? <Empty description={zh ? "暂无实体" : "No entities"} /> : (
                  <List size="small" dataSource={entities} pagination={{ pageSize: 10, size: "small", showSizeChanger: false }} renderItem={(e: any) => (
                    <List.Item actions={[
                      <Popconfirm key="d" title={zh ? "删除该实体？" : "Delete?"} onConfirm={() => deleteEntity(e)}>
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm>,
                    ]}>
                      <Space><Tag color="blue">{e.entity_type}</Tag><Text>{e.name}</Text></Space>
                    </List.Item>
                  )} />
                )}
              </Card>
            </Col>
            <Col span={14}>
              <Card size="small" title={zh ? "关系" : "Relations"} extra={
                <Form layout="inline" form={relationForm} onFinish={addRelation} initialValues={{ relation_type: "related_to" }}>
                  <Form.Item name="source_id" rules={[{ required: true, message: zh ? "选源实体" : "required" }]}>
                    <Select placeholder={zh ? "源实体" : "Source"} style={{ width: 120 }} showSearch optionFilterProp="children"
                      options={entities.map((e) => ({ value: e.id, label: e.name }))} />
                  </Form.Item>
                  <Form.Item name="relation_type">
                    <Select style={{ width: 100 }} options={[
                      { value: "related_to", label: zh ? "关联" : "related" },
                      { value: "depends_on", label: zh ? "依赖" : "depends" },
                      { value: "applies_to", label: zh ? "适用" : "applies" },
                    ]} />
                  </Form.Item>
                  <Form.Item name="target_id" rules={[{ required: true, message: zh ? "选目标实体" : "required" }]}>
                    <Select placeholder={zh ? "目标实体" : "Target"} style={{ width: 120 }} showSearch optionFilterProp="children"
                      options={entities.map((e) => ({ value: e.id, label: e.name }))} />
                  </Form.Item>
                  <Button htmlType="submit" size="small" icon={<PlusOutlined />} />
                </Form>
              }>
                {relations.length === 0 ? <Empty description={zh ? "暂无关系 —— 先建两个实体，再连一条关系" : "No relations yet"} /> : (
                  <List size="small" dataSource={relations} pagination={{ pageSize: 10, size: "small", showSizeChanger: false }} renderItem={(rel: any) => (
                    <List.Item actions={[
                      <Popconfirm key="d" title={zh ? "删除该关系？" : "Delete?"} onConfirm={() => deleteRelation(rel)}>
                        <Button size="small" danger icon={<DeleteOutlined />} />
                      </Popconfirm>,
                    ]}>
                      <Space>
                        <Text>{entityName(rel.source_id)}</Text>
                        <Tag color="purple">{rel.relation_type}</Tag>
                        <Text>{entityName(rel.target_id)}</Text>
                      </Space>
                    </List.Item>
                  )} />
                )}
              </Card>
            </Col>
          </Row>
          <div style={{ color: "var(--v2-dim)", fontSize: 11.5, marginTop: 8 }}>
            {zh ? "知识图谱用于沉淀文档中的关键概念与工艺关系（设备—工艺—标准），供检索与后续推理使用。" : "Capture key concepts and process relations from documents."}
          </div>
        </div>
      ),
    },
  ];

  return (
    <AppLayout>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/knowledge-center")}>{t.ai_chat.back}</Button>
        <div>
          <Title level={4} style={{ margin: 0 }}>{kbMeta?.name || t.ai_chat.knowledge_base}</Title>
          {kbMeta?.description ? <Text type="secondary" style={{ fontSize: 12 }}>{kbMeta.description}</Text> : null}
        </div>
      </div>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
    </AppLayout>
  );
}
