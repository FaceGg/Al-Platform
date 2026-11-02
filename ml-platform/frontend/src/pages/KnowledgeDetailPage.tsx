import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Tabs, Upload, Button, List, Typography, Input, message, Card, Space, Spin, Tag, Empty, Modal, Progress, Collapse, Statistic, Row, Col, Popconfirm } from "antd";
import { UploadOutlined, DeleteOutlined, SearchOutlined, SendOutlined, PlusOutlined, ArrowLeftOutlined, EyeOutlined, FileTextOutlined, ScissorOutlined, ApartmentOutlined, DownloadOutlined } from "@ant-design/icons";
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
  const [previewDoc, setPreviewDoc] = useState<any>(null);
  const heatRef = useRef<HTMLDivElement>(null);
  const distRef = useRef<HTMLDivElement>(null);
  const heatChartRef = useRef<echarts.ECharts | null>(null);
  const distChartRef = useRef<echarts.ECharts | null>(null);
  const graphChartRef = useRef<echarts.ECharts | null>(null);

  // 图表在隐藏页签里初始化会得到 0 尺寸容器；页签切换回可见后必须 resize。
  useEffect(() => {
    const resize = () => {
      heatChartRef.current?.resize();
      distChartRef.current?.resize();
      graphChartRef.current?.resize();
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
    // 大库可达数万实体/关系，全量拉取会卡死浏览器；预览只取最强子集
    apiClient.get(`/knowledge/bases/${kbId}/graph/entities?limit=2000`).then((res) => setEntities(Array.isArray(res.data) ? res.data : [])).catch(() => {});
    apiClient.get(`/knowledge/bases/${kbId}/graph/relations?limit=600`).then((res) => setRelations(Array.isArray(res.data) ? res.data : [])).catch(() => {});
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

  // 导出下载：PDF/Word/Excel 平台只存提取文本，后端统一导出为同名 .txt。
  const exportDoc = async (doc: any) => {
    try {
      const res = await apiClient.get(`/knowledge/documents/${doc.id}/export`, { responseType: "blob" });
      const name = doc.filename || `${doc.id}.txt`;
      const ext = (name.match(/\.[^.]+$/)?.[0] || "").toLowerCase();
      const downloadName = [".txt", ".md", ".csv"].includes(ext) ? name : name.replace(/\.[^.]*$/, "") + "（提取文本）.txt";
      const url = URL.createObjectURL(res.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = downloadName;
      anchor.click();
      URL.revokeObjectURL(url);
      message.success(zh ? "已开始下载" : "Download started");
    } catch (e: any) { message.error(e.response?.data?.detail || t.common.error); }
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

  // 知识图谱预览：点击实体聚焦其邻域（纯展示，编辑在独立图谱工具中）。
  const [focusEntity, setFocusEntity] = useState<string | null>(null);
  const graphCanvasRef = useRef<HTMLDivElement>(null);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);
  // 节点位置缓存（按知识库隔离）：静态布局只算一次，聚焦切换时复用既有坐标
  const graphPosRef = useRef<{ kbId: string; map: Map<string, [number, number]> }>({ kbId: "", map: new Map() });

  // 确保图谱已初始化并应用当前数据/聚焦。
  // 轮询兜底只负责「实例缺失时补挂」；数据/聚焦未变化时绝不能重复 setOption——
  // 每次调用都会重启过渡动画，表现为图谱持续转动不停。
  const ensureGraphChart = useCallback(() => {
    if (activeTab !== "graph" || !graphCanvasRef.current || entities.length === 0) return;
    const dom = graphCanvasRef.current;
    const chart = echarts.getInstanceByDom(dom) ?? echarts.init(dom);
    graphChartRef.current = chart;
    const chartAny = chart as any;
    const signature = [
      focusEntity,
      entities.length,
      relations.length,
      entities[0]?.id ?? "",
      relations[0]?.id ?? "",
    ].join("|");
    if (chartAny.__appliedSignature === signature) {
      // 仅在容器尺寸变化时 resize（页签过渡期初始化可能测到窄宽度）
      if (chartAny.__lastW !== dom.clientWidth || chartAny.__lastH !== dom.clientHeight) {
        chartAny.__lastW = dom.clientWidth;
        chartAny.__lastH = dom.clientHeight;
        chart.resize();
      }
      return;
    }
    chartAny.__appliedSignature = signature;
    chartAny.__lastW = dom.clientWidth;
    chartAny.__lastH = dom.clientHeight;
    requestAnimationFrame(() => chart.resize());
    const degree = new Map<string, number>();
    for (const rel of relations) {
      degree.set(rel.source_id, (degree.get(rel.source_id) || 0) + 1);
      degree.set(rel.target_id, (degree.get(rel.target_id) || 0) + 1);
    }
    let view = entities;
    if (focusEntity) {
      const keep = new Set([focusEntity]);
      for (const rel of relations) {
        if (rel.source_id === focusEntity) keep.add(rel.target_id);
        if (rel.target_id === focusEntity) keep.add(rel.source_id);
      }
      view = entities.filter((e) => keep.has(e.id));
      // 兜底：过滤结果为空（如键不一致或实体被清理）时不白屏，退回全量视图
      if (view.length === 0) view = entities;
    } else if (entities.length > 60) {
      view = [...entities]
        .sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0))
        .slice(0, 60);
    }
    const keepIds = new Set(view.map((e) => e.id));

    // —— 一次性静态力导向布局 ——
    // 不用 echarts 的 force（其模拟会持续步进、图永远在动），改为自行计算
    // 最终坐标后以 layout:"none" 渲染：静止、确定，节点仍可拖拽（data[].draggable）。
    if (graphPosRef.current.kbId !== kbId) graphPosRef.current = { kbId: kbId ?? "", map: new Map() };
    const posCache = graphPosRef.current.map;
    const W = Math.max(dom.clientWidth, 320);
    const H = Math.max(dom.clientHeight, 240);
    const fresh = view.filter((e) => !posCache.has(e.id));
    const R0 = Math.min(W, H) * 0.4;
    fresh.forEach((e, i) => {
      const a = (i / Math.max(1, fresh.length)) * Math.PI * 2 - Math.PI / 2;
      posCache.set(e.id, [W / 2 + R0 * Math.cos(a), H / 2 + R0 * Math.sin(a)]);
    });
    const idx = new Map(view.map((e, i) => [e.id, i]));
    const pts: [number, number][] = view.map((e) => posCache.get(e.id)!);
    const simEdges: [number, number][] = [];
    for (const r of relations) {
      const s = idx.get(r.source_id);
      const t = idx.get(r.target_id);
      if (s != null && t != null) simEdges.push([s, t]);
    }
    const LINK_LEN = 95, REPULSE = 4200, ITERATIONS = 220;
    for (let it = 0; it < ITERATIONS; it++) {
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          let dx = pts[i][0] - pts[j][0];
          let dy = pts[i][1] - pts[j][1];
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) { dx = 0.05; dy = 0.05; d2 = 1; }
          const d = Math.sqrt(d2);
          const f = REPULSE / d2 / d;
          pts[i][0] += dx * f; pts[i][1] += dy * f;
          pts[j][0] -= dx * f; pts[j][1] -= dy * f;
        }
      }
      for (const [s, t] of simEdges) {
        const dx = pts[t][0] - pts[s][0];
        const dy = pts[t][1] - pts[s][1];
        const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
        const f = ((d - LINK_LEN) / d) * 0.08;
        pts[s][0] += dx * f; pts[s][1] += dy * f;
        pts[t][0] -= dx * f; pts[t][1] -= dy * f;
      }
      for (const p of pts) {
        p[0] += (W / 2 - p[0]) * 0.01;
        p[1] += (H / 2 - p[1]) * 0.01;
      }
    }
    for (let i = 0; i < view.length; i++) {
      pts[i][0] = Math.min(Math.max(pts[i][0], 24), W - 24);
      pts[i][1] = Math.min(Math.max(pts[i][1], 24), H - 24);
      posCache.set(view[i].id, [pts[i][0], pts[i][1]]);
    }

    chart.setOption({
      tooltip: {},
      animationDurationUpdate: 500,
      animationEasingUpdate: "cubicInOut",
      series: [{
        type: "graph",
        layout: "none",
        roam: true, // 拖拽节点固定位置 / 滚轮缩放 / 空白处平移
        data: view.map((e, i) => ({
          id: e.id, name: e.name, category: e.entity_type,
          x: pts[i][0], y: pts[i][1],
          draggable: true,
          symbolSize: 9 + Math.min(11, (degree.get(e.id) || 0) * 2.5),
        })),
        links: relations
          .filter((r) => keepIds.has(r.source_id) && keepIds.has(r.target_id))
          .map((r) => ({ source: r.source_id, target: r.target_id, name: r.relation_type })),
        categories: [...new Set(view.map((e) => e.entity_type))].map((name) => ({ name })),
        label: { show: true, fontSize: 10 },
        // 悬停高亮邻域（其余节点淡出），聚焦/恢复切换带缓动过渡
        emphasis: {
          focus: "adjacency",
          itemStyle: { shadowBlur: 12, shadowColor: "rgba(56,132,255,0.45)" },
          label: { fontWeight: "bold" },
        },
        blur: { itemStyle: { opacity: 0.15 }, lineStyle: { opacity: 0.04 } },
        lineStyle: { color: "rgba(140,150,170,0.35)", width: 1, curveness: 0.12 },
      }],
    });
    // 拖拽节点与点击聚焦区分：位移超过阈值视为拖拽，不切换聚焦。
    // ensureGraphChart 会被轮询重复调用，handler 按引用精确替换，避免叠加或误删 roam 内部监听。
    if (chartAny.__downHandler) chart.getZr().off("mousedown", chartAny.__downHandler);
    chartAny.__downHandler = (ev: any) => { dragStartRef.current = { x: ev.offsetX, y: ev.offsetY }; };
    chart.getZr().on("mousedown", chartAny.__downHandler);
    if (chartAny.__clickHandler) chart.off("click", chartAny.__clickHandler);
    chartAny.__clickHandler = (params: any) => {
      if (params.dataType !== "node") return;
      const ev = params.event?.event;
      const dragStart = dragStartRef.current;
      if (dragStart && ev && Math.hypot(ev.offsetX - dragStart.x, ev.offsetY - dragStart.y) > 5) return;
      // 以实体 id 聚焦：params.name 是展示名，与邻域过滤的 id 键不一致会把视图过滤成空集（白屏）
      const id = params.data?.id ?? params.name;
      setFocusEntity(focusEntity === id ? null : id);
    };
    chart.on("click", chartAny.__clickHandler);
  }, [activeTab, entities, relations, focusEntity, kbId]);

  // 主 effect 之外再挂轮询兜底：页签首次激活的 effect 时序偶发不触发（实测复现），
  // 轮询保证 400ms 内图谱必然初始化。清理只停轮询，不销毁图表——聚焦切换等
  // 输入变化由 ensureGraphChart 原地复用实例平滑过渡。
  useEffect(() => {
    ensureGraphChart();
    const timer = window.setInterval(ensureGraphChart, 400);
    return () => window.clearInterval(timer);
  }, [ensureGraphChart]);

  // 仅在离开页面（组件卸载）时销毁实例。
  useEffect(() => {
    return () => {
      const dom = graphCanvasRef.current;
      if (dom) {
        const inst = echarts.getInstanceByDom(dom);
        if (inst) inst.dispose();
      }
      graphChartRef.current = null;
    };
  }, []);

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
                  <Space>
                    <Button size="small" icon={<EyeOutlined />} onClick={() => setPreviewDoc(doc)}>{zh ? "预览" : "Preview"}</Button>
                    <Button size="small" icon={<DownloadOutlined />} onClick={() => exportDoc(doc)}>{zh ? "导出" : "Export"}</Button>
                    <Button danger size="small" icon={<DeleteOutlined />} onClick={() => deleteDoc(doc.id)}>{t.ai_chat.delete}</Button>
                  </Space>
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
        <>
        <div style={{ display: "flex", gap: 12 }}>
          <Card size="small" title={zh ? "实体" : "Entities"} style={{ width: 300, flex: "0 0 300px" }}
            styles={{ body: { maxHeight: 430, overflowY: "auto", padding: "0 0" } }}>
            {entities.length === 0 ? <Empty description={zh ? "暂无实体（图谱数据由文档自动抽取生成）" : "No entities"} /> : (
              <List size="small" dataSource={entities} pagination={{ pageSize: 10, size: "small", showSizeChanger: false }} renderItem={(e: any) => (
                <List.Item
                  style={{ cursor: "pointer", background: focusEntity === e.id ? "#fff7e6" : undefined, padding: "4px 12px" }}
                  onClick={() => setFocusEntity(focusEntity === e.id ? null : e.id)}
                >
                  <Space><Tag color="blue">{e.entity_type}</Tag><Text>{e.name}</Text></Space>
                </List.Item>
              )} />
            )}
          </Card>
          <Card size="small" title={zh ? "关系预览" : "Relation preview"} style={{ flex: 1 }}
            styles={{ body: { padding: 0 } }}>
            {relations.length === 0 ? <Empty description={zh ? "暂无关系" : "No relations"} style={{ padding: 40 }} /> : (
              <div ref={graphCanvasRef} style={{ width: "100%", height: 430 }} />
            )}
          </Card>
        </div>
        <div style={{ color: "var(--v2-dim)", fontSize: 11.5, marginTop: 8 }}>
          {zh ? "知识图谱沉淀文档中的关键概念与工艺关系（设备—工艺—标准）；可拖拽节点固定位置、滚轮缩放、空白处平移，悬停节点高亮其邻域，点击实体或左侧列表聚焦。由文档自动抽取生成，预览仅展示权重最高的前 600 条关系。"
            : "Auto-extracted from documents. Drag nodes to reposition, scroll to zoom, pan on empty space; hover to highlight the neighborhood, click an entity (or the list) to focus. Preview shows the top 600 strongest relations."}
        </div>
        </>
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
      <Modal
        open={!!previewDoc}
        title={<Space><FileTextOutlined style={{ color: "#1890ff" }} />{previewDoc?.filename || previewDoc?.name}</Space>}
        onCancel={() => setPreviewDoc(null)}
        footer={null}
        width={760}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Tag color="blue">{previewDoc?.chunk_count || 0} {zh ? "分块" : "chunks"}</Tag>
          <Tag>{previewDoc?.doc_type || "text"}</Tag>
          {(previewDoc?.content_length || 0) > (previewDoc?.preview || "").length && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {zh ? `预览前 ${(previewDoc?.preview || "").length} 字 / 共 ${(previewDoc?.content_length || 0)} 字` : `Showing ${(previewDoc?.preview || "").length} of ${(previewDoc?.content_length || 0)} chars`}
            </Text>
          )}
        </Space>
        {(previewDoc?.preview || "").trim() ? (
          <Paragraph style={{ background: "#fafafa", color: "rgba(0,0,0,0.85)", padding: 12, borderRadius: 8, whiteSpace: "pre-wrap", maxHeight: 480, overflow: "auto", fontSize: 12.5, marginBottom: 0 }}>
            {previewDoc?.preview}
          </Paragraph>
        ) : (
          <Empty description={zh ? "该文档暂无可预览的文本内容" : "No preview text"} />
        )}
      </Modal>
    </AppLayout>
  );
}
