import { useEffect, useState } from "react";
import { Drawer, Select } from "antd";
import type { AnnotatorSubject, SampleScope } from "../api/annotatorAssignments";

interface Props {
  open: boolean;
  taskRevision: number;
  sampleScope: SampleScope;
  annotators: AnnotatorSubject[];
  assignedIds?: string[];
  overlapWarning?: string | null;
  loading?: boolean;
  onClose: () => void;
  onSubmit: (payload: { annotator_ids: string[]; sample_scope: SampleScope; due_at?: string }) => void;
}

export default function AssignmentDialog({ open, taskRevision, sampleScope, annotators, assignedIds = [], overlapWarning, loading = false, onClose, onSubmit }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [dueAt, setDueAt] = useState("");

  useEffect(() => {
    if (!open) {
      setSelected([]);
      setDueAt("");
    }
  }, [open]);

  const sampleIds = sampleScope.kind === "ids" ? (sampleScope.sample_ids ?? []) : [];
  const nameOf = (subjectId: string) => {
    const subject = annotators.find((item) => item.id === subjectId);
    return (subject?.display_name || subject?.username) || `${subjectId.slice(0, 8)}…`;
  };
  const assignable = annotators.filter((item) => !assignedIds.includes(item.id));
  const assignedNames = assignedIds.map(nameOf);

  if (!open) return null;
  return <Drawer open={open} placement="right" width="min(560px, 100vw)" title="指派任务" onClose={onClose}
    footer={<div className="annotation-dialog__footer"><button type="button" onClick={onClose}>取消</button><button type="button" className="ant-btn ant-btn-primary" disabled={loading || selected.length === 0} onClick={() => onSubmit({ annotator_ids: selected, sample_scope: sampleScope, ...(dueAt ? { due_at: new Date(dueAt).toISOString() } : {}) })}>确认指派</button></div>}
  >
    <div className="annotation-dialog__body">
      <p>任务修订 {taskRevision} · {sampleScope.kind === "ids" ? `固定样本 ${sampleIds.length} 条` : "任务冻结范围"}</p>
      <label htmlFor="assignment-annotators">选择标注员</label>
      <Select
        id="assignment-annotators"
        mode="multiple"
        showSearch
        placeholder="搜索并选择已审核通过的标注员"
        value={selected}
        onChange={setSelected}
        options={assignable.map((item) => ({ value: item.id, label: item.display_name || item.username, email: item.email || "" }))}
        optionRender={(option) => {
          const subject = assignable.find((item) => item.id === option.value);
          return (
            <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.4 }}>
              <span style={{ fontWeight: 600 }}>{String(option.label ?? "")}</span>
              <span style={{ fontSize: 12, color: "rgba(0, 0, 0, 0.45)" }}>
                {subject?.email ? `${subject.email} · ` : ""}已审核通过 · 已授权本项目
              </span>
            </div>
          );
        }}
        filterOption={(input, option) => {
          const needle = input.trim().toLowerCase();
          if (!needle) return true;
          const subject = assignable.find((item) => item.id === option?.value);
          const haystack = `${option?.label ?? ""} ${subject?.email ?? ""}`.toLowerCase();
          return haystack.includes(needle);
        }}
        style={{ width: "100%" }}
        notFoundContent={loading ? "标注员加载中…" : (assignable.length === 0 && assignedIds.length > 0 ? "该项目标注员均已指派" : "没有匹配的标注员")}
      />
      {!loading && annotators.length === 0 && <p role="note" className="annotation-dialog__warning">该项目暂无已授权标注员，请先在用户管理 → 标注员管理中完成项目授权</p>}
      {assignedIds.length > 0 && (
        <div className="annotation-dialog__assigned" style={{ border: "1px solid #e5e7eb", borderRadius: 6, padding: "8px 12px", marginBottom: 12, display: "flex", flexDirection: "column", gap: 4 }}>
          <strong style={{ fontSize: 13 }}>已指派标注员（{assignedNames.length}）</strong>
          <span style={{ fontSize: 12, color: "rgba(0, 0, 0, 0.65)" }}>{assignedNames.join("、")}</span>
        </div>
      )}
      {overlapWarning && <p role="alert" className="annotation-dialog__warning">{overlapWarning}</p>}
      <div className="annotation-dialog__scope" aria-label="指派范围摘要"><strong>指派范围</strong><span>{sampleScope.kind === "ids" ? `${sampleScope.kind} · ${sampleIds.slice(0, 5).join(", ")}${sampleIds.length > 5 ? " …" : ""}` : "frozen_task_scope · 服务端冻结样本"}</span></div>
      <label htmlFor="assignment-due-at">截止时间（可选）</label>
      <input id="assignment-due-at" type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} />
    </div>
  </Drawer>;
}
