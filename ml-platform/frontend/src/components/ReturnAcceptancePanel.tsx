import { useEffect, useMemo, useState } from "react";
import { Drawer, Empty, Spin, Tag } from "antd";
import {
  acceptReturnBatch,
  diffReturnBatch,
  exportReturnBatchDataset,
  exportReturnBatchPreview,
  listReturnBatches,
  returnReturnBatch,
  type ExportPreview,
  type ReturnBatch,
  type ReturnDiffRow,
} from "../api/annotationReturns";

type Props = { projectId: string };

// 后端以 UTC 存储时间戳；补 "Z" 后按浏览器本地时区展示（与 DataAnnotationPage 一致）。
function formatBackendTimestamp(value: string | null | undefined): string {
  if (!value) return "-";
  const hasTimezone = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(value);
  const date = new Date(hasTimezone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function annotatorPortalUrl(taskId?: string | null): string {
  const base = (import.meta.env.VITE_ANNOTATOR_PORTAL_URL as string | undefined)
    || `${window.location.protocol}//${window.location.hostname}:8443`;
  // viewer=admin binds the portal tab to the admin session cookie so a
  // logged-in annotator session never shadows the reviewer identity.
  return taskId ? `${base}/?task=${encodeURIComponent(taskId)}&viewer=admin` : base;
}

function batchTitle(batch: ReturnBatch): string {
  if (batch.task_name || batch.task_id) {
    const name = batch.task_name || "未命名任务";
    return `${name} (${(batch.task_id || "").slice(0, 8)})`;
  }
  return batch.id.slice(0, 8);
}

function batchHeadLabel(batch: ReturnBatch): string {
  if (batch.task_name || batch.task_id) return batch.task_name || "未命名任务";
  return batch.id.slice(0, 8);
}

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

function canReviewBatch(batch: ReturnBatch | null | undefined): boolean {
  return Boolean(batch && batch.state === "pending" && batch.operation_state === "completed");
}

function returnValidationLabel(batch: ReturnBatch): string {
  if (batch.operation_state === "completed") return "已完成";
  if (batch.operation_state === "failed") return `失败${batch.operation_error_code ? ` · ${batch.operation_error_code}` : ""}`;
  if (batch.operation_state === "running") return "校验中";
  if (batch.operation_state === "queued") return "排队中";
  return "未启动";
}

// Non-ASCII (e.g. Chinese) label column names are invalid identifiers in the
// exported dataset; the user has to provide an English name before saving.
const needsEnglishName = (key: string): boolean => /[^\x00-\x7F]/.test(key);

const isEnglishIdentifier = (value: string): boolean => /^[A-Za-z_][A-Za-z0-9_]*$/.test(value);

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
  const [exportName, setExportName] = useState("");
  const [exportPreview, setExportPreview] = useState<ExportPreview | null>(null);
  const [exportLoading, setExportLoading] = useState(false);
  const [exportSaving, setExportSaving] = useState(false);
  const [exportRenames, setExportRenames] = useState<Record<string, string>>({});

  const loadBatches = async (cursor?: string) => {
    if (!projectId) return;
    setLoading(true);
    setError("");
    try {
      const page = await listReturnBatches(projectId, cursor, 50);
      setBatches(current => cursor ? [...current, ...page.items] : page.items);
      setSelected(current => {
        if (!current) return current;
        return page.items.find(item => item.id === current.id) || current;
      });
      setNextCursor(page.next_cursor);
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
    // Frozen sample rows do not exist until the durable validation operation
    // completes. Avoid calling the diff endpoint while it is queued/running;
    // that endpoint correctly returns 409 RETURN_BATCH_NOT_READY.
    if (selected.operation_state !== "completed") {
      setDiff([]);
      setDiffLoading(false);
      return;
    }
    let active = true;
    setDiffLoading(true);
    setError("");
    // The diff is only used to compute the quality-risk summary; sample details
    // are reviewed in the annotator portal, not rendered here.
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
    if (!canReviewBatch(selected)) {
      setError("回传校验尚未完成，请刷新状态后再验收或退回");
      return;
    }
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

  const resetExportState = () => {
    setExportName("");
    setExportPreview(null);
    setExportLoading(false);
    setExportSaving(false);
    setExportRenames({});
  };

  const saveExportDataset = async (batch: ReturnBatch, name: string, renames: Record<string, string> = {}) => {
    setExportSaving(true);
    setError("");
    try {
      const result = await exportReturnBatchDataset(batch.id, name, renames);
      setMessage(`已保存到数据管理：${result.name}（${result.row_count} 条）`);
      resetExportState();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存到数据管理失败");
    } finally {
      setExportSaving(false);
    }
  };

  const startExportPreview = async () => {
    if (!selected || !exportName.trim() || exportLoading || exportSaving) return;
    setExportLoading(true);
    setError("");
    setExportPreview(null);
    try {
      const preview = await exportReturnBatchPreview(selected.id);
      // Numeric label columns with English names save directly; string columns
      // need the value→int mapping confirmed, and Chinese column names need an
      // English rename, before saving.
      const needsConfirm = preview.columns.some(
        column => column.value_type === "string" || needsEnglishName(column.machine_key),
      );
      if (!needsConfirm) {
        await saveExportDataset(selected, exportName.trim());
      } else {
        setExportPreview(preview);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "标签类型检测失败");
    } finally {
      setExportLoading(false);
    }
  };

  return (
    <section className="table-surface data-annotation__operations-surface annotation-return-panel" role="region" aria-label="回传验收">
      <div className="data-annotation__section-head">
        <h3>回传验收</h3>
        <button type="button" className="ant-btn ant-btn-sm" onClick={() => { void loadBatches(); }} disabled={loading}>刷新</button>
      </div>
      <div className="annotation-return-panel__notices">
        {error && <div role="alert">{error}</div>}
        {message && <div role="status">{message}</div>}
      </div>
      <div className="data-annotation__operations">
        {loading && batches.length === 0 && <div className="data-annotation__operations-loading"><Spin /></div>}
        {!loading && batches.length === 0 && <Empty description="暂无回传批次" />}
        {batches.map(batch => (
          <div className="data-annotation__operation" key={batch.id}>
            <div className="data-annotation__operation-head">
              <code title={batch.task_id || batch.id}>{batchHeadLabel(batch)}</code>
              <Tag color={batchStateColor(batch.state)}>{batchStateLabel(batch.state)}</Tag>
            </div>
            <div className="data-annotation__operation-meta">
              <span>标注员 {batch.annotator_name || (batch.annotator_subject_id || "").slice(0, 8) || "-"}</span>
              <span aria-hidden="true">·</span>
              <span>{typeof batch.validated_row_count === "number" ? `${batch.validated_row_count} 条` : "样本数 -"}</span>
            </div>
            {batch.task_id && <div className="data-annotation__operation-task">
              任务 <code title={batch.task_id}>{batch.task_id.slice(0, 8)}</code>
            </div>}
            {batch.created_at && <div className="data-annotation__operation-time">{formatBackendTimestamp(batch.created_at)}</div>}
            {batch.state === "pending" && !canReviewBatch(batch) && (
              <div className="data-annotation__operation-task">
                回传校验 <strong>{returnValidationLabel(batch)}</strong>
              </div>
            )}
            <button type="button" className="ant-btn ant-btn-sm annotation-return-panel__action" onClick={() => setSelected(batch)}>
              {canReviewBatch(batch) ? "打开验收" : batch.state === "pending" ? "查看状态" : "查看摘要"}
            </button>
          </div>
        ))}
      </div>
      {nextCursor && <div className="table-row-actions data-annotation__operations-more"><button type="button" className="ant-btn ant-btn-sm" onClick={() => { void loadBatches(nextCursor); }} disabled={loading}>加载更多</button></div>}
      <Drawer
        open={Boolean(selected)}
        title={selected ? `回传验收 · ${batchTitle(selected)}` : "回传验收"}
        onClose={() => { setSelected(null); setReason(""); resetExportState(); }}
        width={480}
        rootClassName="annotation-return-panel-drawer"
        destroyOnClose
      >
        {selected && <>
          <p>任务：<strong>{batchTitle(selected)}</strong></p>
          <p>标注员：<strong>{selected.annotator_name || (selected.annotator_subject_id || "").slice(0, 8) || "-"}</strong></p>
          <p>批次状态：<Tag color={batchStateColor(selected.state)}>{batchStateLabel(selected.state)}</Tag> · 样本数：{selected.validated_row_count ?? "-"} · 修订：{selected.task_revision}</p>
          {selected.state === "pending" && !canReviewBatch(selected) ? (
            <p role="status">回传内容正在校验，完成后才能验收或退回。当前状态：{returnValidationLabel(selected)}。请点击上方“刷新”查看最新状态。</p>
          ) : (
            <p>质量风险：<strong>{diffLoading ? "…" : risks}</strong> 条标签为空{diff.length > 0 && diff.length < (selected.validated_row_count ?? diff.length) ? `（已扫描前 ${diff.length} 条）` : ""}</p>
          )}
          <p className="annotation-return-panel__hint">
            样本数据与标注结果不在验收页展开；请点击下方按钮跳转标注员门户查看明细后再验收。
          </p>
          <div className="table-row-actions">
            <button
              type="button"
              className="ant-btn"
              onClick={() => { window.open(annotatorPortalUrl(selected.task_id), "_blank", "noopener"); }}
            >
              在标注员门户查看明细
            </button>
          </div>
          {canReviewBatch(selected) && <>
            <textarea aria-label="退回原因" value={reason} maxLength={2000} onChange={event => setReason(event.target.value)} placeholder="退回时填写原因" />
            <div className="table-row-actions">
              <button type="button" className="ant-btn ant-btn-primary" disabled={loading} onClick={() => { void review("accept"); }}>验收并生成数据版本</button>
              <button type="button" className="ant-btn" disabled={loading} onClick={() => { void review("return"); }}>退回修改</button>
            </div>
          </>}
          {selected.state === "accepted" && (
            <div className="annotation-return-panel__export">
              <h4>保存到数据管理</h4>
              <p className="annotation-return-panel__hint">
                将已验收的标注结果保存为数据管理中的数据集。数值型标签（int/float）直接保存；文本型（string）标签将按映射转换为整数。
              </p>
              <input
                aria-label="数据集名称"
                value={exportName}
                maxLength={256}
                placeholder="数据集名称"
                onChange={event => setExportName(event.target.value)}
              />
              <div className="table-row-actions">
                <button
                  type="button"
                  className="ant-btn ant-btn-primary"
                  disabled={!exportName.trim() || exportLoading || exportSaving}
                  onClick={() => { void startExportPreview(); }}
                >
                  {exportLoading ? "检测标签中…" : "检测标签并保存"}
                </button>
              </div>
              {exportPreview && <>
                <p>标签列检测结果（共 {exportPreview.row_count} 条样本）：</p>
                {exportPreview.columns.map(column => (
                  <div className="annotation-return-panel__export-column" key={column.machine_key}>
                    <div>
                      <code>{column.machine_key}</code>（{column.display_name}）{" "}
                      <Tag color={column.value_type === "string" ? "orange" : "green"}>
                        {column.value_type === "string" ? "文本 · 需映射" : `${column.value_type} · 直接保存`}
                      </Tag>
                      {needsEnglishName(column.machine_key) && (
                        <Tag color="red">中文名称 · 需改为英文</Tag>
                      )}
                    </div>
                    {needsEnglishName(column.machine_key) && (
                      <div className="annotation-return-panel__export-rename">
                        <label htmlFor={`export-rename-${column.machine_key}`}>重命名为</label>
                        <input
                          id={`export-rename-${column.machine_key}`}
                          aria-label={`英文列名 ${column.machine_key}`}
                          value={exportRenames[column.machine_key] || ""}
                          maxLength={64}
                          placeholder={`英文名称，如 label_${column.display_name}`}
                          onChange={event => setExportRenames(current => ({ ...current, [column.machine_key]: event.target.value }))}
                        />
                      </div>
                    )}
                    {column.value_type === "string" && Object.keys(column.mapping || {}).length > 0 && (
                      <table className="annotation-return-panel__export-mapping">
                        <thead><tr><th>标签值</th><th>映射为</th></tr></thead>
                        <tbody>
                          {Object.entries(column.mapping || {}).map(([value, index]) => (
                            <tr key={value}><td>{value}</td><td>{index}</td></tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                ))}
                <div className="table-row-actions">
                  <button
                    type="button"
                    className="ant-btn ant-btn-primary"
                    disabled={exportSaving || exportPreview.columns.some(
                      column => needsEnglishName(column.machine_key) && !isEnglishIdentifier((exportRenames[column.machine_key] || "").trim()),
                    )}
                    onClick={() => {
                      const renames = Object.fromEntries(
                        Object.entries(exportRenames)
                          .map(([key, value]) => [key, value.trim()])
                          .filter(([, value]) => value.length > 0),
                      );
                      void saveExportDataset(selected, exportName.trim(), renames);
                    }}
                  >
                    确认映射并保存到数据管理
                  </button>
                  <button type="button" className="ant-btn" onClick={() => setExportPreview(null)}>取消</button>
                </div>
              </>}
            </div>
          )}
        </>}
      </Drawer>
    </section>
  );
}
