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

export default function PreviewDrawer({ open, title = "任务预览", operationId, summary, samples = [], progress, strategySummary, errorMessage, onClose, onLoadMore, hasMore = false, snapshot, status, loading = false, sampleTotal }: Props) {
  if (!open) return null;
  return <aside role="dialog" aria-label={title} className="annotation-preview-drawer">
    <header><h2>{title}</h2><button type="button" aria-label="关闭预览" onClick={onClose}>关闭</button></header>
    {operationId && <p>操作：{operationId}</p>}
    {status && <p>状态：{status}</p>}
    {snapshot && <section aria-label="任务快照"><h3>任务快照</h3><dl>
      {([["instructions", "说明"], ["dataset_version", "数据版本"], ["sample_ids", "数据范围"], ["visible_columns", "可见字段"], ["label_schema", "标签 schema"], ["configuration", "模型与配置"], ["config_hash", "配置 hash"]] as const).map(([key, label]) => snapshot[key] !== undefined && <div key={key}><dt>{label}</dt><dd style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{key === "sample_ids" && Array.isArray(snapshot[key]) ? `${snapshot[key].length} 个样本` : typeof snapshot[key] === "string" ? snapshot[key] : JSON.stringify(snapshot[key])}</dd></div>)}
    </dl></section>}
    {typeof progress === "number" && <div aria-label="预览进度"><progress max={100} value={progress}>{progress}%</progress><span>{progress}%</span></div>}
    {errorMessage && <p role="alert">{errorMessage}</p>}
    {summary && <pre>{JSON.stringify(summary, null, 2)}</pre>}
    {strategySummary && <section aria-label="策略摘要"><h3>策略摘要</h3><pre>{JSON.stringify(strategySummary, null, 2)}</pre></section>}
    <section aria-label="预览样本">
      <h3>预览样本{sampleTotal !== undefined ? ` (${samples.length}/${sampleTotal})` : ""}</h3>
      {!samples.length && !loading && <p>暂无样本</p>}
      {samples.map((sample) => <div key={`${sample.sample_id}-${sample.row_index}`}><strong>{sample.sample_id}</strong><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(sample.values, null, 2)}</pre></div>)}
      {hasMore && <button type="button" disabled={loading} onClick={onLoadMore}>加载更多</button>}
    </section>
  </aside>;
}
