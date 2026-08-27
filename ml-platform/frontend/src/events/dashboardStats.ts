export const DASHBOARD_STATS_CHANGED = "platform:dashboard-stats-changed";

export function notifyDashboardStatsChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(DASHBOARD_STATS_CHANGED));
  try {
    window.localStorage.setItem("platform:dashboard-stats-changed", String(Date.now()));
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}
