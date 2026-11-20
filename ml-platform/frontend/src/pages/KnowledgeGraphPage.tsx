import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import {
  Select, Button, Form, Input, List, Typography, message, Card, Space, Tag, Empty,
  AutoComplete, InputNumber, Tooltip,
} from "antd";
import {
  PlusOutlined, DeleteOutlined, ReloadOutlined, AimOutlined, ScanOutlined,
  ApartmentOutlined, NodeIndexOutlined, EyeOutlined, EyeInvisibleOutlined,
} from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import PageHeading from "../components/PageHeading";
import ExtractionControl from "../components/kg/ExtractionControl";
import OntologyModal from "../components/kg/OntologyModal";
import FusionPanel from "../components/kg/FusionPanel";
import EntityDetailDrawer from "../components/kg/EntityDetailDrawer";
import PathQueryModal from "../components/kg/PathQueryModal";
import { useI18n } from "../i18n";
import { useTheme } from "../stores/themeContext";

const { Text } = Typography;

interface GraphNode {
  id: string; label: string; type?: string; source?: string; freq?: number;
  docCount?: number;
}
interface GraphEdge {
  source: string; target: string; label?: string; type?: string; weight?: number;
}
interface GraphData {
  nodes: GraphNode[]; edges: GraphEdge[];
}

// 总览时的边预算：Obsidian 观感是稀疏链接，全量共现边会糊成一片并拖慢渲染；
// 聚焦邻域时不裁剪，保证高亮完整
const MAX_VIEW_EDGES = 2500;

// Obsidian 风格柔和分组色板：type 优先分色，来源兜底，按序轮转
const GROUP_PALETTE = [
  "#8a7dff", "#4ec9b0", "#f7c65d", "#e06c9f", "#61afef",
  "#98c379", "#ff9f6a", "#6bcfff", "#d19cf5", "#e8a0a0",
];

