import { memo } from "react";
import { Handle, Position, NodeProps } from "reactflow";
import { Progress, Tooltip } from "antd";
import {
  AppstoreOutlined, ApartmentOutlined, BarChartOutlined, CheckCircleFilled,
  CloseCircleFilled, DatabaseOutlined, ExperimentOutlined, FilterOutlined,
  FundOutlined, LoadingOutlined, PlayCircleOutlined, ThunderboltOutlined, ToolOutlined,
} from "@ant-design/icons";
import { useWorkflowStore } from "../../stores/workflowStore";
import { useI18n } from "../../i18n";

const STATUS_CFG: Record<string, { icon: React.ReactNode }> = {
  pending: { icon: <PlayCircleOutlined /> },
  running: { icon: <LoadingOutlined spin /> },
  completed: { icon: <CheckCircleFilled /> },
  failed: { icon: <CloseCircleFilled /> },
  timed_out: { icon: <CloseCircleFilled /> },
  cancelled: { icon: <CloseCircleFilled /> },
  skipped: { icon: <PlayCircleOutlined /> },
};

const CATEGORY_ICONS = {
  data_io: DatabaseOutlined,
  processing: FilterOutlined,
  blending: ApartmentOutlined,
  ml: ExperimentOutlined,
  dl: ThunderboltOutlined,
  evaluation: BarChartOutlined,
  visualization: FundOutlined,
  control: ApartmentOutlined,
  mechanism: ToolOutlined,
  optimization: ExperimentOutlined,
  utility: AppstoreOutlined,
};

function normalizeCategory(category?: string): keyof typeof CATEGORY_ICONS {
  if (category === "io") return "data_io";
  if (category && category in CATEGORY_ICONS) return category as keyof typeof CATEGORY_ICONS;
  return "utility";
}

function logicalPortName(handleId?: string | null): string {
  return String(handleId || "").replace(/__slot_\d+$/, "");
}

