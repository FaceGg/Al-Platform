type Props = {
  snapshot?: Record<string, unknown>;
  status?: string;
  loading?: boolean;
  sampleTotal?: number;
  open: boolean;
  title?: string;
  operationId?: string;
  summary?: Record<string, unknown>;
  samples?: Array<{ sample_id: string; row_index: number; values: Record<string, unknown> }>;
  progress?: number;
  strategySummary?: Record<string, unknown>;
  errorMessage?: string | null;
  onLoadMore?: () => void;
  hasMore?: boolean;
  onClose: () => void;
};

function displayValue(value: unknown) {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function statusLabel(status?: string) {
  return ({ queued: "排队中", running: "处理中", completed: "已完成", ready: "已就绪", failed: "失败", cancelled: "已取消" } as Record<string, string>)[status || ""] || status || "等待中";
}

export default function PreviewDrawer({ open, title = "任务预览", operationId, summary, samples = [], progress, strategySummary, errorMessage, onClose, onLoadMore, hasMore = false, snapshot, status, loading = false, sampleTotal }: Props) {
  if (!open) return null;
  return <aside role="dialog" aria-label={title} className="annotation-preview-drawer">
    <header className="annotation-preview-drawer__header">
      <div><span className="annotation-preview-drawer__eyebrow">ANNOTATION PREVIEW</span><h2>{title}</h2>{operationId && <code>{operationId}</code>}</div>
      <button type="button" aria-label="关闭预览" className="annotation-preview-drawer__close" onClick={onClose}>×</button>
    </header>
    <div className="annotation-preview-drawer__body">
      <div className="annotation-preview-drawer__status-row">
        <span className={`annotation-preview-drawer__status annotation-preview-drawer__status--${status || "queued"}`}><i />{statusLabel(status)}</span>
        {typeof progress === "number" && <span className="annotation-preview-drawer__progress-label">{progress}% 完成</span>}
      </div>
      {typeof progress === "number" && <div aria-label="预览进度" className="annotation-preview-drawer__progress"><span style={{ width: `${progress}%` }} /></div>}
      <div className="annotation-preview-drawer__metrics">
        <div><strong>{sampleTotal ?? samples.length}</strong><span>样本总数</span></div>
        <div><strong>{samples.length}</strong><span>已加载</span></div>
        <div><strong>{snapshot && Array.isArray(snapshot.visible_columns) ? snapshot.visible_columns.length : "—"}</strong><span>可见字段</span></div>
      </div>
      {errorMessage && <div className="annotation-preview-drawer__error" role="alert"><strong>预览处理失败</strong><span>{errorMessage}</span></div>}
      {snapshot && <section aria-label="任务快照" className="annotation-preview-drawer__section"><h3>任务快照</h3><dl>
        {([["instructions", "说明"], ["dataset_version", "数据版本"], ["sample_ids", "数据范围"], ["visible_columns", "可见字段"], ["label_schema", "标签 schema"], ["configuration", "模型与配置"], ["config_hash", "配置 hash"]] as const).map(([key, label]) => snapshot[key] !== undefined && <div key={key}><dt>{label}</dt><dd>{key === "sample_ids" && Array.isArray(snapshot[key]) ? `${snapshot[key].length} 个样本` : displayValue(snapshot[key])}</dd></div>)}
    </dl></section>}
      {summary && <section className="annotation-preview-drawer__section"><h3>结果摘要</h3><pre>{displayValue(summary)}</pre></section>}
      {strategySummary && <section aria-label="策略摘要" className="annotation-preview-drawer__section"><h3>策略摘要</h3><pre>{displayValue(strategySummary)}</pre></section>}
      <section aria-label="预览样本" className="annotation-preview-drawer__section annotation-preview-drawer__samples"><div className="annotation-preview-drawer__section-title"><h3>预览样本</h3><span>{samples.length}{sampleTotal !== undefined ? ` / ${sampleTotal}` : ""}</span></div>
      {!samples.length && !loading && <p>暂无样本</p>}
      {samples.map((sample) => <article className="annotation-preview-sample" key={`${sample.sample_id}-${sample.row_index}`}><div><strong>{sample.sample_id}</strong><span>第 {sample.row_index + 1} 行</span></div><pre>{displayValue(sample.values)}</pre></article>)}
      {hasMore && <button type="button" disabled={loading} onClick={onLoadMore}>加载更多</button>}
      </section>
    </div>
  </aside>;
}
