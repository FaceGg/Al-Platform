import apiClient from "./client";

/** 质量监控 API（补齐路线第一批 F3，B1-03/04/05，技术方案 §9B）。
 *
 * 三页的所有数字都来自后端同一个聚合口径模块（D27）；前端不自行加总。
 */

export interface MonitorScopeParams {
  factory?: string;
  workshop?: string;
  production_line?: string;
  station_id?: string;
  scene_id?: string;
}

export interface StaleState {
  stale: boolean;
  last_production_at: string | null;
  hours: number | null;
  never_produced: boolean;
}

export interface TrendPoint {
  date: string;
  total: number;
  anomaly: number;
  alerts: number;
  high: number;
  critical: number;
  spc_exceed: number;
  closed: number;
  confirmed_ng: number;
  ng_rate: number | null;
}

export interface ParetoItem {
  key: string;
  label: string;
  count: number;
  ratio: number;
  cumulative: number;
}

export interface DashboardPayload {
  scope: MonitorScopeParams;
  window: { days: number; since: string; until: string };
  production: { total: number; ok: number; anomaly: number };
  alerts: {
    alerts_in_window: number; open: number; high_risk: number; sla_overdue: number;
    confirmed_ng: number; closed_in_window: number; by_severity: Record<string, number>;
    hit_rate: number | null;
  };
  disposition_ops: {
    per_thousand: number | null; mean_first_ack_seconds: number | null;
    acknowledged: number; closure_rate: number | null;
    closed_in_window: number; created_in_window: number;
  };
  trend: { points: TrendPoint[]; totals: Record<string, number | null> };
  recent: Array<{
    id: string; title: string; severity: string; source_type: string; status: string;
    created_at: string | null; station: string | null; occurrence_count: number;
  }>;
  station_ranking: Array<{
    station_id: string; station: string; alerts: number; open: number; high_risk: number; occurrences: number;
  }>;
  line_status: Array<{ line: string; stations: number; stations_with_open_alerts: number; offline_devices: number }>;
  stale: StaleState;
  generated_at: string;
}

export interface TrendsPayload {
  scope: MonitorScopeParams;
  window: { days: number; since: string; until: string };
  trend: { points: TrendPoint[]; totals: Record<string, number | null> };
  pareto: { dimension: string; total: number; items: ParetoItem[] };
  ng_vocabulary: Record<string, string>;
  stale: StaleState;
  generated_at: string;
}

export interface StationCard {
  station_id: string;
  code: string;
  name: string;
  scene: string | null;
  factory: string | null;
  workshop: string | null;
  production_line: string | null;
  responsible_user_id: string | null;
  product: string | null;
  batch: string | null;
  shift: string | null;
  last_production_at: string | null;
  result: string | null;
  score: number | null;
  predicted_label: string | null;
  shift_total: number;
  shift_anomaly: number;
  open_alerts: number;
  latest_alert: { id: string; title: string; severity: string; status: string; created_at: string | null } | null;
  device: { id: string; name: string; status: string; online: boolean; last_heartbeat: string | null } | null;
}

export interface StationsPayload {
  scope: MonitorScopeParams;
  now: string;
  shift: { label: string; start: string };
  cards: StationCard[];
  tree: Array<{ key: string; title: string; children: Array<{ key: string; title: string; open_alerts: number; device: StationCard["device"] }> }>;
  stale: StaleState;
}

export interface MonitorStreamEvent {
  type: "snapshot" | "alerts";
  dashboard?: DashboardPayload;
  events?: Array<{
    event_id: string; alert_id: string; action: string; from_status: string | null; to_status: string | null;
    note: string | null; created_at: string | null; title: string; severity: string; status: string; station_id: string | null;
  }>;
  counts?: { open: number; high_risk: number };
}

function scoped(path: string, scope: MonitorScopeParams) {
  const params: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(scope)) {
    if (value !== undefined && value !== null && value !== "") params[key] = value;
  }
  return { url: `/projects/${path}`, params };
}

