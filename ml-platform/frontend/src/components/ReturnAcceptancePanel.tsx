import { useEffect, useMemo, useState } from "react";
import {
  acceptReturnBatch,
  diffReturnBatch,
  listReturnBatches,
  returnReturnBatch,
  type ReturnBatch,
  type ReturnDiffRow,
} from "../api/annotationReturns";

type Props = { projectId: string };

function json(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 0);
}

export default function ReturnAcceptancePanel({ projectId }: Props) {
  const [batches, setBatches] = useState<ReturnBatch[]>([]);
  const [selected, setSelected] = useState<ReturnBatch | null>(null);
  const [diff, setDiff] = useState<ReturnDiffRow[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [diffLoading, setDiffLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadBatches = async (cursor?: string) => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    try {
      const page = await listReturnBatches(projectId, cursor, 50);
      setBatches(current => cursor ? [...current, ...page.items] : page.items);
      setNextCursor(page.next_cursor);
      if (!selected && page.items[0]) setSelected(page.items[0]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "回传批次加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setBatches([]);
    setSelected(null);
    setDiff([]);
    setNextCursor(null);
    void loadBatches();
  }, [projectId]);

  useEffect(() => {
    if (!selected) {
      setDiff([]);
      return;
    }
    let active = true;
    setDiffLoading(true);
    setError("");
    diffReturnBatch(selected.id, undefined, 200)
      .then(page => { if (active) setDiff(page.items); })
      .catch(cause => { if (active) setError(cause instanceof Error ? cause.message : "差异加载失败"); })
      .finally(() => { if (active) setDiffLoading(false); });
    return () => { active = false; };
  }, [selected]);

  const risks = useMemo(
    () => diff.filter(row => Object.keys(row.label_values || {}).length === 0).length,
    [diff],
  );

  const review = async (action: "accept" | "return") => {
    if (!selected) return;
    setLoading(true);
    setError("");
    setMessage("");
    try {
      if (action === "accept") {
        await acceptReturnBatch(selected.id, selected.task_revision);
        setMessage("回传批次已验收并生成新的数据版本");
      } else {
        if (!reason.trim()) {
          setError("退回原因不能为空");
          return;
        }
        await returnReturnBatch(selected.id, { task_revision: selected.task_revision, reason: reason.trim() });
        setMessage("回传批次已退回修改");
      }
      const nextState = action === "accept" ? "accepted" : "returned_for_changes";
      setBatches(current => current.map(item => item.id === selected.id ? { ...item, state: nextState } : item));
      setSelected(current => current ? { ...current, state: nextState } : current);
      setReason("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "回传验收失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="table-surface annotation-return-panel" aria-label="回传验收">
      <div className="page-header">
        <div className="page-header-copy">
          <h3 className="page-title">回传验收</h3>
          <p className="page-subtitle">基于冻结回传明细查看差异、质量风险并验收。</p>
        </div>
        <button type="button" className="ant-btn" onClick={() => { void loadBatches(); }} disabled={loading}>刷新</button>
      </div>
      {error && <div role="alert">{error}</div>}
      {message && <div role="status">{message}</div>}
      <div className="annotation-return-panel__layout">
        <div className="annotation-return-panel__batches">
          {batches.length === 0 && !loading && <p>暂无待验收回传</p>}
          {batches.map(batch => (
            <button
              type="button"
              key={batch.id}
              className={selected?.id === batch.id ? "ant-btn ant-btn-primary" : "ant-btn"}
              onClick={() => setSelected(batch)}
            >
              <span>{batch.id.slice(0, 8)}</span>
              <span>{batch.state}</span>
            </button>
          ))}
          {nextCursor && <button type="button" className="ant-btn" onClick={() => { void loadBatches(nextCursor); }} disabled={loading}>加载更多</button>}
        </div>
        <div className="annotation-return-panel__detail">
          {!selected && <p>选择一个回传批次查看明细。</p>}
          {selected && <>
            <p>批次状态：<strong>{selected.state}</strong> · 样本数：{selected.validated_row_count ?? "-"}</p>
            <p>质量风险：<strong>{risks}</strong> 条标签为空</p>
            <table>
              <thead><tr><th>样本</th><th>源数据</th><th>回传标签</th><th>风险</th></tr></thead>
              <tbody>
                {diff.map(row => {
                  const risky = Object.keys(row.label_values || {}).length === 0;
                  return <tr key={row.sample_id}><td>{row.sample_id}</td><td><code>{json(row.source_values)}</code></td><td><code>{json(row.label_values)}</code></td><td>{risky ? "标签为空" : "无"}</td></tr>;
                })}
              </tbody>
            </table>
            {diffLoading && <p>差异加载中...</p>}
            {selected.state === "pending" && selected.operation_state === "completed" && <>
              <textarea aria-label="退回原因" value={reason} maxLength={2000} onChange={event => setReason(event.target.value)} placeholder="退回时填写原因" />
              <div className="table-row-actions">
                <button type="button" className="ant-btn ant-btn-primary" disabled={loading} onClick={() => { void review("accept"); }}>验收并生成数据版本</button>
                <button type="button" className="ant-btn" disabled={loading} onClick={() => { void review("return"); }}>退回修改</button>
              </div>
            </>}
          </>}
        </div>
      </div>
    </section>
  );
}
