import { Progress, Tag } from "antd";
import { useI18n } from "../../i18n";
import { useWorkflowStore } from "../../stores/workflowStore";

export default function ExecutionProgress() {
  const { t } = useI18n();
  const { isRunning, nodeStatuses, nodes } = useWorkflowStore();

  // Build lookup: nodeId -> display name
  const nodeLabelMap: Record<string, string> = {};
  for (const n of nodes) {
    const opId = n.data?.operatorId as string || "";
    const zh = (t as any).operator?.[opId] || "";
    nodeLabelMap[n.id] = zh || n.data?.label || opId || n.id.slice(0, 8);
  }

  const nodeEntries = Object.entries(nodeStatuses).filter(([id]) => !id.startsWith("__"));
  const realTotal = nodes.length;

  if (nodeEntries.length === 0 && !isRunning) return null;

  const completed = nodeEntries.filter(([, s]) => s === "completed").length;
  const running = nodeEntries.filter(([, s]) => s === "running").length;
  const failed = nodeEntries.filter(([, s]) => s === "failed").length;
  const timedOut = nodeEntries.filter(([, s]) => s === "timed_out").length;
  const cancelled = nodeEntries.filter(([, s]) => s === "cancelled").length;
  const skipped = nodeEntries.filter(([, s]) => s === "skipped").length;
  const finished = completed + failed + timedOut + cancelled + skipped;
  const total = realTotal || nodeEntries.length;
  const percent = total > 0 ? Math.round((finished / total) * 100) : 0;
  const progressStatus = failed + timedOut > 0 ? "failed"
    : cancelled > 0 && finished === total ? "cancelled"
      : !isRunning && total > 0 && finished === total ? "completed"
        : isRunning ? "running" : "pending";

  const progressLabel = t.workspace?.run_progress || "\u6267\u884c\u8fdb\u5ea6";
  const nodeUnit = "\u4e2a\u8282\u70b9"; // 个节点

  return (
    <div className={`execution-progress execution-progress--${progressStatus}`} data-testid="execution-progress" data-status={progressStatus}>
      <div className="execution-progress__summary">
        <span>{progressLabel}</span>
        <span>{finished}/{total} {nodeUnit}</span>
      </div>
      <Progress className="execution-progress__bar" percent={percent} size="small"
        status={(failed + timedOut) > 0 && !isRunning ? "exception" : isRunning ? "active" : "success"} />
      {running > 0 && (
        <div className="execution-progress__running">
          {"\u8fd0\u884c\u4e2d"} {running} {nodeUnit}
        </div>
      )}
      <div className="execution-progress__tags">
        {nodeEntries.slice(0, 8).map(([id, status]) => (
          <Tag key={id} color={
            status === "completed" ? "success" :
            status === "running" ? "processing" :
            status === "failed" || status === "timed_out" ? "error" :
            status === "cancelled" ? "warning" : "default"
          } className="execution-progress__tag">
            {nodeLabelMap[id] || id.slice(0, 8)}
          </Tag>
        ))}
      </div>
    </div>
  );
}
