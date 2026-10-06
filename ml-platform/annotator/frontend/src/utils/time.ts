// Backend timestamps are naive UTC (no timezone suffix). Parsing them with
// `new Date` directly treats them as local wall time (8h off in UTC+8).
export function parseBackendTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}
