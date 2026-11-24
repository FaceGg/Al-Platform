import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import {
  Select, Button, Form, Input, List, Typography, message, Card, Space, Tag, Empty, Tabs,
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
import ExtractionActions from "../components/kg/ExtractionActions";
import ExtractionStatus from "../components/kg/ExtractionStatus";
import { useKgExtraction } from "../components/kg/useKgExtraction";
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

const EMPTY_GRAPH: GraphData = { nodes: [], edges: [] };

// 画布卡片与右栏高度随视口：页头 + 两行工具栏（动作行 + 抽取状态行）约占的像素
const CANVAS_OFFSET = 240;
const CANVAS_HEIGHT = `calc(100vh - ${CANVAS_OFFSET}px)`;

// 小图谱（实体数不超过它）给每个节点都显示名称；更大的只给连接多的节点显示
const COMPACT_GRAPH_NODES = 60;

// Obsidian 风格柔和分组色板：type 优先分色，来源兜底，按序轮转
const GROUP_PALETTE = [
  "#8a7dff", "#4ec9b0", "#f7c65d", "#e06c9f", "#61afef",
  "#98c379", "#ff9f6a", "#6bcfff", "#d19cf5", "#e8a0a0",
];

// 占比最高的类型用中性色（Obsidian 默认是中性灰点，彩色只用于少数分组），
// 否则整片同色圆点会像「紫色海洋」
const NEUTRAL_NODE_COLOR = "#7f8b9e";

// 实体类型固定色映射：跨知识库一致（同一类型永远同一颜色），
// 未登记类型统一中性灰（与「概念」同色系）
const TYPE_COLORS: Record<string, string> = {
  工艺: "#8a7dff",
  缺陷: "#e06c75",
  设备: "#61afef",
  材料: "#98c379",
  指标: "#f7c65d",
  标准: "#56b6c2",
  部件: "#ff9f6a",
  组织: "#d19cf5",
  人员: "#e8a0a0",
  术语: "#6bcfff",
  concept: "#7f8b9e",
  term: "#6bcfff",
  person: "#e8a0a0",
  location: "#d19cf5",
  organization: "#ff9f6a",
  standard: "#56b6c2",
  material: "#98c379",
  equipment: "#61afef",
  process: "#8a7dff",
};

function typeColor(type: string): string {
  return TYPE_COLORS[type] ?? NEUTRAL_NODE_COLOR;
}

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
    // 标题栏的图谱规模：与状态行标注的「实体 N · 关系 M」同口径
    entitiesLabel: "实体", relationsLabel: "关系", viewOf: "当前视图",
    emptyKb: "该知识库还没有实体，可先点击「快速抽取」或「深度抽取」",
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
    entitiesLabel: "Entities", relationsLabel: "relations", viewOf: "View",
    emptyKb: "No entities yet — run quick or deep extraction first",
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
  // 全图请求序号：只有最新一次请求的响应可以落到画布（见 loadGraph）
  const loadSeqRef = useRef(0);
  const [bases, setBases] = useState<any[]>([]);
  const [selectedKb, setSelectedKb] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData>(EMPTY_GRAPH);
  const [loading, setLoading] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [viewSize, setViewSize] = useState(100);
  const [ontologyOpen, setOntologyOpen] = useState(false);
  const [pathOpen, setPathOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [labelsVisible, setLabelsVisible] = useState(true);
  // 搜索聚焦模式：搜索选中后只显示目标节点及其直接邻居
  const [searchFocus, setSearchFocus] = useState(false);
  const [form] = Form.useForm();
  const [edgeForm] = Form.useForm();
  focusIdRef.current = focusId;

  useEffect(() => {
    apiClient.get("/knowledge/bases").then((res) => {
      setBases(res.data.items || res.data || []);
    }).catch(() => {});
  }, []);

  // 后端图载荷 → 画布数据模型
  const toGraphData = useCallback((data: any): GraphData => {
    const nodes = (data?.nodes || []).map((n: any) => ({
      id: n.id,
      label: n.label ?? n.name ?? n.id,
      type: n.type ?? n.entity_type ?? "entity",
      source: n.properties?.source,
      freq: n.properties?.freq ?? 0,
      docCount: Array.isArray(n.properties?.doc_ids) ? n.properties.doc_ids.length : undefined,
    }));
    const edges = (data?.edges || []).map((edge: any) => ({
      source: edge.source ?? edge.source_id,
      target: edge.target ?? edge.target_id,
      label: edge.label ?? edge.relation_type,
      type: edge.type ?? edge.relation_type,
      weight: Number(edge.properties?.weight ?? 1),
    }));
    return { nodes, edges };
  }, []);

  // quiet：抽取期间的自动刷新——不转圈、不清选中，画布原地长大
  const loadGraph = useCallback((opts?: { quiet?: boolean }) => {
    if (!selectedKb) return;
    const quiet = opts?.quiet === true;
    // 请求序号守卫：大库的全图响应可能比后来发起的小库请求晚到（「开发计划」
    // 7,915 实体/66 万关系要数十秒）。过期的响应必须丢弃，否则会把当前选中库
    // 的图覆盖成别的库——实测选「点焊工艺」画布却显示「开发计划」（2026-11-23）
    const seq = ++loadSeqRef.current;
    if (!quiet) setLoading(true);
    apiClient.get("/knowledge/bases/" + selectedKb + "/graph")
      .then((res) => {
        if (seq !== loadSeqRef.current) return;
        setGraphData(toGraphData(res.data));
        if (!quiet) setFocusId(null);
      })
      .catch(() => {
        if (seq === loadSeqRef.current && !quiet) message.error(t.common.error);
      })
      .finally(() => { if (seq === loadSeqRef.current && !quiet) setLoading(false); });
  }, [selectedKb, t, toGraphData]);

  useEffect(() => {
    // 切库立即清掉上一个库的图（不残留成「下拉是 A、画布是 B」）；
    // 同库刷新不走这里，画布不闪空
    setGraphData(EMPTY_GRAPH);
    loadGraph();
  }, [selectedKb]);

  // 抽取产出落库 / 抽取结果被替换：重新拉图。合并模式更新（见下方 ReactECharts），
  // 已有节点保持原位，抽取期间画布是「长出来」的而不是整图重排
  const handleExtracted = useCallback(() => loadGraph({ quiet: true }), [loadGraph]);

  const extraction = useKgExtraction({ kbId: selectedKb, onExtracted: handleExtracted });
  const { refreshSummary } = extraction;

  // 手工改动（增删实体/关系、融合审核、手动刷新）之后，图谱与抽取摘要一起
  // 重新拉取——状态标注与标题栏始终是同一组数字
  const reloadGraph = useCallback(() => {
    loadGraph();
    if (selectedKb) void refreshSummary(selectedKb);
  }, [loadGraph, refreshSummary, selectedKb]);

  // 标题栏的图谱规模：任务进行中用任务行计数（与状态行进度里的数字同一来源，
  // 左右两侧逐项相等），其余时候就是画布数据的节点/连线数
  const liveGraph = extraction.running || extraction.waitingCancel;
  const graphTotals = liveGraph
    ? {
        entities: extraction.job?.entities_found ?? 0,
        relations: extraction.job?.relations_found ?? 0,
      }
    : { entities: graphData.nodes.length, relations: graphData.edges.length };

  // 全库度数（Obsidian 以链接数决定节点大小，聚焦视图下仍按全库度数缩放）
  const degree = useMemo(() => {
    const d = new Map<string, number>();
    for (const e of graphData.edges) {
      d.set(e.source, (d.get(e.source) || 0) + 1);
      d.set(e.target, (d.get(e.target) || 0) + 1);
    }
    return d;
  }, [graphData.edges]);

  const viewCap = viewSize;

  // 视图模型：枢纽-卫星采样（Obsidian 观感的关键）——按度数取少量枢纽作骨架，
  // 再按边权重挂上低连接叶子实体，得到「少数大点 + 大量小点」的放射状结构；
  // 全量渲染 5 千实体时 echarts O(n²) 力导向不可行，故按 viewSize 采样。
  const view = useMemo((): GraphData => {
    const all = graphData.nodes;
    if (all.length === 0) return graphData;
    // 搜索聚焦模式（用户期望：搜索后只显示目标节点及其直接相连节点，
    // Obsidian 式聚焦视图；其余节点隐藏）。点击节点/返回总览退出该模式。
    if (searchFocus && focusId) {
      const keep = new Set<string>([focusId]);
      for (const e of graphData.edges) {
        if (e.source === focusId) keep.add(e.target);
        if (e.target === focusId) keep.add(e.source);
      }
      const nodes = all.filter((n) => keep.has(n.id));
      const edges = graphData.edges.filter(
        (e) => keep.has(e.source) && keep.has(e.target),
      );
      return { nodes, edges };
    }
    if (all.length <= viewCap) return graphData;

    const ranked = [...all].sort(
      (a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0)
        || (b.freq || 0) - (a.freq || 0),
    );
    const hubCount = Math.min(80, Math.max(12, Math.round(viewCap * 0.2)));
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
          if (keep.size >= viewCap) continue;
          keep.add(leaf);
        }
      }
      if (edges.length >= MAX_VIEW_EDGES) break;
      edges.push(e);
    }
    // 第二遍：弱边挂低度数叶子实体（Obsidian 的「小点海」来源——连接稀疏的小实体）
    if (keep.size < viewCap) {
      const weakEdges = [...graphData.edges].sort((a, b) => (a.weight || 0) - (b.weight || 0));
      for (const e of weakEdges) {
        const sHub = hubIds.has(e.source);
        const tHub = hubIds.has(e.target);
        if (sHub === tHub) continue;
        const leaf = sHub ? e.target : e.source;
        if (keep.has(leaf)) continue;
        if ((degree.get(leaf) || 0) > 12) continue;
        if (keep.size >= viewCap) break;
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
  }, [graphData, focusId, viewCap, degree, searchFocus]);

  // 分组维度：type 优先（≥2 种类型时按类型分色），否则退回 auto/manual 来源
  const grouping = useMemo(() => {
    const nodes = graphData.nodes;
    if (nodes.length === 0) return null;
    const types = [...new Set(nodes.map((n) => n.type || "entity"))];
    if (types.length > 1) {
      // 类型固定色映射：同一类型跨库永远同一颜色（样式统一）
      return {
        dim: "type" as const,
        items: types.map((t) => ({
          key: t,
          name: typeDisplayName(t, lang),
          color: typeColor(t),
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
    if (node) {
      setSearchFocus(true);
      setFocusId(node.id);
    }
  };

  // Obsidian 风格力导向图配置：hover 邻居高亮 + 其余淡出，滚轮缩放、拖动平移、节点可拖拽
  const option = useMemo(() => {
    const nodeCount = view.nodes.length;
    if (nodeCount === 0) return {};
    const repulsion = Math.min(600, 150 + nodeCount * 1.1);
    // 节点大小库内归一：按「度数/库内最大度数」比例映射到固定区间（5-20px），
    // 不同库呈现同构的大小分布（少量大 hub + 大量小点），跨库风格一致
    const maxDeg = Math.max(1, ...Array.from(degree.values()));
    // 小图谱给每个节点都显示名称（受「隐藏文字」开关约束），不按大小隐藏
    const showAllLabels = view.nodes.length <= COMPACT_GRAPH_NODES;
    const nodes = view.nodes.map((n) => {
      const deg = degree.get(n.id) || 0;
      const size = 5 + 15 * Math.sqrt(deg / maxDeg);
      // 选中节点的高亮不在此处渲染（focusId 不进 option deps）——进 deps 会让
      // 每次点击全量重建 option → 力导向从头模拟 → 其它节点疯狂抖动。
      // 高亮由下方增量 effect 以「锁定当前坐标的全量 data」更新，零重排。
      return {
        id: n.id,
        name: n.label,
        category: groupIndexOf(n),
        symbolSize: size,
        label: { show: labelsVisible && (showAllLabels || size >= 10) },
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
      // 底部类型图例：按当前库实际分组维度（实体类型优先）渲染——
      // LLM 深度抽取的类型（工艺/缺陷/设备…）有领域语义，图例恢复有意义。
      // 只有一种类型时显式隐藏：合并模式下传 undefined 不会撤掉已有的图例
      legend: grouping && grouping.items.length > 1 ? {
        data: grouping.items.map((g) => g.name),
        bottom: 8,
        icon: "circle",
        itemWidth: 10,
        itemHeight: 10,
        type: "scroll",
        textStyle: { color: isDark ? "#8FA8C4" : "#57707B", fontSize: 11 },
      } : { show: false, data: [] },
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
  }, [view, grouping, degree, groupIndexOf, groupColorOf, isDark, graphText, labelsVisible]);

  // 选中节点高亮：增量更新（focusId 不进 option deps——进 deps 会让每次点击
  // 全量重建 option → 力导向从头模拟 → 其它节点疯狂抖动）。
  // 关键：全量 data 每项带「当前显示坐标」（getItemLayout），位置零重排；
  // 选中节点紫色放大+标签强制，其余节点还原基础样式。
  const prevFocusRef = useRef<string | null>(null);
  useEffect(() => {
    // 没有选中、也没有「刚取消的选中」可还原时不动图表：否则每次数据更新
    // （如抽取视图长出新节点）都会把所有节点钉在当前坐标并关掉布局动画
    if (!focusId && !prevFocusRef.current) return;
    const inst = chartRef.current?.getEchartsInstance?.();
    const seriesModel = inst?.getModel?.()?.getSeriesByIndex?.(0);
    const seriesData = seriesModel?.getData?.();
    if (!inst || !seriesData) return;
    const count = seriesData.count();
    if (count === 0) return;
    const full: Record<string, unknown>[] = [];
    const degreeMax = Math.max(1, ...Array.from(degree.values()));
    for (let i = 0; i < count; i++) {
      const name = seriesData.getName(i);
      const layout = seriesData.getItemLayout(i);
      const rawItem = (seriesData.getRawDataItem(i) ?? {}) as Record<string, any>;
      const deg = degree.get(rawItem?.raw?.id ?? "") || 0;
      const size = 5 + 15 * Math.sqrt(deg / degreeMax);
      const isTarget = !!focusId && rawItem?.raw?.id === focusId;
      const base = {
        id: rawItem?.id ?? name,
        name,
        x: Array.isArray(layout) ? layout[0] : undefined,
        y: Array.isArray(layout) ? layout[1] : undefined,
        symbolSize: isTarget ? Math.max(size, 22) : size,
        label: {
          show: labelsVisible
            && (isTarget || view.nodes.length <= COMPACT_GRAPH_NODES || size >= 10),
        },
        itemStyle: isTarget
          ? { color: "#8a7dff", opacity: 1, borderColor: "#6a5acd", borderWidth: 2 }
          : {
              color: groupColorOf(rawItem?.raw as GraphNode),
              opacity: 0.55 + Math.min(0.45, (deg / 16) * 0.45),
            },
      };
      full.push(base);
    }
    inst.setOption(
      { series: [{ data: full, force: { layoutAnimation: false } }] },
      { lazyUpdate: true },
    );
    prevFocusRef.current = focusId;
  }, [focusId, view, labelsVisible, degree, groupColorOf]);

  // onEvents 需保持稳定引用（echarts-for-react 按引用重绑），最新 focusId 走 ref
  const chartEvents = useMemo(() => ({
    click: (p: any) => {
      if (p.dataType !== "node") return;
      const id = p.data?.id;
      if (id) {
        setSearchFocus(false); // 手动点节点退出搜索聚焦，回到普通高亮
        setFocusId(focusIdRef.current === id ? null : id);
      }
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
      reloadGraph();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const addEntity = async (values: any) => {
    try {
      await apiClient.post("/knowledge/bases/" + selectedKb + "/graph/entities", values);
      message.success(t.common.success);
      form.resetFields();
      reloadGraph();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const deleteEntity = async (id: string) => {
    try {
      await apiClient.delete("/knowledge/graph/entities/" + id);
      message.success(t.common.success);
      reloadGraph();
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
            <Button icon={<ReloadOutlined />} onClick={reloadGraph} loading={loading}>
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
      {/* 工具栏第 1 行：左=搜索，右=动作（抽取在前，其后是视图工具） */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 12,
      }}>
        <Space>
          <AutoComplete
            options={searchOptions}
            style={{ width: 320 }}
            placeholder={graphText.searchPh}
            filterOption={(input, option) =>
              (option?.value || "").toLowerCase().includes(input.toLowerCase())}
            onSelect={(value: string | undefined) => { if (value) focusByLabel(value); }}
            value={undefined}
          />
          {focusId && (
            <Button
              icon={<AimOutlined />}
              onClick={() => { setSearchFocus(false); setFocusId(null); }}
            >
              {graphText.overview}
            </Button>
          )}
        </Space>
        <Space>
          <ExtractionActions extraction={extraction} />
          <Button
            icon={<NodeIndexOutlined />}
            onClick={() => setPathOpen(true)}
            disabled={!selectedKb || graphData.nodes.length === 0}
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
        </Space>
      </div>
      {/* 工具栏第 2 行：两类抽取的状态——做过没有、产出多少、进行到哪 */}
      <div style={{ marginTop: 8, marginBottom: 12, minHeight: 28, display: "flex", alignItems: "center" }}>
        <ExtractionStatus extraction={extraction} />
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
        <div style={{ flex: 1, minWidth: 460 }}>
          <Card
            size="small"
            // 根节点设为纵向弹性盒：标题栏占固定高度，正文撑满剩余（正文再用
            // 绝对定位铺满，画布尺寸不依赖百分比高度的解析）
            style={{
              height: CANVAS_HEIGHT, minHeight: 520, overflow: "hidden",
              display: "flex", flexDirection: "column",
            }}
            styles={{ body: { position: "relative", flex: 1, minHeight: 0, padding: 0 } }}
            title={(
              // 图谱规模：与状态行标注的「实体 N · 关系 M」同一组数字
              <Text type="secondary" style={{ fontSize: 13, whiteSpace: "nowrap" }} data-testid="kg-graph-totals">
                {graphText.entitiesLabel}{" "}
                <Text strong style={{ fontSize: 14, fontVariantNumeric: "tabular-nums", color: isDark ? "#D8E2F0" : "#142A33" }}>
                  {graphTotals.entities.toLocaleString()}
                </Text>
                {" · "}
                {graphText.relationsLabel}{" "}
                <Text strong style={{ fontSize: 14, fontVariantNumeric: "tabular-nums", color: isDark ? "#D8E2F0" : "#142A33" }}>
                  {graphTotals.relations.toLocaleString()}
                </Text>
              </Text>
            )}
            extra={(
              <Space size={12}>
                <Text type="secondary" style={{ fontSize: 13, whiteSpace: "nowrap" }}>
                  {graphText.viewOf}{" "}
                  <Text strong style={{ fontSize: 14, fontVariantNumeric: "tabular-nums", color: isDark ? "#D8E2F0" : "#142A33" }}>
                    {view.nodes.length}
                  </Text>
                  {/* 采样时标出分母，避免「当前视图 100」被读成库里只有 100 个 */}
                  {view.nodes.length < graphData.nodes.length && (
                    <Text type="secondary"> / {graphData.nodes.length.toLocaleString()}</Text>
                  )}
                </Text>
                <Tooltip title={graphText.viewCapHelp}>
                  <Space size={6}>
                    <Text type="secondary" style={{ fontSize: 13, whiteSpace: "nowrap" }}>
                      {graphText.viewCap}
                    </Text>
                    <InputNumber
                      size="small"
                      min={10} step={50} value={viewSize}
                      onChange={(v) => setViewSize(Number(v) || 100)}
                      style={{ width: 80 }}
                    />
                  </Space>
                </Tooltip>
                <Tooltip title={graphText.resetView}>
                  <Button size="small" icon={<ScanOutlined />} onClick={resetView} />
                </Tooltip>
              </Space>
            )}
          >
            {view.nodes.length === 0 ? (
              <Empty
                description={loading ? t.common.loading : graphText.emptyKb}
                style={{ marginTop: 200 }}
              />
            ) : (
              <div style={{ position: "absolute", inset: 0 }}>
                <ReactECharts
                  // key 只随知识库变：换库重建图表（全新布局）。同库内的数据更新
                  // 走合并模式（notMerge=false）——力导向按节点 id 记住已有坐标，
                  // 已有节点保持原位，抽取期间新抽出的节点长进来，而不是每片
                  // 都整图重新模拟。「重置视图」会重建系列，从头布局。
                  key={selectedKb ?? "none"}
                  ref={chartRef}
                  option={option}
                  notMerge={false}
                  lazyUpdate
                  style={{ width: "100%", height: "100%" }}
                  onEvents={chartEvents}
                />
              </div>
            )}
          </Card>
        </div>
        <div style={{
          width: 320,
          height: CANVAS_HEIGHT,
          minHeight: 520,
        }}>
          <Tabs
            size="small"
            style={{ height: "100%" }}
            items={[
              {
                key: "edit",
                label: lang === "zh" ? "编辑" : "Edit",
                children: (
                  <div style={{ maxHeight: `calc(100vh - ${CANVAS_OFFSET + 60}px)`, overflowY: "auto" }}>
                    <Space direction="vertical" style={{ width: "100%" }} size={10}>
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
                    </Space>
                  </div>
                ),
              },
              {
                key: "entities",
                label: graphText.entityList,
                children: (
                  <Card size="small">
                    <List
                      size="small"
                      dataSource={view.nodes}
                      style={{ maxHeight: `calc(100vh - ${CANVAS_OFFSET + 90}px)`, overflowY: "auto" }}
                      locale={{ emptyText: <Empty description={t.common.loading} /> }}
                      renderItem={(node: GraphNode) => (
                        <List.Item
                          style={{ cursor: "pointer", background: node.id === focusId ? "#fff7e6" : undefined }}
                          onClick={() => { setSearchFocus(false); setFocusId(node.id === focusId ? null : node.id); }}
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
                ),
              },
              {
                key: "fusion",
                label: lang === "zh" ? "融合审核" : "Fusion review",
                children: selectedKb
                  ? <FusionPanel kbId={selectedKb} onChanged={reloadGraph} />
                  : <Empty description={t.knowledge.title} />,
              },
            ]}
          />
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
