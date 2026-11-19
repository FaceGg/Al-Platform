import { useEffect, useState, useRef, useCallback, useMemo } from "react";
import {
  Select, Button, Form, Input, List, Typography, message, Card, Space, Tag, Empty,
  AutoComplete, Statistic, InputNumber, Tooltip, Segmented,
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
  docCount?: number; docIds?: string[];
}
interface GraphEdge {
  source: string; target: string; label?: string; type?: string; weight?: number;
}
interface GraphData {
  nodes: GraphNode[]; edges: GraphEdge[];
}
interface DocItem {
  id: string; filename: string; doc_type?: string; chunk_count?: number;
}

// 总览时的边预算：全量共现边会糊成一片并拖慢渲染
const MAX_VIEW_EDGES = 2500;

// Obsidian 风格柔和分组色板：type 优先分色，来源兜底，按序轮转
const GROUP_PALETTE = [
  "#8a7dff", "#4ec9b0", "#f7c65d", "#e06c9f", "#61afef",
  "#98c379", "#ff9f6a", "#6bcfff", "#d19cf5", "#e8a0a0",
];

// 占比最高的类型用中性色（Obsidian 默认是中性灰点，彩色只用于少数分组）
const NEUTRAL_NODE_COLOR = "#7f8b9e";

// 实体类型显示名：抽取层 type 是英文标识，中文界面翻译显示；未知类型显示原值
const TYPE_DISPLAY_ZH: Record<string, string> = {
  concept: "概念", term: "术语", person: "人物", location: "地点",
  organization: "机构", standard: "标准", material: "材料", equipment: "设备",
  process: "工艺", disease: "疾病", indicator: "指标", unit: "单位",
};