// 占比最高的类型用中性色（Obsidian 默认是中性灰点，彩色只用于少数分组），
// 否则整片同色圆点会像「紫色海洋」
const NEUTRAL_NODE_COLOR = "#7f8b9e";

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
    auto: "自动", manual: "手动", docCount: (n: number) => `出处文档 ${n} 篇`,
    searchPh: "搜索实体，查看它的邻域",
    overview: "返回总览",
    inLibrary: "库内实体", viewOf: "当前视图",
    viewCap: "视图上限",
    viewCapHelp: "总览最多渲染的实体数量；库内超出时按连接数与词频优先采样（Top 枢纽 + 其关系），保证布局性能与可读性。聚焦邻域时不受此限制。",
    neighborhood: "邻域",
    entityList: "实体列表",
    ontology: "本体设置",
    pathQuery: "路径查询",
    labelsOn: "隐藏文字",
    labelsOff: "显示文字",
    relSource: "来源实体",
    relTarget: "目标实体",
    relSourcePh: "来源实体 ID",
    relTargetPh: "目标实体 ID",
    resetView: "重置视图",
    degreeLabel: "度数",
  } : {
    auto: "Auto", manual: "Manual", docCount: (n: number) => `${n} source doc(s)`,
    searchPh: "Search an entity to view its neighborhood",
    overview: "Back to overview",
    inLibrary: "In library", viewOf: "View",
    viewCap: "View cap",
    viewCapHelp: "Max entities rendered in the overview; beyond it, top-connected entities are sampled (top hubs + their edges) for layout performance and readability. Focus mode is not capped.",
    neighborhood: "Neighborhood",
    entityList: "Entities",
    ontology: "Ontology",
    pathQuery: "Path query",
    labelsOn: "Hide labels",
    labelsOff: "Show labels",
    relSource: "Source entity",
    relTarget: "Target entity",
    relSourcePh: "source entity id",
    relTargetPh: "target entity id",
    resetView: "Reset view",
    degreeLabel: "Links",
  };
  const chartRef = useRef<any>(null);
  const focusIdRef = useRef<string | null>(null);
  const [bases, setBases] = useState<any[]>([]);
  const [selectedKb, setSelectedKb] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [viewSize, setViewSize] = useState(100);
  const [ontologyOpen, setOntologyOpen] = useState(false);
  const [pathOpen, setPathOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [labelsVisible, setLabelsVisible] = useState(true);
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
          weight: Number(edge.properties?.weight ?? 1),
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

  // 视图模型：枢纽-卫星采样（Obsidian 观感的关键）——按度数取少量枢纽作骨架，
  // 再按边权重挂上低连接叶子实体，得到「少数大点 + 大量小点」的放射状结构；
  // 全量渲染 5 千实体时 echarts O(n²) 力导向不可行，故按 viewSize 采样。
  const view = useMemo((): GraphData => {
    const all = graphData.nodes;
    if (all.length === 0) return graphData;
    if (all.length <= viewSize) return graphData;

    const ranked = [...all].sort(
      (a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0)
        || (b.freq || 0) - (a.freq || 0),
    );
    const hubCount = Math.min(80, Math.max(12, Math.round(viewSize * 0.2)));
    const hubIds = new Set(ranked.slice(0, hubCount).map((n) => n.id));
    const keep = new Set(hubIds);
    const edges: GraphEdge[] = [];
    const sortedEdges = [...graphData.edges].sort((a, b) => (b.weight || 0) - (a.weight || 0));
    // 第一遍：强边骨架（枢纽之间的主干连接）
    for (const e of sortedEdges) {
      const sHub = hubIds.has(e.source);
      const tHub = hubIds.has(e.target);
      if (!sHub && !tHub) continue;
      if (!sHub || !tHub) {
        const leaf = sHub ? e.target : e.source;
        if (!keep.has(leaf)) {
          if (keep.size >= viewSize) continue;
          keep.add(leaf);
        }
      }
      if (edges.length >= MAX_VIEW_EDGES) break;
      edges.push(e);
    }
    // 第二遍：弱边挂低度数叶子实体（Obsidian 的「小点海」来源——连接稀疏的小实体）
    if (keep.size < viewSize) {
      const weakEdges = [...graphData.edges].sort((a, b) => (a.weight || 0) - (b.weight || 0));
      for (const e of weakEdges) {
        const sHub = hubIds.has(e.source);
        const tHub = hubIds.has(e.target);
        if (sHub === tHub) continue;
        const leaf = sHub ? e.target : e.source;
        if (keep.has(leaf)) continue;
        if ((degree.get(leaf) || 0) > 12) continue;
        if (keep.size >= viewSize) break;
        keep.add(leaf);
        if (edges.length < MAX_VIEW_EDGES) edges.push(e);
      }
    }
    if (focusId && !keep.has(focusId)) {
      keep.add(focusId);
      for (const e of graphData.edges) {
        if (e.source === focusId) keep.add(e.target);
        if (e.target === focusId) keep.add(e.source);
      }
    }
    const nodes = all.filter((n) => keep.has(n.id));
    return {
      nodes,
      edges: edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    };
  }, [graphData, focusId, viewSize, degree]);

  // 分组维度：type 优先（≥2 种类型时按类型分色），否则退回 auto/manual 来源
  const grouping = useMemo(() => {
    const nodes = graphData.nodes;
    if (nodes.length === 0) return null;
    const types = [...new Set(nodes.map((n) => n.type || "entity"))];
    if (types.length > 1) {
      const counts = new Map<string, number>();
      for (const n of nodes) {
        const key = n.type || "entity";
        counts.set(key, (counts.get(key) || 0) + 1);
      }
      let dominant = types[0];
      for (const t of types) {
        if ((counts.get(t) || 0) > (counts.get(dominant) || 0)) dominant = t;
      }
      let paletteIndex = 0;
      return {
        dim: "type" as const,
        items: types.map((t) => {
          if (t === dominant) {
            return { key: t, name: typeDisplayName(t, lang), color: NEUTRAL_NODE_COLOR };
          }
          const color = GROUP_PALETTE[paletteIndex % GROUP_PALETTE.length];
          paletteIndex += 1;
          return { key: t, name: typeDisplayName(t, lang), color };
        }),
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
    const repulsion = Math.min(600, 150 + nodeCount * 1.1);
    const nodes = view.nodes.map((n) => {
      const deg = degree.get(n.id) || 0;
      const size = Math.min(26, 3 + Math.sqrt(deg) * 1.35);
      // 搜索/点击选中的目标节点显著化：紫色放大+标签强制显示——
      // focusId 不在采样视图时由 view 注入逻辑把它拉进图，这里保证肉眼可见
      const isFocus = n.id === focusId;
      return {
        id: n.id,
        name: n.label,
        category: groupIndexOf(n),
        symbolSize: isFocus ? Math.max(size, 22) : size,
        label: { show: labelsVisible && (isFocus || size >= 10) },
        itemStyle: isFocus
          ? { color: "#8a7dff", opacity: 1, borderColor: "#6a5acd", borderWidth: 2 }
          : {
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
      // 底部类型图例：按当前库实际分组维度（实体类型优先）渲染——
      // LLM 深度抽取的类型（工艺/缺陷/设备…）有领域语义，图例恢复有意义
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
          // 节点多时关闭布局动画（O(n²) 每帧计算会卡），直接呈现收敛结果
          layoutAnimation: nodeCount <= 250,
        },
        categories: grouping?.items.map((g) => ({ name: g.name })) || [],
        data: nodes,
        links,
        lineStyle: {
          color: isDark ? "rgba(216,226,240,0.16)" : "rgba(20,42,51,0.18)",
          width: 1,
          curveness: 0.12,
        },
        label: {
          show: labelsVisible,
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
  }, [view, grouping, degree, groupIndexOf, groupColorOf, isDark, graphText, labelsVisible, focusId]);

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
            <Button
              icon={<ApartmentOutlined />}
              onClick={() => setOntologyOpen(true)}
              disabled={!selectedKb}
            >
              {graphText.ontology}
            </Button>
          </>
        )}
      />
      <div style={{
        marginBottom: 12, display: "flex", alignItems: "center",
        justifyContent: "space-between", flexWrap: "wrap", gap: 12,
      }}>
        <Space>
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
        </Space>
        <Space size={16}>
          <ExtractionControl kbId={selectedKb} onExtracted={loadGraph} />
          <Button
            icon={<NodeIndexOutlined />}
            onClick={() => setPathOpen(true)}
            disabled={!selectedKb || view.nodes.length === 0}
          >
            {graphText.pathQuery}
          </Button>
          <Tooltip title={labelsVisible ? graphText.labelsOn : graphText.labelsOff}>
            <Button
              icon={labelsVisible ? <EyeOutlined /> : <EyeInvisibleOutlined />}
              onClick={() => setLabelsVisible((v) => !v)}
              disabled={view.nodes.length === 0}
            >
              {labelsVisible ? graphText.labelsOn : graphText.labelsOff}
            </Button>
          </Tooltip>
          <Text type="secondary" style={{ fontSize: 13, whiteSpace: "nowrap" }}>
            {graphText.inLibrary}{" "}
            <Text strong style={{ fontSize: 16, fontVariantNumeric: "tabular-nums", color: isDark ? "#D8E2F0" : "#142A33" }}>
              {graphData.nodes.length.toLocaleString()}
            </Text>
            {"　"}
            {graphText.viewOf}{" "}
            <Text strong style={{ fontSize: 16, fontVariantNumeric: "tabular-nums", color: isDark ? "#D8E2F0" : "#142A33" }}>
              {view.nodes.length}
            </Text>
          </Text>
          <Tooltip title={graphText.viewCapHelp}>
            <Space size={6}>
              <Text type="secondary" style={{ fontSize: 13 }}>{graphText.viewCap}</Text>
              <InputNumber
                min={10} step={50} value={viewSize}
                onChange={(v) => setViewSize(Number(v) || 100)}
                style={{ width: 90 }}
              />
            </Space>
          </Tooltip>
        </Space>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
        <div style={{ flex: 1, minWidth: 460 }}>
          <Card
            style={{
              height: "calc(100vh - 230px)",
              minHeight: 560,
              padding: 0,
              overflow: "hidden",
            }}
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
        <div style={{
          width: 320,
          height: "calc(100vh - 230px)",
          minHeight: 560,
          display: "flex",
          flexDirection: "column",
          gap: 12,
          overflowY: "auto",
          overflowX: "hidden",
        }}>
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
              <Form.Item name="source_id" label={graphText.relSource} rules={[{ required: true }]}>
                <Input placeholder={graphText.relSourcePh} />
              </Form.Item>
              <Form.Item name="target_id" label={graphText.relTarget} rules={[{ required: true }]}>
                <Input placeholder={graphText.relTargetPh} />
              </Form.Item>
              <Form.Item name="relation_type" label={t.knowledge.relation_type}>
                <Input />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<PlusOutlined />} block>
                {t.knowledge.relation}
              </Button>
            </Form>
          </Card>
          <Card size="small" title={graphText.entityList}>
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
                    <Button type="link" size="small"
                      onClick={(e) => { e.stopPropagation(); setDetailId(node.id); setDetailOpen(true); }}
                    >
                      {lang === "zh" ? "详情" : "Info"}
                    </Button>,
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
          {selectedKb && (
            <FusionPanel kbId={selectedKb} onChanged={loadGraph} />
          )}
        </div>
      </div>
      <OntologyModal
        kbId={selectedKb}
        open={ontologyOpen}
        onClose={() => setOntologyOpen(false)}
      />
      <PathQueryModal
        kbId={selectedKb}
        nodes={graphData.nodes.map((n) => ({ id: n.id, label: n.label }))}
        open={pathOpen}
        onClose={() => setPathOpen(false)}
        onLocate={(id) => { setFocusId(id); setPathOpen(false); }}
      />
      <EntityDetailDrawer
        kbId={selectedKb}
        entityId={detailId}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        onLocate={(id) => { setFocusId(id); setDetailOpen(false); }}
      />
    </AppLayout>
  );
}
