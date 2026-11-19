import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import {
  Select, Button, Form, Input, List, Typography, message, Card, Space, Tag, Empty,
  AutoComplete, Statistic, InputNumber, Tooltip,
} from "antd";
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined, ThunderboltOutlined, AimOutlined, ScanOutlined,
} from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import PageHeading from "../components/PageHeading";
import { useI18n } from "../i18n";
import { useTheme } from "../stores/themeContext";

const { Text } = Typography;

interface GraphNode {
  id: string; label: string; type?: string; source?: string; freq?: number;
  docCount?: number;
}
interface GraphEdge {
  source: string; target: string; label?: string; type?: string;
}
interface GraphData {
  nodes: GraphNode[]; edges: GraphEdge[];
}

// Obsidian 风格柔和分组色板：type 优先分色，来源兜底，按序轮转
const GROUP_PALETTE = [
  "#8a7dff", "#4ec9b0", "#f7c65d", "#e06c9f", "#61afef",
  "#98c379", "#ff9f6a", "#6bcfff", "#d19cf5", "#e8a0a0",
];

// 实体类型显示名：抽取层 type 是英文标识（jieba 词性映射），中文界面翻译显示；
// 未知类型显示原值
const TYPE_DISPLAY_ZH: Record<string, string> = {
  concept: "概念", term: "术语", person: "人物", location: "地点",
  organization: "机构", standard: "标准", material: "材料", equipment: "设备",
  process: "工艺", disease: "疾病", indicator: "指标", unit: "单位",
};

