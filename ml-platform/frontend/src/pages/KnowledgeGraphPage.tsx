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
    inLibrary: "库内实体", viewOf: "当前视图",
    // 抽取视图的工具条统计（与进度条数字同源）
    jobExtracted: "本次抽取", relationsLabel: "关系",
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
    jobExtracted: "This job", relationsLabel: "relations",
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
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] });
  // 抽取中的「本次抽取结果」子图：非空时画布改画它（与进度条的数字同源），
  // 任务结束或切回全图时清空
  const [jobGraph, setJobGraph] = useState<GraphData | null>(null);
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

  // 后端图载荷（全图 / 本次抽取子图共用形态）→ 画布数据模型
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

  const handleJobGraph = useCallback(
    (payload: unknown) => setJobGraph(payload ? toGraphData(payload as any) : null),
    [toGraphData],
  );

  const loadGraph = useCallback(() => {
    if (!selectedKb) return;
    // 请求序号守卫：大库的全图响应可能比后来发起的小库请求晚到（「开发计划」
    // 7,915 实体/66 万关系要数十秒）。过期的响应必须丢弃，否则会把当前选中库
    // 的图覆盖成别的库——实测选「点焊工艺」画布却显示「开发计划」（2026-11-23）
    const seq = ++loadSeqRef.current;
    setLoading(true);
    apiClient.get("/knowledge/bases/" + selectedKb + "/graph")
      .then((res) => {
        if (seq !== loadSeqRef.current) return;
        setGraphData(toGraphData(res.data));
        setFocusId(null);
      })
      .catch(() => { if (seq === loadSeqRef.current) message.error(t.common.error); })
      .finally(() => { if (seq === loadSeqRef.current) setLoading(false); });
  }, [selectedKb, t, toGraphData]);

  useEffect(() => {
    // 切库立即清掉上一个库的图与抽取视图（不残留成「下拉是 A、画布是 B」）；
    // 同库刷新（loadGraph 被 refresh/抽取/编辑触发）不走这里，画布不闪空
    setGraphData({ nodes: [], edges: [] });
    setJobGraph(null);
    loadGraph();
  }, [selectedKb]);

  // 画布数据源：抽取视图（本次抽取子图）优先，否则全图
  const canvasData = jobGraph ?? graphData;
  // 抽取视图节点少且都是刚抽出来的，放宽采样上限（尽量把本次结果画全）
  const viewCap = jobGraph ? Math.max(viewSize, 400) : viewSize;

  // 全库度数（Obsidian 以链接数决定节点大小，聚焦视图下仍按全库度数缩放）
  const degree = useMemo(() => {
    const d = new Map<string, number>();
    for (const e of canvasData.edges) {
      d.set(e.source, (d.get(e.source) || 0) + 1);
      d.set(e.target, (d.get(e.target) || 0) + 1);
    }
    return d;
  }, [canvasData.edges]);

  // 视图模型：枢纽-卫星采样（Obsidian 观感的关键）——按度数取少量枢纽作骨架，
  // 再按边权重挂上低连接叶子实体，得到「少数大点 + 大量小点」的放射状结构；
  // 全量渲染 5 千实体时 echarts O(n²) 力导向不可行，故按 viewSize 采样。
  const view = useMemo((): GraphData => {
    const all = canvasData.nodes;
    if (all.length === 0) return canvasData;
    // 搜索聚焦模式（用户期望：搜索后只显示目标节点及其直接相连节点，
    // Obsidian 式聚焦视图；其余节点隐藏）。点击节点/返回总览退出该模式。
    if (searchFocus && focusId) {
      const keep = new Set<string>([focusId]);
      for (const e of canvasData.edges) {
        if (e.source === focusId) keep.add(e.target);
        if (e.target === focusId) keep.add(e.source);
      }
      const nodes = all.filter((n) => keep.has(n.id));
      const edges = canvasData.edges.filter(
        (e) => keep.has(e.source) && keep.has(e.target),
      );
      return { nodes, edges };
    }
    if (all.length <= viewCap) return canvasData;

    const ranked = [...all].sort(
      (a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0)
        || (b.freq || 0) - (a.freq || 0),
    );
    const hubCount = Math.min(80, Math.max(12, Math.round(viewCap * 0.2)));
    const hubIds = new Set(ranked.slice(0, hubCount).map((n) => n.id));
    const keep = new Set(hubIds);
    const edges: GraphEdge[] = [];
    const sortedEdges = [...canvasData.edges].sort((a, b) => (b.weight || 0) - (a.weight || 0));
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
      const weakEdges = [...canvasData.edges].sort((a, b) => (a.weight || 0) - (b.weight || 0));
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
      for (const e of canvasData.edges) {
        if (e.source === focusId) keep.add(e.target);
        if (e.target === focusId) keep.add(e.source);
      }
    }
    const nodes = all.filter((n) => keep.has(n.id));
    return {
      nodes,
      edges: edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    };
  }, [canvasData, focusId, viewCap, degree, searchFocus]);

  // 分组维度：type 优先（≥2 种类型时按类型分色），否则退回 auto/manual 来源
  const grouping = useMemo(() => {
    const nodes = canvasData.nodes;
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
  }, [canvasData.nodes, graphText, lang]);

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
    () => canvasData.nodes.map((n) => ({ value: n.label, id: n.id })),
    [canvasData.nodes],
  );

  const focusByLabel = (label: string) => {
    const node = canvasData.nodes.find((n) => n.label === label);
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
    // 抽取视图节点少且都是刚抽出来的：全部显示名称（受「隐藏文字」开关约束），
    // 不按大小隐藏
    const showAllLabels = !!jobGraph;
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
  }, [view, grouping, degree, groupIndexOf, groupColorOf, isDark, graphText, labelsVisible, !!jobGraph]);

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
        label: { show: labelsVisible && (isTarget || !!jobGraph || size >= 10) },
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
            <Button
              icon={<AimOutlined />}
              onClick={() => { setSearchFocus(false); setFocusId(null); }}
            >
              {graphText.overview}
            </Button>
          )}
        </Space>
        <Space size={16}>
          <ExtractionControl kbId={selectedKb} onExtracted={loadGraph} onJobGraph={handleJobGraph} />
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
            {/* 抽取视图：「本次抽取 N · 关系 M」与进度条数字同源；平时显示库内实体数 */}
            {jobGraph ? graphText.jobExtracted : graphText.inLibrary}{" "}
            <Text strong style={{ fontSize: 16, fontVariantNumeric: "tabular-nums", color: isDark ? "#D8E2F0" : "#142A33" }}>
              {canvasData.nodes.length.toLocaleString()}
            </Text>
            {jobGraph && (
              <>
                {" · "}
                {graphText.relationsLabel}{" "}
                <Text strong style={{ fontSize: 16, fontVariantNumeric: "tabular-nums", color: isDark ? "#D8E2F0" : "#142A33" }}>
                  {jobGraph.edges.length}
                </Text>
              </>
            )}
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
                  // key 随「全图 / 本次抽取」视图切换：切换时重建图表（全新布局）；
                  // 抽取视图内的数据更新走合并模式（notMerge=false）——已有节点
                  // 保持原位、新抽出的节点长进来，而不是每片都整图重新模拟
                  key={`${selectedKb ?? "none"}:${jobGraph ? "job" : "full"}`}
                  ref={chartRef}
                  option={option}
                  notMerge={!jobGraph}
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
        }}>
          <Tabs
            size="small"
            style={{ height: "100%" }}
            items={[
              {
                key: "edit",
                label: lang === "zh" ? "编辑" : "Edit",
                children: (
                  <div style={{ maxHeight: "calc(100vh - 290px)", overflowY: "auto" }}>
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
                      style={{ maxHeight: "calc(100vh - 320px)", overflowY: "auto" }}
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
                  ? <FusionPanel kbId={selectedKb} onChanged={loadGraph} />
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
