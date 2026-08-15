import { Fragment, memo, useState } from "react";
import { Handle, Position, NodeProps } from "reactflow";
import { Modal, Progress, Tooltip } from "antd";
import {
  AppstoreOutlined, ApartmentOutlined, BarChartOutlined, CheckCircleFilled,
  CloseCircleFilled, DatabaseOutlined, ExperimentOutlined, FilterOutlined,
  FundOutlined, LoadingOutlined, PlayCircleOutlined, ThunderboltOutlined, ToolOutlined,
} from "@ant-design/icons";
import { normalizeNodeError, normalizeWorkflowHandle, useWorkflowStore } from "../../stores/workflowStore";
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
  return normalizeWorkflowHandle(handleId) || "";
}

export function getPortSlots(
  _nodeId: string,
  ports: any[],
  _direction: "in" | "out",
  _edges: any[],
) {
  return ports.map((port) => ({
    port,
    handleId: String(port.name),
  }));
}

export function abbreviatePortName(portName?: string | null): string {
  return Array.from(portName ?? "").slice(0, 3).join("").toUpperCase();
}

function resolvePortValue(
  nodeId: string,
  portName: string,
  portDirection: "in" | "out",
  edges: any[],
  nodeResults: Record<string, any>,
): any {
  if (portDirection === "in") {
    // For input ports: show data from the connected upstream source port
    const incEdge = edges.find(e => (
      e.target === nodeId && (logicalPortName(e.targetHandle) === portName || e.targetHandle === "in-0")
    ));
    if (incEdge && nodeResults[incEdge.source] !== undefined) {
      const upstream = nodeResults[incEdge.source];
      const sourcePort = logicalPortName(incEdge.sourceHandle);
      if (upstream && typeof upstream === "object" && sourcePort && sourcePort in upstream) {
        return upstream[sourcePort];
      }
      if (upstream && typeof upstream === "object" && portName in upstream) {
        return upstream[portName];
      }
      return upstream;
    }
  } else {
    // For output ports: show this node's result
    if (nodeResults[nodeId] !== undefined) {
      const result = nodeResults[nodeId];
      if (result && typeof result === "object" && portName in result) return result[portName];
      return result;
    }
  }
  return undefined;
}

export function inferDataFormat(value: any, declaredFormat?: string): string {
  if (declaredFormat) return declaredFormat;
  if (value == null) return "unknown";
  if (Array.isArray(value)) return "records";
  if (typeof value === "object") {
    if (Array.isArray(value.data)) return "records";
    return "object";
  }
  return typeof value;
}

export function formatSample(value: any): string {
  if (value == null) return "-";
  try {
    const sample = Array.isArray(value) ? value.slice(0, 2) : value;
    const serialized = JSON.stringify(sample, null, 2);
    return serialized === undefined ? String(sample) : serialized.slice(0, 500);
  } catch {
    return String(value).slice(0, 500);
  }
}