export function getPortSlots(
  nodeId: string,
  ports: any[],
  direction: "in" | "out",
  edges: any[],
) {
  return ports.flatMap((port) => {
    const connectionCount = edges.filter((edge) => (
      direction === "in"
        ? edge.target === nodeId && logicalPortName(edge.targetHandle) === port.name
        : edge.source === nodeId && logicalPortName(edge.sourceHandle) === port.name
    )).length;
    return Array.from({ length: Math.max(1, connectionCount + 1) }, (_, slot) => ({
      port,
      handleId: `${port.name}__slot_${slot}`,
    }));
  });
}

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
    const incEdge = edges.find(e => (
      e.target === nodeId && (logicalPortName(e.targetHandle) === portName || e.targetHandle === "in-0")
    ));
    if (incEdge && nodeResults[incEdge.source]) {
      const upstream = nodeResults[incEdge.source];
      return formatResult(upstream[portName] ?? upstream, lang);
    }
  } else {
    // For output ports: show this node's result
    if (nodeResults[nodeId]) {
      const result = nodeResults[nodeId];
      return formatResult(result[portName] ?? result, lang);
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
  const { lang, t } = useI18n();
  const status = (data.status as string) || "pending";
  const cfg = STATUS_CFG[status] || STATUS_CFG.pending;
  const progress = (data.progress as number) ?? undefined;

  const opId = data.operatorId as string || "";
  const label = (t as any).operator?.[opId] || (data.label as string) || opId;
  const nodeId = data.nodeId as string || "";
  const category = normalizeCategory(data.category as string);
  const CategoryIcon = CATEGORY_ICONS[category];
  const statusLabel = {
    completed: lang === "zh" ? "已完成" : "Completed",
    running: lang === "zh" ? "运行中" : "Running",
    failed: lang === "zh" ? "失败" : "Failed",
    timed_out: lang === "zh" ? "已超时" : "Timed out",
    cancelled: lang === "zh" ? "已取消" : "Cancelled",
    skipped: lang === "zh" ? "已跳过" : "Skipped",
    pending: lang === "zh" ? "待运行" : "Pending",
  }[status] || status;

  const inputs = Array.isArray(data.inputs) ? data.inputs : [];
  const outputs = Array.isArray(data.outputs) ? data.outputs : [];

  // Get node results and edges from store for port preview
  const nodeResults = useWorkflowStore((s) => s.nodeResults);
  const allEdges = useWorkflowStore((s) => s.edges);
  const allNodes = useWorkflowStore((s) => s.nodes);
  const inputSlots = getPortSlots(nodeId, inputs, "in", allEdges);
  const outputSlots = getPortSlots(nodeId, outputs, "out", allEdges);

  const portStyle = (index: number, total: number, side: "left" | "right"): React.CSSProperties => ({
    top: total <= 1 ? "50%" : ((index + 0.5) / total) * 100 + "%",
    ...(side === "left" ? { left: -9 } : { right: -9 }),
  });

  return (
    <div
      className={`workflow-node workflow-node--${status}${selected ? " workflow-node--selected" : ""}`}
      data-testid="workflow-node"
    >
      {inputSlots.map(({ port: p, handleId }, i: number) => {
        const preview = buildPortPreview(nodeId, p.name, "in", allNodes, allEdges, nodeResults, lang);
        const portLabel = (p.label || p.name) + (p.type ? " (" + p.type + ")" : "");
        const tooltipContent = (
          <div style={{ fontSize: 12, lineHeight: 1.6 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{portLabel}</div>
            {preview ? (
              <div className="workflow-port-tooltip__preview">
                {preview}
              </div>
            ) : (
              <div className="workflow-port-tooltip__empty">
                {lang === "zh" ? "暂无数据" : "No data available"}
              </div>
            )}
          </div>
        );
        return (
          <Tooltip title={tooltipContent} placement="left" mouseEnterDelay={0.3} key={"tt-in-" + handleId}>
            <Handle
              type="target"
              position={Position.Left}
              id={handleId}
              data-testid={"port-in-" + handleId}
              className="workflow-node-handle workflow-node-handle--input"
              style={portStyle(i, inputSlots.length, "left")}
            />
          </Tooltip>
        );
      })}

      <div className="workflow-node__header">
        <span className="workflow-node__category" data-testid="workflow-node-category">
          <CategoryIcon />
        </span>
        <div className="workflow-node__identity">
          <span className="workflow-node__title" title={label}>{label}</span>
          <span className="workflow-node__operator-id">{opId}</span>
        </div>
        <span className="workflow-node__status" data-testid="workflow-node-status">
          <span className="workflow-node__status-icon">{cfg.icon}</span>
          {statusLabel}
        </span>
      </div>

      <div className="workflow-node__signals" aria-hidden="true">
        <span>IN {inputs.length}</span>
        <span>OUT {outputs.length}</span>
      </div>

      {status === "failed" && (data as any).error && (
        <Tooltip title={String((data as any).error)}>
          <div className="workflow-node__error">
            {String((data as any).error).slice(0, 60)}
          </div>
        </Tooltip>
      )}

      {status === "running" && (
        <Progress className="workflow-node__progress" percent={progress} size="small" status="active"
          showInfo={progress != null} />
      )}

      {outputSlots.map(({ port: p, handleId }, i: number) => {
        const preview = buildPortPreview(nodeId, p.name, "out", allNodes, allEdges, nodeResults, lang);
        const portLabel = (p.label || p.name) + (p.type ? " (" + p.type + ")" : "");
        const tooltipContent = (
          <div style={{ fontSize: 12, lineHeight: 1.6 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{portLabel}</div>
            {preview ? (
              <div className="workflow-port-tooltip__preview">
                {preview}
              </div>
            ) : (
              <div className="workflow-port-tooltip__empty">
                {lang === "zh" ? "暂无数据" : "No data available"}
              </div>
            )}
          </div>
        );
        return (
          <Tooltip title={tooltipContent} placement="right" mouseEnterDelay={0.3} key={"tt-out-" + handleId}>
            <Handle
              type="source"
              position={Position.Right}
              id={handleId}
              data-testid={"port-out-" + handleId}
              className="workflow-node-handle workflow-node-handle--output"
              style={portStyle(i, outputSlots.length, "right")}
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
