type Props = {
  open: boolean;
  title?: string;
  operationId?: string;
  summary?: Record<string, unknown>;
  onClose: () => void;
};

export default function PreviewDrawer({ open, title = "任务预览", operationId, summary, onClose }: Props) {
  if (!open) return null;
  return <aside role="dialog" aria-label={title} className="annotation-preview-drawer">
    <header><h2>{title}</h2><button type="button" aria-label="关闭预览" onClick={onClose}>关闭</button></header>
    {operationId && <p>操作：{operationId}</p>}
    {summary && <pre>{JSON.stringify(summary, null, 2)}</pre>}
  </aside>;
}
