import { useEffect, useMemo, useState } from "react";
import type { AnnotatorSubject, SampleScope } from "../api/annotatorAssignments";

interface Props {
  open: boolean;
  taskRevision: number;
  sampleScope: SampleScope;
  annotators: AnnotatorSubject[];
  overlapWarning?: string | null;
  loading?: boolean;
  onClose: () => void;
  onSearch?: (query: string) => void;
  onSubmit: (payload: { annotator_ids: string[]; sample_scope: SampleScope; due_at?: string }) => void;
}

export default function AssignmentDialog({ open, taskRevision, sampleScope, annotators, overlapWarning, loading = false, onClose, onSearch, onSubmit }: Props) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [dueAt, setDueAt] = useState("");

  useEffect(() => {
    if (!open) {
      setQuery("");
      setSelected([]);
      setDueAt("");
    }
  }, [open]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? annotators.filter((item) => `${item.username} ${item.display_name || ""}`.toLowerCase().includes(needle)) : annotators;
  }, [annotators, query]);

  if (!open) return null;
  return <div className="annotation-dialog-backdrop" role="presentation">
    <section className="annotation-dialog" role="dialog" aria-modal="true" aria-labelledby="assignment-dialog-title">
      <header className="annotation-dialog__header"><div><h2 id="assignment-dialog-title">指派任务</h2><p>任务修订 {taskRevision} · 固定样本 {sampleScope.sample_ids.length} 条</p></div><button type="button" aria-label="关闭指派" onClick={onClose}>关闭</button></header>
      <div className="annotation-dialog__body">
        <label htmlFor="annotator-search">搜索标注员</label>
        <input id="annotator-search" value={query} onChange={(event) => { setQuery(event.target.value); onSearch?.(event.target.value); }} placeholder="按名称搜索" />
        {overlapWarning && <p role="alert" className="annotation-dialog__warning">{overlapWarning}</p>}
        <div className="annotation-dialog__scope" aria-label="指派范围摘要"><strong>指派范围</strong><span>{sampleScope.kind} · {sampleScope.sample_ids.slice(0, 5).join(", ")}{sampleScope.sample_ids.length > 5 ? " …" : ""}</span></div>
        <fieldset className="annotation-dialog__annotators"><legend>选择标注员</legend>{filtered.length === 0 ? <p>没有匹配的标注员</p> : filtered.map((item) => <label key={item.id}><input type="checkbox" aria-label={item.display_name || item.username} checked={selected.includes(item.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} />{item.display_name || item.username}</label>)}</fieldset>
        <label htmlFor="assignment-due-at">截止时间（可选）</label>
        <input id="assignment-due-at" type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} />
      </div>
      <footer className="annotation-dialog__footer"><button type="button" onClick={onClose}>取消</button><button type="button" className="ant-btn ant-btn-primary" disabled={loading || selected.length === 0} onClick={() => onSubmit({ annotator_ids: selected, sample_scope: sampleScope, ...(dueAt ? { due_at: new Date(dueAt).toISOString() } : {}) })}>确认指派</button></footer>
    </section>
  </div>;
}
