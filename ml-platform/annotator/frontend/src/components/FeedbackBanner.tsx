export default function FeedbackBanner({ count, onLocate }: { count: number; onLocate: () => void }) {
  if (count <= 0) return null
  return (
    <div role="alert" className="feedback-banner">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="16" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12.01" y2="8" />
      </svg>
      <span><strong>质检反馈：</strong>有 {count} 条反馈待处理（退回重编辑的任务请优先处理）</span>
      <button type="button" onClick={onLocate}>查看反馈任务</button>
    </div>
  )
}
