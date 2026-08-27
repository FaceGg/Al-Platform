export type TaskStatusLanguage = "zh" | "en";

const STATUS_KEYS: Record<string, string> = {
  pending: "pending",
  queued: "queued",
  validating: "validating",
  running: "running",
  in_progress: "running",
  cancel_requested: "cancel_requested",
  completed: "completed",
  finished: "completed",
  finished_successfully: "completed",
  failed: "failed",
  cancelled: "cancelled",
  canceled: "cancelled",
};

const LABELS = {
  zh: { pending: "待运行", queued: "排队中", validating: "校验中", running: "运行中", cancel_requested: "取消中", completed: "已完成", failed: "失败", cancelled: "已取消" },
  en: { pending: "Pending", queued: "Queued", validating: "Validating", running: "Running", cancel_requested: "Cancelling", completed: "Completed", failed: "Failed", cancelled: "Cancelled" },
} as const;

const COLORS: Record<string, string> = {
  pending: "default", queued: "processing", validating: "processing", running: "blue",
  cancel_requested: "warning", completed: "green", failed: "red", cancelled: "default",
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
