import { useState } from "react";
import { Empty, Spin, Tag } from "antd";
import type { ReturnBatch } from "../api/annotationReturns";
import { formatLocalTime } from "../utils/time";

type Props = {
  items: ReturnBatch[];
  loading: boolean;
  onDiff: (batchId: string) => void;
  onAccept: (batchId: string, taskRevision: number) => void;
  onReturn: (batchId: string, reason: string, taskRevision: number) => void;
};

function batchStateLabel(state: string): string {
  if (state === "pending") return "待验收";
  if (state === "accepted") return "已验收";
  if (state === "returned_for_changes") return "已退回";
  return state;
}

function batchStateColor(state: string): string {
  if (state === "pending") return "orange";
  if (state === "accepted") return "green";
  if (state === "returned_for_changes") return "red";
  return "default";
}

// 与 ReturnAcceptancePanel / 任务操作记录一致：标注员名优先，缺失时回退 subject_id 前 8 位。
function annotatorLabel(batch: ReturnBatch): string {
  return batch.annotator_name || (batch.annotator_subject_id || "").slice(0, 8) || "-";
}

export default function ReturnBatchList({ items, loading, onDiff, onAccept, onReturn }: Props) {
  const [reasonDraft, setReasonDraft] = useState<Record<string, string>>({});
  const [returningId, setReturningId] = useState<string | null>(null);
  const pendingCount = items.filter(batch => batch.state === "pending").length;

  return (
    <section className="table-surface data-annotation__operations-surface return-batch-list" role="region" aria-label="回传结果">
      <div className="data-annotation__section-head">
        <h3>回传结果</h3>
        <span className="return-batch-list__summary">
          共 {items.length} 个批次{pendingCount > 0 ? ` · ${pendingCount} 个待验收` : ""}
        </span>
      </div>
      <div className="data-annotation__operations">
        {loading && items.length === 0 && <div className="data-annotation__operations-loading"><Spin /></div>}
        {!loading && items.length === 0 && <Empty description="暂无回传批次" />}
        {items.map(batch => {
          const actionable = batch.state === "pending";
          const reason = reasonDraft[batch.id] ?? "";
          const returning = returningId === batch.id;
          return (
            <div className="data-annotation__operation" key={batch.id}>
              <div className="data-annotation__operation-head">
                <code title={batch.task_name || batch.id}>{batch.task_name || batch.id.slice(0, 8)}</code>
                <Tag color={batchStateColor(batch.state)}>{batchStateLabel(batch.state)}</Tag>
              </div>
              <div className="data-annotation__operation-meta">
                <span title={batch.annotator_subject_id || undefined}>标注员 {annotatorLabel(batch)}</span>
                <span aria-hidden="true">·</span>
                <span>{typeof batch.validated_row_count === "number" ? `${batch.validated_row_count} 条样本` : "样本数 -"}</span>
                <span aria-hidden="true">·</span>
                <span>修订 {batch.task_revision}</span>
              </div>
              {batch.source_dataset_name && (
                <div className="data-annotation__operation-task">
                  原始文件 <code title={batch.source_dataset_name}>{batch.source_dataset_name}</code>
                </div>
              )}
              {batch.task_id && (
                <div className="data-annotation__operation-task">
                  任务 <code title={batch.task_id}>{batch.task_id.slice(0, 8)}</code>
                </div>
              )}
              {batch.saved_dataset_name && (
                <div className="data-annotation__operation-task">
                  已保存制品 <code title={batch.saved_dataset_name}>{batch.saved_dataset_name}</code>
                </div>
              )}
              {batch.created_at && (
                <div className="data-annotation__operation-time">{formatLocalTime(batch.created_at, true)}</div>
              )}
              {actionable && returning && (
                <textarea
                  aria-label="退回原因"
                  value={reason}
                  maxLength={2000}
                  placeholder="退回时填写原因"
                  onChange={event => setReasonDraft({ ...reasonDraft, [batch.id]: event.target.value })}
                />
              )}
              <div className="table-row-actions">
                <button type="button" className="ant-btn ant-btn-sm" onClick={() => onDiff(batch.id)}>查看差异</button>
                {actionable && !returning && (
                  <button type="button" className="ant-btn ant-btn-sm ant-btn-primary" onClick={() => onAccept(batch.id, batch.task_revision)}>验收</button>
                )}
                {actionable && !returning && (
                  <button type="button" className="ant-btn ant-btn-sm ant-btn-dangerous" onClick={() => setReturningId(batch.id)}>退回</button>
                )}
                {actionable && returning && (
                  <button type="button" className="ant-btn ant-btn-sm ant-btn-dangerous" disabled={!reason.trim()} onClick={() => { onReturn(batch.id, reason, batch.task_revision); setReturningId(null); }}>确认退回</button>
                )}
                {actionable && returning && (
                  <button type="button" className="ant-btn ant-btn-sm" onClick={() => setReturningId(null)}>取消</button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
