import { Empty, Spin, Tag } from "antd";
import type { ReactNode } from "react";

import type { AnnotationOperation } from "../../api/annotationTasks";
import { taskStatusColor, taskStatusLabel } from "../../utils/taskStatus";

/**
 * 通用任务操作面板（P3 拆分第二刀，自 DataAnnotationPage 原位抽出，
 * 渲染结构不变）。刷新/加载更多/查看结果均回传意图，状态留在页面。
 */
export interface TaskOperationsPanelProps {
  lang: "zh" | "en";
  title: ReactNode;
  operations: AnnotationOperation[];
  loading: boolean;
  cursor: string | null;
  formatTimestamp: (value: string | null | undefined) => string;
  onRefresh: () => void;
  onLoadMore: () => void;
  onViewExecutionResult?: (operation: AnnotationOperation) => void;
}

export default function TaskOperationsPanel({
  lang,
  title,
  operations,
  loading,
  cursor,
  formatTimestamp,
  onRefresh,
  onLoadMore,
  onViewExecutionResult,
}: TaskOperationsPanelProps) {
  const zh = lang === "zh";
  return (
    <div className="table-surface data-annotation__operations-surface" role="region" aria-label="通用任务操作">
      <div className="data-annotation__section-head">
        <h3>{title}</h3>
        <button type="button" className="ant-btn ant-btn-sm" onClick={onRefresh} disabled={loading}>{zh ? "刷新操作" : "Refresh"}</button>
      </div>
      <div className="data-annotation__operations">
        {loading && operations.length === 0 && <div className="data-annotation__operations-loading"><Spin /></div>}
        {!loading && operations.length === 0 && <Empty description={zh ? "暂无任务操作记录" : "No task operations"} />}
        {operations.map((operation) => <div className="data-annotation__operation" key={operation.id}>
          <div className="data-annotation__operation-head">
            <code title={operation.id}>{operation.id.slice(0, 8)}</code>
            <Tag color={taskStatusColor(operation.state)}>{taskStatusLabel(operation.state, lang)}</Tag>
          </div>
          <div className="data-annotation__operation-meta">
            <span>{operation.resource_type}</span>
            <span aria-hidden="true">·</span>
            <span>{operation.stage}</span>
          </div>
          {operation.task_id && <div className="data-annotation__operation-task">
            {zh ? "任务" : "Task"} <code title={operation.task_id}>{operation.task_id.slice(0, 8)}</code>
          </div>}
          <div className="data-annotation__operation-progress">
            <span className="data-annotation__progress-track" aria-hidden="true"><i style={{ width: `${Math.min(100, Math.max(0, Number(operation.progress) || 0))}%` }} /></span>
            <span className="data-annotation__progress-text">{operation.progress}%</span>
          </div>
          {operation.created_at && <div className="data-annotation__operation-time">{formatTimestamp(operation.created_at)}</div>}
          {operation.error_code && <div className="data-annotation__operation-error" role="alert">{operation.error_code}</div>}
          {operation.resource_type === "annotation_execution" && operation.state === "completed" && (
            <button type="button" className="ant-btn ant-btn-sm" onClick={() => { onViewExecutionResult?.(operation); }}>{zh ? "查看结果" : "View results"}</button>
          )}
        </div>)}
      </div>
      {cursor && <div className="table-row-actions data-annotation__operations-more"><button type="button" className="ant-btn ant-btn-sm" onClick={onLoadMore} disabled={loading}>{zh ? "加载更多操作" : "Load more"}</button></div>}
    </div>
  );
}
