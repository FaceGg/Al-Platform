export type TaskStatusLanguage = "zh" | "en";

const STATUS_KEYS: Record<string, string> = {
  pending: "pending",
  queued: "queued",
  validating: "validating",
  running: "running",
  in_progress: "running",
  previewing: "running",
  preview_ready: "preview_ready",
  executing: "running",
  awaiting_annotation: "awaiting_annotation",
  awaiting_return: "awaiting_return",
  returned_pending_acceptance: "returned_pending_acceptance",
  accepted: "accepted",
  paused: "paused",
  archived: "archived",
  needs_review: "needs_review",
  cancel_requested: "cancel_requested",
  completed: "completed",
  finished: "completed",
  finished_successfully: "completed",
  failed: "failed",
  cancelled: "cancelled",
  canceled: "cancelled",
};

const LABELS = {
  zh: {
    pending: "待运行", queued: "排队中", validating: "校验中", running: "运行中",
    preview_ready: "预览就绪", awaiting_annotation: "待标注", awaiting_return: "待回传",
    returned_pending_acceptance: "待验收", accepted: "已验收", paused: "已暂停",
    archived: "已归档", needs_review: "待复核", cancel_requested: "取消中",
    completed: "已完成", failed: "失败", cancelled: "已取消",
  },
  en: {
    pending: "Pending", queued: "Queued", validating: "Validating", running: "Running",
    preview_ready: "Preview ready", awaiting_annotation: "Awaiting annotation",
    awaiting_return: "Awaiting return", returned_pending_acceptance: "Awaiting acceptance",
    accepted: "Accepted", paused: "Paused", archived: "Archived", needs_review: "Needs review",
    cancel_requested: "Cancelling", completed: "Completed", failed: "Failed", cancelled: "Cancelled",
  },
} as const;

const COLORS: Record<string, string> = {
  pending: "default", queued: "processing", validating: "processing", running: "blue",
  preview_ready: "success", awaiting_annotation: "blue", awaiting_return: "blue",
  returned_pending_acceptance: "warning", accepted: "success", paused: "warning",
  archived: "default", needs_review: "warning", cancel_requested: "warning",
  completed: "green", failed: "red", cancelled: "default",
};

export function normalizeTaskStatus(status: unknown): string {
  const raw = String(status || "pending").toLowerCase();
  return STATUS_KEYS[raw] || raw;
}

export function taskStatusLabel(status: unknown, lang: TaskStatusLanguage): string {
  const normalized = normalizeTaskStatus(status);
  const language = lang === "en" ? "en" : "zh";
  return LABELS[language][normalized as keyof typeof LABELS.zh] || String(status || "pending");
}

export function taskStatusColor(status: unknown): string {
  return COLORS[normalizeTaskStatus(status)] || "default";
}
