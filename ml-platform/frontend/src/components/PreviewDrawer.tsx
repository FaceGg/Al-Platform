type Props = {
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

export default function PreviewDrawer({ open, title = "任务预览", operationId, summary, samples = [], progress, strategySummary, errorMessage, onClose, onLoadMore, hasMore = false }: Props) {
  if (!open) return null;
  return <aside role="dialog" aria-label={title} className="annotation-preview-drawer">
    <header><h2>{title}</h2><button type="button" aria-label="关闭预览" onClick={onClose}>关闭</button></header>
    {operationId && <p>操作：{operationId}</p>}
    {typeof progress === "number" && <div aria-label="预览进度"><progress max={100} value={progress}>{progress}%</progress><span>{progress}%</span></div>}
    {errorMessage && <p role="alert">{errorMessage}</p>}
    {summary && <pre>{JSON.stringify(summary, null, 2)}</pre>}
    {strategySummary && <section aria-label="策略摘要"><h3>策略摘要</h3><pre>{JSON.stringify(strategySummary, null, 2)}</pre></section>}
    {samples.length > 0 && <section aria-label="预览样本">{samples.map((sample) => <div key={`${sample.sample_id}-${sample.row_index}`}><strong>{sample.sample_id}</strong><pre>{JSON.stringify(sample.values, null, 2)}</pre></div>)}{hasMore && <button type="button" onClick={onLoadMore}>加载更多</button>}</section>}
  </aside>;
}
