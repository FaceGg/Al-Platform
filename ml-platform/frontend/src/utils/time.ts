export function parseBackendTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatLocalTime(value: string | null | undefined, withSeconds = false): string {
  const parsed = parseBackendTime(value);
  if (!parsed) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", ...(withSeconds ? { second: "2-digit" } : {}), hour12: false,
  }).format(parsed).replace(/\//g, "-");
}
