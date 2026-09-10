import { useState } from "react";
import type { ReturnBatch } from "../api/annotationReturns";

interface Props {
  items: ReturnBatch[];
  loading?: boolean;
  onDiff: (batchId: string) => void;
  onAccept: (batchId: string, taskRevision: number) => void;
  onReturn: (batchId: string, reason: string, taskRevision: number) => void;
}

export default function ReturnBatchList({ items, loading = false, onDiff, onAccept, onReturn }: Props) {
  const [returning, setReturning] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  if (loading) return <div role="status">正在加载回传批次…</div>;
  return <section className="return-batch-list" aria-label="回传批次">
    <header className="return-batch-list__header"><h3>回传结果</h3><span>{items.length} 个批次</span></header>
    {items.length === 0 ? <p>暂无回传结果</p> : <div className="return-batch-list__rows">{items.map((batch) => <article key={batch.id} className="return-batch-list__row">
      <div><strong>{batch.id.slice(0, 8)}</strong><span>修订 {batch.task_revision}</span><span data-state={batch.state}>{batch.state}</span></div>
      <div className="return-batch-list__actions"><button type="button" onClick={() => onDiff(batch.id)}>查看差异</button>{batch.state === "pending" && <><button type="button" onClick={() => onAccept(batch.id, batch.task_revision)}>验收</button><button type="button" onClick={() => { setReturning(batch.id); setReason(""); }}>退回</button></>}</div>
      {returning === batch.id && <div className="return-batch-list__return-form"><label htmlFor={`return-reason-${batch.id}`}>退回原因</label><textarea id={`return-reason-${batch.id}`} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明需要修改的内容" /><div><button type="button" onClick={() => setReturning(null)}>取消</button><button type="button" className="ant-btn ant-btn-dangerous" disabled={!reason.trim()} onClick={() => { onReturn(batch.id, reason.trim(), batch.task_revision); setReturning(null); }}>确认退回</button></div></div>}
    </article>)}</div>}
  </section>;
}