function typeDisplayName(type: string, lang: string): string {
  if (lang !== "zh") return type;
  return TYPE_DISPLAY_ZH[type] ?? type;
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
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
    searchPh: "搜索实体，定位到其所属文档",
    overview: "返回总览",
    inLibrary: "库内实体", viewOf: "当前视图",
    neighborhood: "邻域",
    expandHint: "点击实体高亮其邻域 · 滚轮缩放 / 拖动平移 / 拖拽节点",
    resetView: "重置视图",
    degreeLabel: "度数",
    modeRadial: "放射关系图", modeEntity: "实体图谱",
    centerDoc: "中心文档", innerCount: "内圈", outerCount: "外圈",
    centerDocEmpty: "该文档未抽取到实体",
    relatedDocs: "相关文档", centerEntities: "文档实体",
    sharedEntities: (n: number) => `共享实体 ${n} 个`,
    docType: "文档类型", chunks: (n: number) => `${n} 个分块`,
    pickEntity: "点击实体高亮其与中心文档的关系",
    noDocs: "该知识库还没有文档",
  } : {
    extract: "Auto extract", extracting: "Extracting...",
    extractDone: (e: number, r: number) => `Extracted: ${e} entities, ${r} relations`,
    extractEmpty: "Extracted nothing above threshold (check document content or lower the frequency threshold)",
    extractFailed: "Auto extraction failed",
    auto: "Auto", manual: "Manual", docCount: (n: number) => `${n} source doc(s)`,
    searchPh: "Search an entity to locate its document",
    overview: "Back to overview",
    inLibrary: "In library", viewOf: "View",
    neighborhood: "Neighborhood",
    expandHint: "Click an entity to highlight its links · scroll to zoom / drag to pan",
    resetView: "Reset view",
    degreeLabel: "Links",
    modeRadial: "Radial map", modeEntity: "Entity graph",
    centerDoc: "Center document", innerCount: "Inner", outerCount: "Outer",
    centerDocEmpty: "No entity extracted from this document",
    relatedDocs: "Related documents", centerEntities: "Document entities",
    sharedEntities: (n: number) => `${n} shared entities`,
    docType: "Type", chunks: (n: number) => `${n} chunks`,
    pickEntity: "Click an entity to highlight its link to the center",
    noDocs: "This knowledge base has no document yet",
  };
  const chartRef = useRef<any>(null);
  const mapRef = useRef<HTMLDivElement>(null);
  const focusIdRef = useRef<string | null>(null);
  const [bases, setBases] = useState<any[]>([]);
  const [selectedKb, setSelectedKb] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] });
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [centerDocId, setCenterDocId] = useState<string | null>(null);
  const [mode, setMode] = useState<"radial" | "entity">("radial");
  const [innerCount, setInnerCount] = useState(14);
  const [outerCount, setOuterCount] = useState(10);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [hoverInfo, setHoverInfo] = useState<{ x: number; y: number; lines: string[] } | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [viewSize, setViewSize] = useState(400);
  const [mapSize, setMapSize] = useState({ w: 900, h: 560 });
  const [form] = Form.useForm();
  const [edgeForm] = Form.useForm();
  focusIdRef.current = focusId;

  useEffect(() => {
    apiClient.get("/knowledge/bases").then((res) => {
      setBases(res.data.items || res.data || []);
    }).catch(() => {});
  }, []);

  const loadDocs = useCallback((kbId: string) => {
    apiClient.get("/knowledge/bases/" + kbId + "/documents").then((res) => {
      const items = (res.data?.items || res.data || []) as DocItem[];
      setDocs(items);
    }).catch(() => setDocs([]));
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
          docIds: Array.isArray(n.properties?.doc_ids) ? n.properties.doc_ids : [],
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
        setHighlightId(null);
      })
      .catch(() => message.error(t.common.error))
      .finally(() => setLoading(false));
  }, [selectedKb, t]);

  useEffect(() => { loadGraph(); }, [selectedKb]);
  useEffect(() => { if (selectedKb) loadDocs(selectedKb); }, [selectedKb, loadDocs]);

  // 容器尺寸测量：放射图按像素排布，标签字号不随视口缩放
  useEffect(() => {
    const el = mapRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0].contentRect;
      setMapSize({ w: Math.max(320, rect.width), h: Math.max(320, rect.height) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [mode, selectedKb]);

  // 全库度数（节点大小按连接数，聚焦视图下仍按全库度数缩放）
  const degree = useMemo(() => {
    const d = new Map<string, number>();
    for (const e of graphData.edges) {
      d.set(e.source, (d.get(e.source) || 0) + 1);
      d.set(e.target, (d.get(e.target) || 0) + 1);
    }
    return d;
  }, [graphData.edges]);

  // 每个文档的实体数（用于挑选默认中心文档）
  const docEntityCount = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of graphData.nodes) {
      for (const d of n.docIds || []) counts.set(d, (counts.get(d) || 0) + 1);
    }
    return counts;
  }, [graphData.nodes]);

  // 放射图模型：中心文档 + 内圈实体（该文档抽出的实体）+ 外圈相关文档（共享实体最多的）
  const radial = useMemo(() => {
    if (docs.length === 0 || graphData.nodes.length === 0) return null;
    let center = docs.find((d) => d.id === centerDocId);
    if (!center) {
      const best = [...docs].sort((a, b) => (docEntityCount.get(b.id) || 0) - (docEntityCount.get(a.id) || 0))[0];
      center = best;
    }
    if (!center) return null;
    const inner = graphData.nodes
      .filter((n) => (n.docIds || []).includes(center!.id))
      .sort((a, b) => (b.freq || 0) - (a.freq || 0) || (degree.get(b.id) || 0) - (degree.get(a.id) || 0))
      .slice(0, innerCount);
    const shared = new Map<string, number>();
    for (const n of graphData.nodes) {
      if (!(n.docIds || []).includes(center!.id)) continue;
      for (const d of n.docIds || []) {
        if (d === center!.id) continue;
        shared.set(d, (shared.get(d) || 0) + 1);
      }
    }
    const outer = docs
      .filter((d) => d.id !== center!.id)
      .map((d) => ({ doc: d, shared: shared.get(d.id) || 0 }))
      .filter((x) => x.shared > 0)
      .sort((a, b) => b.shared - a.shared)
      .slice(0, outerCount);

    const { w, h } = mapSize;
    const cx = w / 2;
    const cy = h / 2;
    const base = Math.min(w, h);
    const r1 = base * 0.33;
    const r2 = base * 0.5;
    const place = (count: number, radius: number, offset: number) => Array.from({ length: count }, (_, i) => {
      const angle = -Math.PI / 2 + (offset + i) * (2 * Math.PI / Math.max(count, 1));
      return { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius, angle };
    });
    const innerPos = place(inner.length, r1, 0);
    const outerPos = place(outer.length, r2, 0.5);
    return {
      center,
      inner: inner.map((node, i) => ({ node, ...innerPos[i] })),
      outer: outer.map((item, i) => ({ ...item, ...outerPos[i] })),
      cx,
      cy,
    };
  }, [docs, graphData.nodes, centerDocId, innerCount, outerCount, degree, docEntityCount, mapSize]);

  // 实体图谱视图模型：枢纽-卫星采样（少数大点 + 大量小点）
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
    return { nodes, edges: edges.filter((e) => keep.has(e.source) && keep.has(e.target)) };
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
    if (!node) return;
    setHighlightId(node.id);
    // 定位到该实体所属文档作为中心
    const docId = (node.docIds || [])[0];
    if (docId) setCenterDocId(docId);
    setMode("radial");
  };

  const option = useMemo(() => {
    const nodeCount = view.nodes.length;
    if (nodeCount === 0) return {};

    // —— 均匀云团 + 尺寸两极化（用户终版 2026-11-19：没有特殊中心节点——
    // 重要节点是大圆、其余是小圆，全域均匀随机散布，无环无中心）——
    const maxDeg = Math.max(1, ...view.nodes.map((n) => degree.get(n.id) || 0));
    const hubCut = maxDeg * 0.12;

    const hash01 = (id: string, salt: number) => {
      let h = (salt * 0x9e3779b9) & 0x7fffffff;
      for (const ch of id) h = (Math.imul(h ^ ch.charCodeAt(0), 0x85ebca6b) ^ (h >>> 7)) & 0x7fffffff;
      h ^= h >>> 13;
      h = Math.imul(h, 0xc2b2ae35) & 0x7fffffff;
      return (h >>> 8) / 0x7fffff;
    };
    // graph layout:"none" 的 x/y 是像素坐标——归一化 0-1 曾致全节点挤在
    // 左上原点（画布空白/中心黑团）。按窗口估算图区尺寸后转像素。
    const VW = Math.max(420, window.innerWidth * 0.55);
    const VH = 620;
    const RR = Math.min(VW, VH) * 0.42;
    const posMap = new Map<string, [number, number]>();
    // 圆盘均匀撒点（sqrt 面密度）：全域随机，无环无中心
    view.nodes.forEach((n) => {
      const r = RR * Math.sqrt(hash01(n.id, 1));
      const a = hash01(n.id, 7) * Math.PI * 2;
      posMap.set(n.id, [VW / 2 + r * Math.cos(a), VH / 2 + r * Math.sin(a)]);
    });

    const nodes = view.nodes.map((n) => {
      const deg = degree.get(n.id) || 0;
      const isHub = deg >= hubCut;
      const size = isHub
        ? 14 + Math.min(14, ((deg - hubCut) / Math.max(1, maxDeg - hubCut)) * 16)
        : 5.5;
      return {
        id: n.id,
        name: n.label,
        category: groupIndexOf(n),
        x: (posMap.get(n.id) ?? [0.5, 0.5])[0],
        y: (posMap.get(n.id) ?? [0.5, 0.5])[1],
        symbolSize: size,
        label: { show: isHub, fontSize: isHub ? 12 : 10 },
        itemStyle: {
          color: isHub ? (isDark ? "#9AA8BF" : "#4a4a4a") : (isDark ? "#5A6B84" : "#9a9a9a"),
          opacity: isHub ? 0.9 : 0.6,
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
          if (group) lines.push(`<span style="color:${group.color}">●</span> ${escapeHtml(group.name)}`);
          lines.push(raw.source === "auto" ? graphText.auto : graphText.manual);
          lines.push(`${graphText.degreeLabel}: ${degree.get(raw.id) || 0}`);
          if (raw.docCount) lines.push(graphText.docCount(raw.docCount));
          return lines.join("<br/>");
        },
      },
      legend: undefined,
      series: [{
        type: "graph",
        layout: "none",
        roam: true,
        draggable: true,
        categories: grouping?.items.map((g) => ({ name: g.name })) || [],
        data: nodes,
        links,
        lineStyle: {
          color: isDark ? "rgba(216,226,240,0.14)" : "rgba(20,42,51,0.16)",
          width: 0.8,
          curveness: 0,
        },
        label: {
          show: true,
          position: "right",
          distance: 4,
          color: isDark ? "#8FA8C4" : "#57707B",
          fontSize: 11,
        },
        labelLayout: { hideOverlap: true },
        edgeLabel: { show: false },
        emphasis: {
          focus: "adjacency",
          label: { show: true, fontWeight: "bold" },
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

  const chartEvents = useMemo(() => ({
    click: (p: any) => {
      if (p.dataType !== "node") return;
      const id = p.data?.id;
      if (id) setFocusId(focusIdRef.current === id ? null : id);
    },
  }), []);

  useEffect(() => {
    const inst = chartRef.current?.getEchartsInstance?.();
    if (!inst) return;
    inst.dispatchAction({ type: "downplay", seriesIndex: 0 });
    if (focusId) {
      const idx = view.nodes.findIndex((n) => n.id === focusId);
      if (idx >= 0) inst.dispatchAction({ type: "highlight", seriesIndex: 0, dataIndex: idx });
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

  // 放射图配色：中心深色、内圈浅灰、外圈更浅，射线极淡
  const radialColors = {
    center: isDark ? "#e8ecf3" : "#3d434d",
    inner: isDark ? "#7d8590" : "#c3c8d0",
    outer: isDark ? "#5e656f" : "#d7dbe2",
    label: isDark ? "#c9d2e0" : "#2b3038",
    labelSoft: isDark ? "#8b94a3" : "#5d646f",
    spoke: isDark ? "rgba(216,226,240,0.16)" : "rgba(20,42,51,0.13)",
    spokeOuter: isDark ? "rgba(216,226,240,0.10)" : "rgba(20,42,51,0.08)",
    halo: isDark ? "#16223a" : "#ffffff",
  };

  const radialLabelAnchor = (x: number, cx: number): "start" | "end" | "middle" => {
    const dx = x - cx;
    if (dx > 12) return "start";
    if (dx < -12) return "end";
    return "middle";
  };

  // 标签按可用宽度裁剪，避免超出画布被裁切
  const fitText = (text: string, x: number, cx: number, fontPx: number) => {
    const anchor = radialLabelAnchor(x, cx);
    const available = anchor === "start"
      ? mapSize.w - x - 8
      : anchor === "end"
        ? x - 8
        : mapSize.w;
    if (available <= 44) return truncate(text, 6);
    let width = 0;
    let out = "";
    for (const ch of text) {
      const charWidth = /[\u4e00-\u9fa5]/.test(ch) ? fontPx : fontPx * 0.55;
      if (width + charWidth > available) break;
      width += charWidth;
      out += ch;
    }
    return out.length < text.length ? `${out}…` : out;
  };

  const renderRadial = () => {
    if (!radial) {
      return <Empty description={docs.length ? graphText.centerDocEmpty : graphText.noDocs} style={{ marginTop: 180 }} />;
    }
    const { center, inner, outer, cx, cy } = radial;
    return (
      <div ref={mapRef} style={{ position: "relative", width: "100%", height: "100%" }}>
        <svg width="100%" height="100%" viewBox={`0 0 ${mapSize.w} ${mapSize.h}`} style={{ display: "block" }}>
          {/* 射线：中心 → 外圈（虚线、更淡） */}
          {outer.map((item) => (
            <line
              key={`outer-line-${item.doc.id}`}
              x1={cx} y1={cy} x2={item.x} y2={item.y}
              stroke={radialColors.spokeOuter} strokeWidth={1} strokeDasharray="3 4"
            />
          ))}
          {/* 射线：中心 → 内圈实体 */}
          {inner.map((item) => (
            <line
              key={`inner-line-${item.node.id}`}
              x1={cx} y1={cy} x2={item.x} y2={item.y}
              stroke={radialColors.spoke} strokeWidth={1}
            />
          ))}
          {/* 中心节点 */}
          <circle cx={cx} cy={cy} r={11} fill={radialColors.center} />
          <text
            x={cx} y={cy + 27} textAnchor="middle"
            fill={radialColors.label} fontSize={13.5} fontWeight={600}
            stroke={radialColors.halo} strokeWidth={3} paintOrder="stroke" strokeLinejoin="round"
          >
            {fitText(center.filename, cx, cx, 13.5)}
          </text>
          {/* 内圈实体 */}
          {inner.map((item) => {
            const active = highlightId === item.node.id;
            return (
              <g
                key={`inner-${item.node.id}`}
                onMouseEnter={(e) => {
                  setHoverKey(item.node.id);
                  setHoverInfo({
                    x: e.clientX, y: e.clientY,
                    lines: [
                      item.node.label,
                      typeDisplayName(item.node.type || "entity", lang),
                      item.node.source === "auto" ? graphText.auto : graphText.manual,
                      `${graphText.degreeLabel}: ${degree.get(item.node.id) || 0}`,
                    ],
                  });
                }}
                onMouseMove={(e) => setHoverInfo((prev) => (prev ? { ...prev, x: e.clientX, y: e.clientY } : prev))}
                onMouseLeave={() => { setHoverKey(null); setHoverInfo(null); }}
                onClick={() => setHighlightId(active ? null : item.node.id)}
                style={{ cursor: "pointer" }}
              >
                <circle
                  cx={item.x} cy={item.y} r={active ? 6 : 4.5}
                  fill={active ? radialColors.center : radialColors.inner}
                />
                <text
                  x={item.x + (radialLabelAnchor(item.x, cx) === "end" ? -8 : radialLabelAnchor(item.x, cx) === "start" ? 8 : 0)}
                  y={item.y + 4}
                  textAnchor={radialLabelAnchor(item.x, cx)}
                  fill={active ? radialColors.label : radialColors.labelSoft}
                  fontSize={12.5}
                  fontWeight={active || hoverKey === item.node.id ? 600 : 400}
                  stroke={radialColors.halo} strokeWidth={3} paintOrder="stroke" strokeLinejoin="round"
                >
                  {fitText(item.node.label, item.x, cx, 12.5)}
                </text>
              </g>
            );
          })}
          {/* 外圈相关文档 */}
          {outer.map((item) => (
            <g
              key={`outer-${item.doc.id}`}
              onMouseEnter={(e) => {
                setHoverKey(item.doc.id);
                setHoverInfo({
                  x: e.clientX, y: e.clientY,
                  lines: [
                    item.doc.filename,
                    graphText.docType + ": " + (item.doc.doc_type || "-"),
                    graphText.sharedEntities(item.shared),
                  ],
                });
              }}
              onMouseMove={(e) => setHoverInfo((prev) => (prev ? { ...prev, x: e.clientX, y: e.clientY } : prev))}
              onMouseLeave={() => { setHoverKey(null); setHoverInfo(null); }}
              onClick={() => setCenterDocId(item.doc.id)}
              style={{ cursor: "pointer" }}
            >
              <circle cx={item.x} cy={item.y} r={4} fill={radialColors.outer} />
              <text
                x={item.x + (radialLabelAnchor(item.x, cx) === "end" ? -7 : radialLabelAnchor(item.x, cx) === "start" ? 7 : 0)}
                y={item.y + 4}
                textAnchor={radialLabelAnchor(item.x, cx)}
                fill={radialColors.labelSoft}
                fontSize={11.5}
                fontWeight={hoverKey === item.doc.id ? 600 : 400}
                stroke={radialColors.halo} strokeWidth={3} paintOrder="stroke" strokeLinejoin="round"
              >
                {fitText(item.doc.filename, item.x, cx, 11.5)}
              </text>
            </g>
          ))}
        </svg>
        {hoverInfo && (
          <div
            style={{
              position: "fixed", left: hoverInfo.x + 14, top: hoverInfo.y + 10,
              background: isDark ? "#16223a" : "#ffffff",
              border: `1px solid ${isDark ? "#24344f" : "#d9d9d9"}`,
              borderRadius: 6, padding: "6px 10px", pointerEvents: "none",
              boxShadow: "0 2px 8px rgba(0,0,0,0.15)", zIndex: 20, whiteSpace: "nowrap",
            }}
          >
            {hoverInfo.lines.map((line, i) => (
              <div
                key={i}
                style={{
                  fontSize: i === 0 ? 13 : 12,
                  fontWeight: i === 0 ? 600 : 400,
                  color: i === 0
                    ? (isDark ? "#D8E2F0" : "#142A33")
                    : (isDark ? "#8FA8C4" : "#57707B"),
                }}
              >
                {line}
              </div>
            ))}
          </div>
        )}
      </div>
    );
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
              onChange={(v) => { setSelectedKb(v); setFocusId(null); setHighlightId(null); }}
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
          <Segmented
            value={mode}
            onChange={(v) => setMode(v as "radial" | "entity")}
            options={[
              { label: graphText.modeRadial, value: "radial" },
              { label: graphText.modeEntity, value: "entity" },
            ]}
          />
          {mode === "radial" && (
            <>
              <Select
                placeholder={graphText.centerDoc}
                style={{ width: 260 }}
                value={radial?.center.id}
                onChange={(v) => setCenterDocId(v)}
                options={docs.map((d) => ({ value: d.id, label: d.filename }))}
                showSearch
                optionFilterProp="label"
              />
              <InputNumber
                min={4} max={40} step={2} value={innerCount}
                onChange={(v) => setInnerCount(Number(v) || 14)}
                style={{ width: 78 }}
                addonBefore={graphText.innerCount}
              />
              <InputNumber
                min={2} max={30} step={2} value={outerCount}
                onChange={(v) => setOuterCount(Number(v) || 10)}
                style={{ width: 78 }}
                addonBefore={graphText.outerCount}
              />
            </>
          )}
          {mode === "entity" && (
            <>
              <AutoComplete
                options={searchOptions}
                style={{ width: 240 }}
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
              <InputNumber
                min={10} step={50} value={viewSize}
                onChange={(v) => setViewSize(Number(v) || 400)}
                style={{ width: 90 }}
              />
            </>
          )}
          <Statistic title={graphText.inLibrary} value={graphData.nodes.length} style={{ margin: 0 }} />
          <Statistic title={t.knowledge.title} value={docs.length} style={{ margin: 0 }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {mode === "radial" ? graphText.pickEntity : graphText.expandHint}
          </Text>
        </Space>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
        <div style={{ flex: 1, minWidth: 460 }}>
          <Card
            style={{ height: 560, padding: 0, overflow: "hidden" }}
            styles={{ body: { height: "100%", padding: 0 } }}
          >
            {mode === "radial" ? (
              renderRadial()
            ) : view.nodes.length === 0 && !loading ? (
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
          {mode === "radial" && radial && (
            <>
              <Card size="small" title={graphText.centerDoc}>
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  <Text strong style={{ wordBreak: "break-all" }}>{radial.center.filename}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {graphText.docType}: {radial.center.doc_type || "-"} · {graphText.chunks(radial.center.chunk_count || 0)}
                  </Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {graphText.centerEntities}: {radial.inner.length}
                  </Text>
                </Space>
              </Card>
              <Card size="small" title={graphText.relatedDocs}>
                <List
                  size="small"
                  dataSource={radial.outer}
                  locale={{ emptyText: <Empty description={graphText.noDocs} /> }}
                  renderItem={(item) => (
                    <List.Item
                      style={{ cursor: "pointer" }}
                      onClick={() => setCenterDocId(item.doc.id)}
                    >
                      <Text style={{ fontSize: 12 }}>{truncate(item.doc.filename, 26)}</Text>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {graphText.sharedEntities(item.shared)}
                      </Text>
                    </List.Item>
                  )}
                />
              </Card>
              <Card size="small" title={graphText.centerEntities}>
                <List
                  size="small"
                  dataSource={radial.inner}
                  style={{ maxHeight: 220, overflowY: "auto" }}
                  locale={{ emptyText: <Empty description={graphText.centerDocEmpty} /> }}
                  renderItem={(item) => (
                    <List.Item
                      style={{ cursor: "pointer", background: highlightId === item.node.id ? "#fff7e6" : undefined }}
                      onClick={() => setHighlightId(highlightId === item.node.id ? null : item.node.id)}
                    >
                      <Tag style={{ marginInlineEnd: 0 }}>{typeDisplayName(item.node.type || "entity", lang)}</Tag>
                      <Text style={{ fontSize: 12 }}>{item.node.label}</Text>
                    </List.Item>
                  )}
                />
              </Card>
            </>
          )}
          {mode === "entity" && (
            <Card size="small" title={t.knowledge.entity + " " + t.nav.data}>
              <List
                size="small"
                dataSource={view.nodes}
                style={{ maxHeight: 300, overflowY: "auto" }}
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
                    </Space>
                  </List.Item>
                )}
              />
            </Card>
          )}
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
        </div>
      </div>
    </AppLayout>
  );
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