export function formatResult(result: any, lang: "zh" | "en"): string {
  const noData = lang === "zh" ? "暂无数据" : "No data available";
  if (result === null || result === undefined || result === "") return noData;
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

function portMetadata(port: any, value: any, lang: "zh" | "en") {
  const type = port.type || port.data_type || port.dataType || "unknown";
  const declaredFormat = port.format || port.data_format || port.dataFormat;
  const format = inferDataFormat(value, declaredFormat);
  const summary = port.summary || port.description || formatResult(value, lang);
  const sampleValue = port.sample ?? port.example ?? port.preview ?? value;
  return { type: String(type), format: String(format), summary: String(summary), sample: formatSample(sampleValue) };
}

function PortTooltipContent({ port, value, lang }: { port: any; value: any; lang: "zh" | "en" }) {
  const metadata = portMetadata(port, value, lang);
  const requiredColumns = Array.isArray(port.required_columns)
    ? port.required_columns.filter((column: unknown): column is string => typeof column === "string" && Boolean(column.trim()))
    : [];
  const labels = lang === "zh"
    ? { type: "类型", format: "格式", summary: "摘要", sample: "样例", required: "必需原始列" }
    : { type: "Type", format: "Format", summary: "Summary", sample: "Sample", required: "Required source columns" };
  return (
    <div className="workflow-port-tooltip" data-testid={`workflow-port-preview-${String(port.name)}`}>
      <div className="workflow-port-tooltip__title">{port.label || port.name}</div>
      <div className="workflow-port-tooltip__meta"><span>{labels.type}</span>{metadata.type}</div>
      <div className="workflow-port-tooltip__meta"><span>{labels.format}</span>{metadata.format}</div>
      <div className="workflow-port-tooltip__section-label">{labels.summary}</div>
      <div className="workflow-port-tooltip__preview">{metadata.summary}</div>
      {requiredColumns.length > 0 && (
        <>
          <div className="workflow-port-tooltip__section-label">{labels.required}</div>
          <div className="workflow-port-tooltip__preview">{requiredColumns.join(", ")}</div>
        </>
      )}
      <div className="workflow-port-tooltip__section-label">{labels.sample}</div>
      <pre className="workflow-port-tooltip__sample">{metadata.sample}</pre>
    </div>
  );
}

function CustomNode({ data, selected }: NodeProps) {
  const { lang, t } = useI18n();
  const status = (data.status as string) || "pending";
  const cfg = STATUS_CFG[status] || STATUS_CFG.pending;
  const progress = (data.progress as number) ?? undefined;
  const [activePreview, setActivePreview] = useState<string | null>(null);
  const [errorOpen, setErrorOpen] = useState(false);

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
  const storedNodeError = useWorkflowStore((s) => s.nodeErrors[nodeId]);
  const allEdges = useWorkflowStore((s) => s.edges);
  const inputSlots = getPortSlots(nodeId, inputs, "in", allEdges);
  const outputSlots = getPortSlots(nodeId, outputs, "out", allEdges);
  const dataNodeError = normalizeNodeError(nodeId, (data as any).error);
  const nodeError = storedNodeError || dataNodeError;
  const errorStatus = status === "failed" || status === "timed_out";
  const canOpenError = errorStatus;

  const openErrorDetails = (event?: React.MouseEvent) => {
    event?.stopPropagation();
    if (canOpenError) setErrorOpen(true);
  };

  const previewProps = (previewKey: string) => ({
    open: activePreview === previewKey,
    onMouseEnter: () => setActivePreview(previewKey),
    onMouseLeave: () => setActivePreview((current) => current === previewKey ? null : current),
    onMouseDown: () => {
      setActivePreview(null);
    },
    // ReactFlow short-circuits Handle's bubble handler when no node id is
    // available (as in isolated tests); capture keeps dismissal deterministic.
    onMouseDownCapture: () => {
      setActivePreview(null);
    },
  });

  const portStyle = (index: number, total: number, side: "left" | "right"): React.CSSProperties => ({
    top: total <= 1 ? "50%" : ((index + 0.5) / total) * 100 + "%",
    ...(side === "left" ? { left: -16 } : { right: -16 }),
  });

  return (
    <div
      className={`workflow-node workflow-node--${status}${selected ? " workflow-node--selected" : ""}`}
      data-testid="workflow-node"
    >
      {inputSlots.map(({ port: p, handleId }, i: number) => {
        const previewKey = `in:${handleId}`;
        const value = resolvePortValue(nodeId, p.name, "in", allEdges, nodeResults);
        return (
          <Fragment key={"in-" + handleId}>
            <span
              className="workflow-node__port-label workflow-node__port-label--input"
              data-testid={"port-label-in-" + handleId}
              aria-label={handleId}
              style={{ top: portStyle(i, inputSlots.length, "left").top }}
            >
              {abbreviatePortName(handleId)}
            </span>
            <Tooltip
              title={<PortTooltipContent port={p} value={value} lang={lang} />}
              placement="left"
              mouseEnterDelay={0}
              destroyOnHidden
              key={"tt-in-" + handleId}
              {...previewProps(previewKey)}
            >
              <Handle
                type="target"
                position={Position.Left}
                id={handleId}
                data-testid={"port-in-" + handleId}
                className="workflow-node-handle workflow-node-handle--input"
                style={portStyle(i, inputSlots.length, "left")}
                {...previewProps(previewKey)}
              />
            </Tooltip>
          </Fragment>
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
        {canOpenError ? (
          <button
            type="button"
            className="workflow-node__status workflow-node__status--interactive"
            data-testid="workflow-node-status"
            onClick={openErrorDetails}
            aria-label={lang === "zh" ? `${statusLabel}，查看错误详情` : `${statusLabel}, view error details`}
          >
            <span className="workflow-node__status-icon">{cfg.icon}</span>
            {statusLabel}
          </button>
        ) : (
          <span className="workflow-node__status" data-testid="workflow-node-status">
            <span className="workflow-node__status-icon">{cfg.icon}</span>
            {statusLabel}
          </span>
        )}
      </div>

      {errorStatus && nodeError && (
        <button type="button" className="workflow-node__error workflow-node__error--interactive" onClick={openErrorDetails}>
          {(nodeError.message || nodeError.code || (lang === "zh" ? "节点执行失败" : "Node execution failed")).slice(0, 60)}
        </button>
      )}

      <Modal
        title={lang === "zh" ? "节点错误详情" : "Node error details"}
        open={errorOpen}
        onCancel={() => setErrorOpen(false)}
        footer={null}
        destroyOnHidden
      >
        <div className="workflow-node__error-details" data-testid="workflow-node-error-modal">
          <div><span>{lang === "zh" ? "错误码" : "Error code"}</span><code>{nodeError?.code || "-"}</code></div>
          <div><span>{lang === "zh" ? "错误消息" : "Message"}</span><p>{nodeError?.message || "-"}</p></div>
          <div><span>{lang === "zh" ? "节点 ID" : "Node ID"}</span><code>{nodeError?.nodeId || nodeId}</code></div>
          <div><span>{lang === "zh" ? "尝试次数" : "Attempt"}</span><code>{nodeError?.attempt ?? "-"}</code></div>
        </div>
      </Modal>

      {status === "running" && (
        <Progress className="workflow-node__progress" percent={progress} size="small" status="active"
          showInfo={progress != null} />
      )}

      {outputSlots.map(({ port: p, handleId }, i: number) => {
        const previewKey = `out:${handleId}`;
        const value = resolvePortValue(nodeId, p.name, "out", allEdges, nodeResults);
        return (
          <Fragment key={"out-" + handleId}>
            <span
              className="workflow-node__port-label workflow-node__port-label--output"
              data-testid={"port-label-out-" + handleId}
              aria-label={handleId}
              style={{ top: portStyle(i, outputSlots.length, "right").top }}
            >
              {abbreviatePortName(handleId)}
            </span>
            <Tooltip
              title={<PortTooltipContent port={p} value={value} lang={lang} />}
              placement="right"
              mouseEnterDelay={0}
              destroyOnHidden
              key={"tt-out-" + handleId}
              {...previewProps(previewKey)}
            >
              <Handle
                type="source"
                position={Position.Right}
                id={handleId}
                data-testid={"port-out-" + handleId}
                className="workflow-node-handle workflow-node-handle--output"
                style={portStyle(i, outputSlots.length, "right")}
                {...previewProps(previewKey)}
              />
            </Tooltip>
          </Fragment>
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
