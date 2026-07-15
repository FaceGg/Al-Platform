import { memo } from "react";
import { Handle, Position, NodeProps } from "reactflow";
import { Progress, Tag, Tooltip } from "antd";
import {
  LoadingOutlined, CheckCircleFilled, CloseCircleFilled, PlayCircleOutlined,
} from "@ant-design/icons";
import { useWorkflowStore } from "../../stores/workflowStore";
import { useI18n } from "../../i18n";

const STATUS_CFG: Record<string, {
  bg: string; border: string; icon: React.ReactNode; tagColor: string;
}> = {
  pending:  { bg: "#fff7e6", border: "#fa8c16", icon: <PlayCircleOutlined style={{ color: "#fa8c16" }} />, tagColor: "orange" },
  running:  { bg: "#e6f7ff", border: "#1890ff", icon: <LoadingOutlined style={{ color: "#1890ff" }} spin />, tagColor: "processing" },
  completed:{ bg: "#f6ffed", border: "#52c41a", icon: <CheckCircleFilled style={{ color: "#52c41a" }} />, tagColor: "success" },
  failed:   { bg: "#fff2f0", border: "#ff4d4f", icon: <CloseCircleFilled style={{ color: "#ff4d4f" }} />, tagColor: "error" },
  timed_out:{ bg: "#fff2f0", border: "#cf1322", icon: <CloseCircleFilled style={{ color: "#cf1322" }} />, tagColor: "error" },
  cancelled:{ bg: "#fffbe6", border: "#d48806", icon: <CloseCircleFilled style={{ color: "#d48806" }} />, tagColor: "warning" },
  skipped:  { bg: "#fafafa", border: "#8c8c8c", icon: <PlayCircleOutlined style={{ color: "#8c8c8c" }} />, tagColor: "default" },
};

function buildPortPreview(
  nodeId: string,
  portName: string,
  portDirection: "in" | "out",
  nodes: any[],
  edges: any[],
  nodeResults: Record<string, any>,
  lang: "zh" | "en"
): string {
  if (portDirection === "in") {
    // For input ports: show data from the connected upstream source port
    const incEdge = edges.find(e => e.target === nodeId && (e.targetHandle === portName || e.targetHandle === "in-0"));
    if (incEdge && nodeResults[incEdge.source]) {
      const upstream = nodeResults[incEdge.source];
      return formatResult(upstream, lang);
    }
  } else {
    // For output ports: show this node's result
    if (nodeResults[nodeId]) {
      return formatResult(nodeResults[nodeId], lang);
    }
  }
  return "";
}

export function formatResult(result: any, lang: "zh" | "en"): string {
  const noData = lang === "zh" ? "暂无数据" : "No data available";
  if (!result) return noData;
  try {
    // If result has data array
    if (Array.isArray(result) && result.length > 0) {
      const row = result[0];
      const keys = typeof row === "object" ? Object.keys(row) : [];
      const dimensions = lang === "zh"
        ? `${keys.length} 列 × ${result.length} 行`
        : `${keys.length} cols × ${result.length} rows`;
      return dimensions + "\n" +
        keys.slice(0, 8).join(", ") + (keys.length > 8 ? " ..." : "");
    }
    if (result && typeof result === "object") {
      const keys = Object.keys(result);
      // If contains data array
      if (result.data && Array.isArray(result.data)) {
        return formatResult(result.data, lang);
      }
      if (result.metrics) {
        return (lang === "zh" ? "指标: " : "Metrics: ") + JSON.stringify(result.metrics, null, 1).slice(0, 200);
      }
      if (result.chart) return lang === "zh" ? "图表（图片）" : "Chart (image)";
      return keys.slice(0, 6).join(", ") + (keys.length > 6 ? " ..." : "");
    }
    return String(result).slice(0, 200);
  } catch {
    return String(result).slice(0, 200);
  }
}