const base = (projectId: string) => `${projectId}/quality-monitor`;

export async function getScopeOptions(projectId: string): Promise<{ factory: string[]; workshop: string[]; production_line: string[] }> {
  const res = await apiClient.get(`/projects/${base(projectId)}/scope-options`);
  return res.data;
}

export async function getDashboard(projectId: string, scope: MonitorScopeParams, days = 7): Promise<DashboardPayload> {
  // scoped() 已经带 /projects 前缀：这里不要再拼一次
  const { url, params } = scoped(base(projectId), scope);
  const res = await apiClient.get(`${url}/dashboard`, { params: { ...params, days } });
  return res.data;
}

export async function getTrends(
  projectId: string, scope: MonitorScopeParams, days: 7 | 30 | 90, dimension: string,
): Promise<TrendsPayload> {
  const { url, params } = scoped(base(projectId), scope);
  const res = await apiClient.get(`${url}/trends`, { params: { ...params, days, dimension } });
  return res.data;
}

export async function saveNgVocabulary(projectId: string, vocabulary: Record<string, string>): Promise<void> {
  await apiClient.put(`/projects/${base(projectId)}/ng-vocabulary`, { vocabulary });
}

export async function getStations(projectId: string, scope: MonitorScopeParams): Promise<StationsPayload> {
  const { url, params } = scoped(base(projectId), scope);
  const res = await apiClient.get(`${url}/stations`, { params });
  return res.data;
}

export async function ackReceived(projectId: string, stationId: string): Promise<{ acknowledged: number }> {
  const res = await apiClient.post(`/projects/${projectId}/quality-stations/${stationId}/ack-received`);
  return res.data;
}

export async function callQuality(projectId: string, stationId: string, reason: string): Promise<{ notified: number }> {
  const res = await apiClient.post(`/projects/${projectId}/quality-stations/${stationId}/call-quality`, { reason });
  return res.data;
}

export async function getDemoPresence(): Promise<{ present: boolean; projects: Array<{ id: string; name: string }> }> {
  const res = await apiClient.get("/demo-loop/presence");
  return res.data;
}

function querystring(scope: MonitorScopeParams) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(scope)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** 逐段解析 SSE 文本：按空行分帧，只取 data: 行。返回 [事件列表, 剩余未完成的文本]。 */
export function parseSseChunk(buffer: string): { events: MonitorStreamEvent[]; rest: string } {
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  const events: MonitorStreamEvent[] = [];
  for (const frame of frames) {
    for (const line of frame.split("\n")) {
      if (!line.startsWith("data:")) continue;
      try {
        events.push(JSON.parse(line.slice(5).trim()) as MonitorStreamEvent);
      } catch {
        // 单帧损坏不拖垮整条流：跳过
      }
    }
  }
  return { events, rest };
}

/**
 * 订阅监控推送流（SSE）。鉴权走请求头（不用原生 EventSource——那要把令牌放进 URL）。
 * 返回停止函数。流建立失败时调用 onFallback，由调用方降级为轮询。
 */
export function subscribeMonitorStream(
  projectId: string, scope: MonitorScopeParams,
  handlers: { onEvent: (event: MonitorStreamEvent) => void; onFallback: () => void },
): () => void {
  const controller = new AbortController();
  const token = localStorage.getItem("token");
  const run = async () => {
    try {
      const response = await fetch(`/api/projects/${base(projectId)}/stream${querystring(scope)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      });
      if (!response.ok || !response.body || typeof response.body.getReader !== "function") {
        handlers.onFallback();
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseChunk(buffer);
        buffer = parsed.rest;
        for (const event of parsed.events) handlers.onEvent(event);
      }
      // 服务端正常结束（例如代理超时断流）：降级轮询，保证页面继续刷新
      if (!controller.signal.aborted) handlers.onFallback();
    } catch {
      if (!controller.signal.aborted) handlers.onFallback();
    }
  };
  void run();
  return () => controller.abort();
}