function typeDisplayName(type: string, lang: string): string {
  if (lang !== "zh") return type;
  return TYPE_DISPLAY_ZH[type] ?? type;
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export default function KnowledgeGraphPage() {
  const { t, lang } = useI18n();
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const graphText = lang === "zh" ? {
    extract: "自动抽取", extracting: "抽取中...",
    extractDone: (e: number, r: number) => `抽取完成：新增实体 ${e} 个、关系 ${r} 条`,
    extractEmpty: "抽取完成：未发现满足阈值的实体（可检查文档内容或降低词频阈值）",
    extractFailed: "自动抽取失败",
    auto: "自动", manual: "手动", docCount: (n: number) => `出处文档 ${n} 篇`,
    searchPh: "搜索实体，查看它的邻域",
    overview: "返回总览",
    inLibrary: "库内实体", viewOf: "当前视图",
    viewHint: (lib: number, view: number) => `库内 ${lib} 实体 · 视图 ${view} 个${view < lib ? "（Top 高频 + 其关系）" : ""}`,
    neighborhood: "邻域",
    expandHint: "点击实体高亮其邻域 · 滚轮缩放 / 拖动平移 / 拖拽节点",
    resetView: "重置视图",
    degreeLabel: "度数",
  } : {
    extract: "Auto extract", extracting: "Extracting...",
    extractDone: (e: number, r: number) => `Extracted: ${e} entities, ${r} relations`,
    extractEmpty: "Extracted nothing above threshold (check document content or lower the frequency threshold)",
    extractFailed: "Auto extraction failed",
    auto: "Auto", manual: "Manual", docCount: (n: number) => `${n} source doc(s)`,
    searchPh: "Search an entity to view its neighborhood",
    overview: "Back to overview",
    inLibrary: "In library", viewOf: "View",
    viewHint: (lib: number, view: number) => `${lib} entities in library · ${view} in view${view < lib ? " (top hubs + their edges)" : ""}`,
    neighborhood: "Neighborhood",
    expandHint: "Click an entity to highlight its links · scroll to zoom / drag to pan / drag nodes",
    resetView: "Reset view",
    degreeLabel: "Links",
  };
  const chartRef = useRef<any>(null);
  const focusIdRef = useRef<string | null>(null);
  const [bases, setBases] = useState<any[]>([]);
  const [selectedKb, setSelectedKb] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [viewSize, setViewSize] = useState(100);
  const [form] = Form.useForm();
  const [edgeForm] = Form.useForm();
  focusIdRef.current = focusId;

  useEffect(() => {
    apiClient.get("/knowledge/bases").then((res) => {
      setBases(res.data.items || res.data || []);
    }).catch(() => {});
  }, []);

  const loadGraph = useCallback(() => {
    if (!selectedKb) return;
    setLoading(true);
    apiClient.get("/knowledge/bases/" + selectedKb + "/graph")
      .then((res) => {
        const data = res.data;
        const nodes = (data.nodes || []).map((n: any) => ({
          id: n.id,
          label: n.label ?? n.name ?? n.id,
          type: n.type ?? n.entity_type ?? "entity",
          source: n.properties?.source,
          freq: n.properties?.freq ?? 0,
          docCount: Array.isArray(n.properties?.doc_ids) ? n.properties.doc_ids.length : undefined,
        }));
        const edges = (data.edges || []).map((edge: any) => ({
          source: edge.source ?? edge.source_id,
          target: edge.target ?? edge.target_id,
          label: edge.label ?? edge.relation_type,
          type: edge.type ?? edge.relation_type,
        }));
        setGraphData({ nodes, edges });
        setFocusId(null);
      })
      .catch(() => message.error(t.common.error))
      .finally(() => setLoading(false));
  }, [selectedKb, t]);

  useEffect(() => { loadGraph(); }, [selectedKb]);

  // 全库度数（Obsidian 以链接数决定节点大小，聚焦视图下仍按全库度数缩放）
  const degree = useMemo(() => {
    const d = new Map<string, number>();
    for (const e of graphData.edges) {
      d.set(e.source, (d.get(e.source) || 0) + 1);
      d.set(e.target, (d.get(e.target) || 0) + 1);
    }
    return d;
  }, [graphData.edges]);

  // 视图模型：Top-N 总览；聚焦实体不在视图内时才并入其邻域（视图内容不变的
  // 点击只做粘性高亮，echarts-for-react 深比较跳过 setOption，力导向不重算）
  const view = useMemo((): GraphData => {
    const all = graphData.nodes;
    if (all.length === 0) return graphData;
    const keep = new Set<string>();
    if (all.length > viewSize) {
      const hubs = [...all]
        .sort((a, b) => (b.freq || 0) - (a.freq || 0)
          || (degree.get(b.id) || 0) - (degree.get(a.id) || 0))
        .slice(0, viewSize);
      for (const n of hubs) keep.add(n.id);
    } else {
      for (const n of all) keep.add(n.id);
    }
    if (focusId && !keep.has(focusId)) {
      keep.add(focusId);
      for (const e of graphData.edges) {
        if (e.source === focusId) keep.add(e.target);
        if (e.target === focusId) keep.add(e.source);
      }
    }
    return {
      nodes: all.filter((n) => keep.has(n.id)),
      edges: graphData.edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    };
  }, [graphData, focusId, viewSize, degree]);

  // 分组维度：type 优先（≥2 种类型时按类型分色），否则退回 auto/manual 来源
  const grouping = useMemo(() => {
    const nodes = graphData.nodes;
    if (nodes.length === 0) return null;
    const types = [...new Set(nodes.map((n) => n.type || "entity"))];
    if (types.length > 1) {
      return {
        dim: "type" as const,
        items: types.map((t, i) => ({
          key: t, name: typeDisplayName(t, lang), color: GROUP_PALETTE[i % GROUP_PALETTE.length],
        })),
      };
    }
    const sources = [...new Set(nodes.map((n) => n.source || "manual"))];
    return {
      dim: "source" as const,
      items: sources.map((s, i) => ({
        key: s,
        name: s === "auto" ? graphText.auto : graphText.manual,
        color: GROUP_PALETTE[i % GROUP_PALETTE.length],
      })),
    };
  }, [graphData.nodes, graphText, lang]);

  const groupIndexOf = useCallback((node: GraphNode): number => {
    if (!grouping) return 0;
    const value = grouping.dim === "type" ? (node.type || "entity") : (node.source || "manual");
    const idx = grouping.items.findIndex((g) => g.key === value);
    return idx >= 0 ? idx : 0;
  }, [grouping]);

  const groupColorOf = useCallback((node: GraphNode): string | undefined => {
    if (!grouping) return undefined;
    return grouping.items[groupIndexOf(node)]?.color;
  }, [grouping, groupIndexOf]);

  const searchOptions = useMemo(
    () => graphData.nodes.map((n) => ({ value: n.label, id: n.id })),
    [graphData.nodes],
  );

  const focusByLabel = (label: string) => {
    const node = graphData.nodes.find((n) => n.label === label);
    if (node) setFocusId(node.id);
  };

  // Obsidian 风格力导向图配置：hover 邻居高亮 + 其余淡出，滚轮缩放、拖动平移、节点可拖拽
  const option = useMemo(() => {
    const nodeCount = view.nodes.length;
    if (nodeCount === 0) return {};
    const repulsion = Math.min(500, 100 + nodeCount * 4);
    const nodes = view.nodes.map((n) => {
      const deg = degree.get(n.id) || 0;
      const size = Math.min(28, 4 + Math.sqrt(deg) * 1.5);
      return {
        id: n.id,
        name: n.label,
        category: groupIndexOf(n),
        // Obsidian 尺寸分布：绝大多数是小圆点，只有度数枢纽明显放大；
        // 小节点隐藏标签（hover 才显示），避免满屏文字挤压
        symbolSize: size,
        label: { show: size >= 10 },
        itemStyle: {
          color: groupColorOf(n),
          // 小节点淡化：度数越低越透明，减轻低频实体「点海」的视觉压迫
          opacity: 0.55 + Math.min(0.45, (deg / 16) * 0.45),
        },
        raw: n,
      };
    });
    const links = view.edges.map((e) => ({ source: e.source, target: e.target }));
    return {
      backgroundColor: "transparent",
      tooltip: {
        confine: true,
        backgroundColor: isDark ? "rgba(22,34,58,0.96)" : "#ffffff",
        borderColor: isDark ? "#24344f" : "#d9d9d9",
        textStyle: { color: isDark ? "#D8E2F0" : "#142A33", fontSize: 12 },
        formatter: (p: any) => {
          if (p.dataType !== "node") return "";
          const raw = p.data?.raw as GraphNode | undefined;
          if (!raw) return escapeHtml(p.data?.name ?? "");
          const group = grouping?.items[groupIndexOf(raw)];
          const lines = [`<b>${escapeHtml(raw.label)}</b>`];
          if (group) {
            lines.push(`<span style="color:${group.color}">●</span> ${escapeHtml(group.name)}`);
          }
          lines.push(raw.source === "auto" ? graphText.auto : graphText.manual);
          lines.push(`${graphText.degreeLabel}: ${degree.get(raw.id) || 0}`);
          if (raw.docCount) lines.push(graphText.docCount(raw.docCount));
          return lines.join("<br/>");
        },
      },
      legend: grouping && grouping.items.length > 1 ? {
        data: grouping.items.map((g) => g.name),
        bottom: 8,
        icon: "circle",
        itemWidth: 10,
        itemHeight: 10,
        type: "scroll",
        textStyle: { color: isDark ? "#8FA8C4" : "#57707B", fontSize: 11 },
      } : undefined,
      series: [{
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        // 圆环初始布局 + 较强向心力：整体轮廓收敛成近似圆形团聚（Obsidian 观感）
        initLayout: "circular",
        force: {
          repulsion,
          edgeLength: [55, 85],
          gravity: 0.38,
          layoutAnimation: nodeCount <= 300,
        },
        categories: grouping?.items.map((g) => ({ name: g.name })) || [],
        data: nodes,
        links,
        lineStyle: {
          color: isDark ? "rgba(216,226,240,0.22)" : "rgba(20,42,51,0.25)",
          width: 1,
          curveness: 0.12,
        },
        label: {
          show: true,
          position: "bottom",
          distance: 4,
          color: isDark ? "#8FA8C4" : "#57707B",
          fontSize: 11,
        },
        labelLayout: { hideOverlap: true },
        edgeLabel: { show: false },
        emphasis: {
          focus: "adjacency",
          label: { show: true },
          itemStyle: { shadowBlur: 12, shadowColor: "rgba(0,0,0,0.35)" },
          lineStyle: { width: 2, opacity: 0.9 },
        },
        blur: {
          itemStyle: { opacity: 0.06 },
          lineStyle: { opacity: 0.03 },
          label: { show: false },
        },
      }],
    };
  }, [view, grouping, degree, groupIndexOf, groupColorOf, isDark, graphText]);

  // onEvents 需保持稳定引用（echarts-for-react 按引用重绑），最新 focusId 走 ref
  const chartEvents = useMemo(() => ({
    click: (p: any) => {
      if (p.dataType !== "node") return;
      const id = p.data?.id;
      if (id) setFocusId(focusIdRef.current === id ? null : id);
    },
  }), []);

  // 聚焦=邻域粘性高亮：dispatchAction 只改状态不改数据，option 深比较不变则
  // setOption 被跳过，力导向不重算——点击后其他节点不会抖动
  useEffect(() => {
    const inst = chartRef.current?.getEchartsInstance?.();
    if (!inst) return;
    inst.dispatchAction({ type: "downplay", seriesIndex: 0 });
    if (focusId) {
      const idx = view.nodes.findIndex((n) => n.id === focusId);
      if (idx >= 0) {
        inst.dispatchAction({ type: "highlight", seriesIndex: 0, dataIndex: idx });
      }
    }
  }, [focusId, view]);

  const resetView = () => {
    const inst = chartRef.current?.getEchartsInstance?.();
    if (inst) inst.dispatchAction({ type: "restore" });
  };

  const addRelation = async (values: any) => {
    try {
      await apiClient.post("/knowledge/bases/" + selectedKb + "/graph/relations", values);
      message.success(t.common.success);
      edgeForm.resetFields();
      loadGraph();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const addEntity = async (values: any) => {
    try {
      await apiClient.post("/knowledge/bases/" + selectedKb + "/graph/entities", values);
      message.success(t.common.success);
      form.resetFields();
      loadGraph();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const extractGraph = async () => {
    if (!selectedKb || extracting) return;
    setExtracting(true);
    try {
      const res = await apiClient.post("/knowledge/bases/" + selectedKb + "/graph/extract");
      const report = res.data || {};
      if ((report.entities_created || 0) === 0 && (report.relations_created || 0) === 0) {
        message.info(graphText.extractEmpty);
      } else {
        message.success(graphText.extractDone(report.entities_created || 0, report.relations_created || 0));
      }
      loadGraph();
    } catch (e: any) {
      message.error(e.response?.data?.detail || graphText.extractFailed);
    } finally {
      setExtracting(false);
    }
  };

  const deleteEntity = async (id: string) => {
    try {
      await apiClient.delete("/knowledge/graph/entities/" + id);
      message.success(t.common.success);
      loadGraph();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  return (
    <AppLayout>
      <PageHeading
        section="agent"
        title={t.knowledge.graph}
        actions={(
          <>
            <Select
              placeholder={t.knowledge.title}
              style={{ width: 200 }}
              value={selectedKb}
              onChange={(v) => { setSelectedKb(v); setFocusId(null); }}
              options={bases.map((b: any) => ({ value: b.id, label: b.name }))}
            />
            <Button icon={<ReloadOutlined />} onClick={loadGraph} loading={loading}>
              {t.monitor.refresh}
            </Button>
            <Button icon={<ThunderboltOutlined />} onClick={extractGraph} disabled={!selectedKb} loading={extracting}>
              {graphText.extract}
            </Button>
          </>
        )}
      />
      <div style={{ marginBottom: 12 }}>
        <Space wrap>
          <AutoComplete
            options={searchOptions}
            style={{ width: 260 }}
            placeholder={graphText.searchPh}
            filterOption={(input, option) =>
              (option?.value || "").toLowerCase().includes(input.toLowerCase())}
            onSelect={(value: string | undefined) => { if (value) focusByLabel(value); }}
            value={undefined}
          />
          {focusId && (
            <Button icon={<AimOutlined />} onClick={() => setFocusId(null)}>
              {graphText.overview}
            </Button>
          )}
          <Statistic title={graphText.inLibrary} value={graphData.nodes.length} style={{ margin: 0 }} />
          <Statistic title={graphText.viewOf} value={view.nodes.length} style={{ margin: 0 }} />
          <InputNumber
            min={10} step={50} value={viewSize}
            onChange={(v) => setViewSize(Number(v) || 100)}
            style={{ width: 90 }}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>{graphText.expandHint}</Text>
        </Space>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
        <div style={{ flex: 1, minWidth: 460 }}>
          <Card
            style={{ height: 520, padding: 0, overflow: "hidden" }}
            styles={{ body: { height: "100%", padding: 0 } }}
          >
            {view.nodes.length === 0 && !loading ? (
              <Empty description={t.common.loading} style={{ marginTop: 200 }} />
            ) : (
              <div style={{ position: "relative", width: "100%", height: "100%" }}>
                <ReactECharts
                  ref={chartRef}
                  option={option}
                  notMerge
                  lazyUpdate
                  style={{ width: "100%", height: "100%" }}
                  onEvents={chartEvents}
                />
                <Tooltip title={graphText.resetView}>
                  <Button
                    size="small"
                    icon={<ScanOutlined />}
                    onClick={resetView}
                    style={{ position: "absolute", top: 10, right: 10, zIndex: 5 }}
                  />
                </Tooltip>
              </div>
            )}
          </Card>
        </div>
        <div style={{ width: 320, display: "flex", flexDirection: "column", gap: 12 }}>
          <Card size="small" title={t.knowledge.add_entity}>
            <Form form={form} onFinish={addEntity} layout="vertical" size="small" autoComplete="off">
              <Form.Item name="name" label={t.knowledge.entity_name} rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="entity_type" label={t.knowledge.entity_type}>
                <Input />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<PlusOutlined />} block>
                {t.knowledge.add_entity}
              </Button>
            </Form>
          </Card>
          <Card size="small" title={t.knowledge.relation}>
            <Form form={edgeForm} onFinish={addRelation} layout="vertical" size="small" autoComplete="off">
              <Form.Item name="source_id" label="Source ID" rules={[{ required: true }]}>
                <Input placeholder="source entity id" />
              </Form.Item>
              <Form.Item name="target_id" label="Target ID" rules={[{ required: true }]}>
                <Input placeholder="target entity id" />
              </Form.Item>
              <Form.Item name="relation_type" label={t.knowledge.relation_type}>
                <Input />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<PlusOutlined />} block>
                {t.knowledge.relation}
              </Button>
            </Form>
          </Card>
          <Card size="small" title={t.knowledge.entity + " " + t.nav.data}>
            <List
              size="small"
              dataSource={view.nodes}
              style={{ maxHeight: 260, overflowY: "auto" }}
              locale={{ emptyText: <Empty description={t.common.loading} /> }}
              renderItem={(node: GraphNode) => (
                <List.Item
                  style={{ cursor: "pointer", background: node.id === focusId ? "#fff7e6" : undefined }}
                  onClick={() => setFocusId(node.id === focusId ? null : node.id)}
                  actions={[
                    <Button type="link" danger size="small" icon={<DeleteOutlined />}
                      onClick={(e) => { e.stopPropagation(); deleteEntity(node.id); }} />,
                  ]}
                >
                  <Space>
                    <Tag style={{ marginInlineEnd: 0 }} color={groupColorOf(node)}>
                      {typeDisplayName(node.type || "entity", lang)}
                    </Tag>
                    <Text>{node.label}</Text>
                    {node.source === "auto"
                      ? <Tag color="orange">{graphText.auto}</Tag>
                      : <Tag>{graphText.manual}</Tag>}
                    {node.docCount ? <Text type="secondary" style={{ fontSize: 11 }}>{graphText.docCount(node.docCount)}</Text> : null}
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </div>
      </div>
    </AppLayout>
  );
}