function CustomNode({ data, selected }: NodeProps) {
  const { lang } = useI18n();
  const status = (data.status as string) || "pending";
  const cfg = STATUS_CFG[status] || STATUS_CFG.pending;
  const progress = (data.progress as number) ?? undefined;

  const opId = data.operatorId as string || "";
  const label = (data.label as string) || opId;
  const nodeId = data.nodeId as string || "";

  const inputs = Array.isArray(data.inputs) ? data.inputs : [];
  const outputs = Array.isArray(data.outputs) ? data.outputs : [];

  // Get node results and edges from store for port preview
  const nodeResults = useWorkflowStore((s) => s.nodeResults);
  const allEdges = useWorkflowStore((s) => s.edges);
  const allNodes = useWorkflowStore((s) => s.nodes);

  const portStyle = (index: number, total: number): React.CSSProperties => ({
    width: 14,
    height: 14,
    background: cfg.border,
    border: "3px solid #fff",
    top: total <= 1 ? "50%" : ((index + 0.5) / total) * 100 + "%",
  });

  return (
    <div
      style={{
        padding: "6px 16px 8px",
        borderRadius: 10,
        border: "2px solid " + (selected ? "#1890ff" : cfg.border),
        background: cfg.bg,
        minWidth: 150,
        maxWidth: 220,
        boxShadow: selected ? "0 0 0 2px rgba(24,144,255,0.3)" : "0 1px 4px rgba(0,0,0,0.1)",
        fontSize: 13,
        transition: "all 0.2s ease",
      }}
    >
      {inputs.map((p: any, i: number) => {
        const preview = buildPortPreview(nodeId, p.name, "in", allNodes, allEdges, nodeResults, lang);
        const portLabel = (p.label || p.name) + (p.type ? " (" + p.type + ")" : "");
        const tooltipContent = (
          <div style={{ fontSize: 12, lineHeight: 1.6 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{portLabel}</div>
            {preview ? (
              <div style={{
                background: "rgba(255,255,255,0.08)", padding: "4px 8px",
                borderRadius: 4, fontFamily: "monospace", fontSize: 11,
                whiteSpace: "pre-wrap", maxWidth: 280,
              }}>
                {preview}
              </div>
            ) : (
              <div style={{ color: "rgba(255,255,255,0.45)", fontStyle: "italic" }}>
                {lang === "zh" ? "暂无数据" : "No data available"}
              </div>
            )}
          </div>
        );
        return (
          <Tooltip title={tooltipContent} color="#1a1a2e" placement="left" mouseEnterDelay={0.3} key={"tt-in-" + p.name}>
            <Handle
              type="target"
              position={Position.Left}
              id={p.name}
              style={portStyle(i, inputs.length)}
            />
          </Tooltip>
        );
      })}

      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span style={{ fontSize: 14 }}>{cfg.icon}</span>
        <span style={{
          fontWeight: 600, flex: 1, overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {label}
        </span>
      </div>

      <Tag color={cfg.tagColor} style={{ fontSize: 10, lineHeight: "14px", marginBottom: 4 }}>
        {status === "completed" ? "\u5df2\u5b8c\u6210" :
         status === "running" ? "\u8fd0\u884c\u4e2d" :
         status === "failed" ? "\u5931\u8d25" :
         status === "timed_out" ? "\u5df2\u8d85\u65f6" :
         status === "cancelled" ? "\u5df2\u53d6\u6d88" :
         status === "skipped" ? "\u5df2\u8df3\u8fc7" : "\u5f85\u8fd0\u884c"}
      </Tag>

      {status === "failed" && (data as any).error && (
        <Tooltip title={String((data as any).error)}>
          <div style={{
            fontSize: 9, color: "#ff4d4f", marginTop: -2, marginBottom: 4,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            maxWidth: 180,
          }}>
            {String((data as any).error).slice(0, 60)}
          </div>
        </Tooltip>
      )}

      {status === "running" && (
        <Progress percent={progress} size="small" status="active"
          showInfo={progress != null} style={{ marginTop: 2 }} />
      )}

      {outputs.map((p: any, i: number) => {
        const preview = buildPortPreview(nodeId, p.name, "out", allNodes, allEdges, nodeResults, lang);
        const portLabel = (p.label || p.name) + (p.type ? " (" + p.type + ")" : "");
        const tooltipContent = (
          <div style={{ fontSize: 12, lineHeight: 1.6 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{portLabel}</div>
            {preview ? (
              <div style={{
                background: "rgba(255,255,255,0.08)", padding: "4px 8px",
                borderRadius: 4, fontFamily: "monospace", fontSize: 11,
                whiteSpace: "pre-wrap", maxWidth: 280,
              }}>
                {preview}
              </div>
            ) : (
              <div style={{ color: "rgba(255,255,255,0.45)", fontStyle: "italic" }}>
                {lang === "zh" ? "暂无数据" : "No data available"}
              </div>
            )}
          </div>
        );
        return (
          <Tooltip title={tooltipContent} color="#1a1a2e" placement="right" mouseEnterDelay={0.3} key={"tt-out-" + p.name}>
            <Handle
              type="source"
              position={Position.Right}
              id={p.name}
              style={portStyle(i, outputs.length)}
            />
          </Tooltip>
        );
      })}
    </div>
  );
}

export function extractColumnsFromResult(result: any): string[] {
  if (!result) return [];
  const values = Object.values(result);
  for (const v of values) {
    if (Array.isArray(v) && v.length > 0 && typeof v[0] === "object" && v[0] !== null) {
      return Object.keys(v[0]);
    }
  }
  if (Array.isArray(result) && result.length > 0 && typeof result[0] === "object") {
    return Object.keys(result[0]);
  }
  return [];
}

export function isColumnParam(paramName: string): string | null {
  const colParams = ["target_column", "left_keys", "right_keys", "sort_column", "columns", "column", "attribute_name", "group_by"];
  return colParams.includes(paramName) ? paramName : null;
}

export default memo(CustomNode);
