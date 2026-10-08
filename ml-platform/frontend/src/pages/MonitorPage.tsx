import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Card, Col, Progress, Row, Space, Spin, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";
import "./MonitorPage.css";

const { Text } = Typography;
const HISTORY_LENGTH = 30;

// Platform palette (matches App.tsx theme tokens).
const COLOR_OK = "#47C3A0";
const COLOR_WARN = "#D9AC52";
const COLOR_DANGER = "#E66F75";
const COLOR_ACCENT = "#2F9BF5";

interface ResourceMetric {
  usage_percent: number;
  total_gb?: number;
  used_gb?: number;
}

interface GpuMetric {
  util: number;
  memory_used_gb?: number;
  memory_total_gb?: number;
  temperature_c?: number;
}

interface LoadMetric {
  load1: number;
  load5: number;
  load15: number;
  cpu_cores: number;
}

interface NetIo {
  rx_bytes: number;
  tx_bytes: number;
}

interface DiskIo {
  read_bytes: number;
  write_bytes: number;
}

interface MonitorData {
  cpu: ResourceMetric;
  memory: ResourceMetric;
  disk: ResourceMetric;
  gpus: GpuMetric[];
  load: LoadMetric | null;
  net: NetIo | null;
  disk_io: DiskIo | null;
  uptime_seconds: number | null;
  timestamp: string | null;
}

interface MonitorHistory {
  cpu: number[];
  memory: number[];
  disk: number[];
  gpu: number[][];
  loadPct: number[];
  netDown: number[];
  netUp: number[];
  diskRead: number[];
  diskWrite: number[];
}

const EMPTY_HISTORY: MonitorHistory = {
  cpu: [], memory: [], disk: [], gpu: [], loadPct: [],
  netDown: [], netUp: [], diskRead: [], diskWrite: [],
};

function toGigaBytes(bytes: number): number {
  return bytes / (1024 * 1024 * 1024);
}

function levelColor(percent: number): string {
  if (percent > 80) return COLOR_DANGER;
  if (percent > 60) return COLOR_WARN;
  return COLOR_OK;
}

function formatRate(bytesPerSecond: number): string {
  if (!Number.isFinite(bytesPerSecond) || bytesPerSecond < 0) return "-";
  if (bytesPerSecond < 1024) return `${Math.round(bytesPerSecond)} B/s`;
  if (bytesPerSecond < 1024 * 1024) return `${(bytesPerSecond / 1024).toFixed(1)} KB/s`;
  if (bytesPerSecond < 1024 * 1024 * 1024) return `${(bytesPerSecond / 1024 / 1024).toFixed(1)} MB/s`;
  return `${(bytesPerSecond / 1024 / 1024 / 1024).toFixed(2)} GB/s`;
}

function formatUptime(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "-";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days} 天 ${hours} 小时`;
  if (hours > 0) return `${hours} 小时 ${minutes} 分`;
  return `${minutes} 分钟`;
}

function snapshotTimeMs(snapshot: any): number {
  const parsed = snapshot?.timestamp ? Date.parse(snapshot.timestamp) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

/* Bytes-per-second rate between two cumulative counter snapshots. */
function counterRate(prev: { value: number; timeMs: number } | null, value: number, timeMs: number) {
  if (!prev || timeMs <= prev.timeMs) return null;
  const delta = value - prev.value;
  if (delta < 0) return null; // counters reset (reboot) — skip the interval
  return (delta / (timeMs - prev.timeMs)) * 1000;
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const width = 220;
  const height = 46;
  if (values.length < 2) return null;
  const maxVal = Math.max(...values, 0.0001);
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * width;
    const y = height - (value / maxVal) * (height - 4) - 2;
    return { x, y };
  });
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${width},${height} L0,${height} Z`;
  return (
    <div className="monitor-spark">
      <svg width={width} height={height} aria-hidden="true">
        <path d={areaPath} fill={color} fillOpacity={0.12} />
        <path d={linePath} fill="none" stroke={color} strokeWidth={1.6} />
      </svg>
    </div>
  );
}

function MetricCard({ title, percent, stats, values, children, zone }: {
  title: string;
  percent: number;
  stats: string[];
  values: number[];
  children?: React.ReactNode;
  zone?: React.ReactNode;
}) {
  const color = percent >= 0 ? levelColor(percent) : COLOR_ACCENT;
  return (
    <Card className="monitor-metric">
      <div className="monitor-gauge-zone">
        {zone ?? (percent >= 0 && (
          <Progress type="dashboard" percent={Math.round(percent)} strokeColor={color} size={128} />
        ))}
      </div>
      <div className="monitor-metric-title">{title}</div>
      {children}
      {stats.map((line) => <div className="monitor-stat" key={line}>{line}</div>)}
      <Sparkline values={values} color={color} />
    </Card>
  );
}

function RatePair({ items }: { items: Array<{ glyph: string; label: string; value: string; color: string }> }) {
  return (
    <div className="monitor-rate">
      {items.map((item) => (
        <div key={item.label} className="monitor-rate-item">
          <div className="monitor-rate-value" style={{ color: item.color }}>{item.glyph} {item.value}</div>
          <div className="monitor-rate-label">{item.label}</div>
        </div>
      ))}
    </div>
  );
}

export default function MonitorPage() {
  const { t } = useI18n();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<MonitorData | null>(null);
  const [history, setHistory] = useState<MonitorHistory>(EMPTY_HISTORY);
  const [updatedAt, setUpdatedAt] = useState("");
  const prevNetRef = useRef<{ rx: number; tx: number; timeMs: number } | null>(null);
  const prevDiskRef = useRef<{ read: number; write: number; timeMs: number } | null>(null);

  const mapBackendResponse = (raw: any): MonitorData => ({
    cpu: { usage_percent: raw.cpu?.percent ?? 0 },
    memory: {
      usage_percent: raw.memory?.percent ?? 0,
      total_gb: raw.memory?.total_bytes ? toGigaBytes(raw.memory.total_bytes) : undefined,
      used_gb: raw.memory?.used_bytes ? toGigaBytes(raw.memory.used_bytes) : undefined,
    },
    disk: {
      usage_percent: raw.disk?.percent ?? 0,
      total_gb: raw.disk?.total ? toGigaBytes(raw.disk.total) : undefined,
      used_gb: raw.disk?.used ? toGigaBytes(raw.disk.used) : undefined,
    },
    gpus: Array.isArray(raw.gpu)
      ? raw.gpu.map((g: any) => ({
          util: g?.gpu_util ?? 0,
          memory_used_gb: g?.memory_used_mb != null ? (g.memory_used_mb) / 1024 : undefined,
          memory_total_gb: g?.memory_total_mb != null ? (g.memory_total_mb) / 1024 : undefined,
          temperature_c: g?.temperature_c,
        }))
      : [],
    load: raw.load ?? null,
    net: raw.net ?? null,
    disk_io: raw.disk_io ?? null,
    uptime_seconds: raw.uptime_seconds ?? null,
    timestamp: typeof raw.timestamp === "string" ? raw.timestamp : null,
  });

  // Backfill trend lines and I/O rates from the backend in-memory buffer so
  // charts survive page reloads instead of restarting from an empty array.
  const fetchHistory = useCallback(async () => {
    try {
      const res = await apiClient.get("/monitor/history", { params: { limit: 60 } });
      const items = Array.isArray(res.data) ? res.data : [];
      const backfilled: MonitorHistory = {
        cpu: [], memory: [], disk: [], gpu: [], loadPct: [],
        netDown: [], netUp: [], diskRead: [], diskWrite: [],
      };
      let prevNet: { rx: number; tx: number; timeMs: number } | null = null;
      let prevDisk: { read: number; write: number; timeMs: number } | null = null;
      for (const snapshot of items) {
        backfilled.cpu.push(snapshot?.cpu?.percent ?? 0);
        backfilled.memory.push(snapshot?.memory?.percent ?? 0);
        backfilled.disk.push(snapshot?.disk?.percent ?? 0);
        const load = snapshot?.load;
        backfilled.loadPct.push(load?.cpu_cores ? Math.min(100, (load.load1 / load.cpu_cores) * 100) : 0);
        const gpus = Array.isArray(snapshot?.gpu) ? snapshot.gpu : [];
        gpus.forEach((g: any, index: number) => {
          backfilled.gpu[index] = [...(backfilled.gpu[index] ?? []), g?.gpu_util ?? 0];
        });
        const timeMs = snapshotTimeMs(snapshot);
        const net = snapshot?.net;
        if (net && timeMs) {
          const down = prevNet ? counterRate({ value: prevNet.rx, timeMs: prevNet.timeMs }, net.rx_bytes ?? 0, timeMs) : null;
          const up = prevNet ? counterRate({ value: prevNet.tx, timeMs: prevNet.timeMs }, net.tx_bytes ?? 0, timeMs) : null;
          if (down != null && up != null) {
            backfilled.netDown.push(down);
            backfilled.netUp.push(up);
          }
          prevNet = { rx: net.rx_bytes ?? 0, tx: net.tx_bytes ?? 0, timeMs };
        }
        const diskIo = snapshot?.disk_io;
        if (diskIo && timeMs) {
          const read = prevDisk ? counterRate({ value: prevDisk.read, timeMs: prevDisk.timeMs }, diskIo.read_bytes ?? 0, timeMs) : null;
          const write = prevDisk ? counterRate({ value: prevDisk.write, timeMs: prevDisk.timeMs }, diskIo.write_bytes ?? 0, timeMs) : null;
          if (read != null && write != null) {
            backfilled.diskRead.push(read);
            backfilled.diskWrite.push(write);
          }
          prevDisk = { read: diskIo.read_bytes ?? 0, write: diskIo.write_bytes ?? 0, timeMs };
        }
      }
      const tail = items[items.length - 1];
      if (tail?.net && tail?.disk_io) {
        const timeMs = snapshotTimeMs(tail);
        if (timeMs) {
          prevNetRef.current = { rx: tail.net.rx_bytes ?? 0, tx: tail.net.tx_bytes ?? 0, timeMs };
          prevDiskRef.current = { read: tail.disk_io.read_bytes ?? 0, write: tail.disk_io.write_bytes ?? 0, timeMs };
        }
      }
      setHistory(backfilled);
    } catch {
      // History is a best-effort backfill; live polling keeps working without it.
    }
  }, []);

  const fetchData = useCallback(async () => {
    try {
      const res = await apiClient.get("/monitor/current");
      const mapped = mapBackendResponse(res.data);
      setData(mapped);
      setUpdatedAt(new Date().toLocaleTimeString());
      setHistory((prev) => {
        const next = {
          ...prev,
          cpu: [...prev.cpu.slice(-HISTORY_LENGTH + 1), mapped.cpu.usage_percent],
          memory: [...prev.memory.slice(-HISTORY_LENGTH + 1), mapped.memory.usage_percent],
          disk: [...prev.disk.slice(-HISTORY_LENGTH + 1), mapped.disk.usage_percent],
          loadPct: [...prev.loadPct.slice(-HISTORY_LENGTH + 1),
            mapped.load?.cpu_cores ? Math.min(100, (mapped.load.load1 / mapped.load.cpu_cores) * 100) : 0],
          gpu: mapped.gpus.length
            ? mapped.gpus.map((g, index) => [...(prev.gpu[index] ?? []).slice(-HISTORY_LENGTH + 1), g.util])
            : prev.gpu,
        };
        // Rates use server sampling timestamps; the client clock may drift
        // from the backend's buffered history.
        const parsedMs = mapped.timestamp ? Date.parse(mapped.timestamp) : Number.NaN;
        const nowMs = Number.isNaN(parsedMs) ? Date.now() : parsedMs;
        if (mapped.net && prevNetRef.current) {
          const prevNet = prevNetRef.current;
          const down = counterRate({ value: prevNet.rx, timeMs: prevNet.timeMs }, mapped.net.rx_bytes, nowMs);
          const up = counterRate({ value: prevNet.tx, timeMs: prevNet.timeMs }, mapped.net.tx_bytes, nowMs);
          if (down != null && up != null) {
            next.netDown = [...prev.netDown.slice(-HISTORY_LENGTH + 1), down];
            next.netUp = [...prev.netUp.slice(-HISTORY_LENGTH + 1), up];
          }
        }
        if (mapped.disk_io && prevDiskRef.current) {
          const prevDisk = prevDiskRef.current;
          const read = counterRate({ value: prevDisk.read, timeMs: prevDisk.timeMs }, mapped.disk_io.read_bytes, nowMs);
          const write = counterRate({ value: prevDisk.write, timeMs: prevDisk.timeMs }, mapped.disk_io.write_bytes, nowMs);
          if (read != null && write != null) {
            next.diskRead = [...prev.diskRead.slice(-HISTORY_LENGTH + 1), read];
            next.diskWrite = [...prev.diskWrite.slice(-HISTORY_LENGTH + 1), write];
          }
        }
        if (mapped.net) prevNetRef.current = { rx: mapped.net.rx_bytes, tx: mapped.net.tx_bytes, timeMs: nowMs };
        if (mapped.disk_io) prevDiskRef.current = { read: mapped.disk_io.read_bytes, write: mapped.disk_io.write_bytes, timeMs: nowMs };
        return next;
      });
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchHistory();
    void fetchData();
    const timer = window.setInterval(() => { void fetchData(); }, 3000);
    return () => window.clearInterval(timer);
  }, [fetchData, fetchHistory]);

  const gpus = data?.gpus ?? [];
  const load = data?.load ?? null;

  const metricCards = [
    { key: "cpu", title: t.monitor.cpu, metric: data?.cpu, values: history.cpu },
    { key: "memory", title: t.monitor.memory, metric: data?.memory, values: history.memory },
    { key: "disk", title: t.monitor.disk, metric: data?.disk, values: history.disk },
  ];
  const gpuCards = gpus.length
    ? gpus.map((gpu, index) => ({
        key: `gpu-${index}`,
        title: gpus.length > 1 ? `GPU ${index + 1}` : t.monitor.gpu,
        util: gpu.util,
        values: history.gpu[index] ?? [],
        gpu,
      }))
    : [{ key: "gpu", title: t.monitor.gpu, util: 0, values: [] as number[], gpu: null as GpuMetric | null }];

  if (loading) {
    return <AppLayout>
      <div className="monitor-page page-shell fade-in" style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: 300 }}>
        <Spin size="large" />
      </div>
    </AppLayout>;
  }

  return <AppLayout>
    <section className="monitor-page page-shell fade-in">
      <div className="page-header page-header--stacked">
        <div className="page-header-copy"><h3 className="page-title">{t.monitor.title}</h3></div>
        <Space direction="horizontal" size={16} align="center" wrap>
          {data?.uptime_seconds != null && (
            <Text type="secondary">{t.monitor.uptime}: {formatUptime(data.uptime_seconds)}</Text>
          )}
          {updatedAt && <Text type="secondary">{t.monitor.updated} {updatedAt}</Text>}
          <Button icon={<ReloadOutlined />} onClick={() => { void fetchHistory(); void fetchData(); }}>{t.monitor.refresh}</Button>
        </Space>
      </div>
      <Row gutter={[16, 16]} className="monitor-grid">
        {metricCards.map((card) => {
          const metric = card.metric as ResourceMetric | undefined;
          const percent = metric?.usage_percent ?? 0;
          const stats: string[] = [];
          if (metric?.total_gb != null) {
            stats.push(`${t.monitor.used} ${metric.used_gb?.toFixed(1)} / ${t.monitor.total} ${metric.total_gb?.toFixed(1)} GB`);
          }
          return <Col xs={24} sm={12} lg={6} key={card.key}>
            <MetricCard title={card.title} percent={percent} stats={stats} values={card.values} />
          </Col>;
        })}
        {gpuCards.map((card) => (
          <Col xs={24} sm={12} lg={6} key={card.key}>
            <MetricCard
              title={card.title}
              percent={card.util}
              stats={card.gpu?.temperature_c != null ? [`${t.monitor.temperature}: ${Math.round(card.gpu.temperature_c)}°C`] : card.gpu ? [] : [t.monitor.no_gpu]}
              values={card.values}
            >
              {card.gpu?.memory_total_gb != null && (
                <div className="monitor-stat">VRAM {card.gpu.memory_used_gb?.toFixed(1)} / {card.gpu.memory_total_gb?.toFixed(1)} GB</div>
              )}
            </MetricCard>
          </Col>
        ))}
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title={t.monitor.load}
            percent={load?.cpu_cores ? Math.min(100, (load.load1 / load.cpu_cores) * 100) : 0}
            stats={load ? [`1m ${load.load1} · 5m ${load.load5} · 15m ${load.load15}`] : []}
            values={history.loadPct}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title={t.monitor.net}
            percent={-1}
            stats={[]}
            values={history.netDown.map((down, i) => down + (history.netUp[i] ?? 0))}
            zone={
              <RatePair items={[
                { glyph: "↓", label: t.monitor.down, value: formatRate(history.netDown[history.netDown.length - 1] ?? Number.NaN), color: COLOR_OK },
                { glyph: "↑", label: t.monitor.up, value: formatRate(history.netUp[history.netUp.length - 1] ?? Number.NaN), color: COLOR_ACCENT },
              ]}/>
            }
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <MetricCard
            title={t.monitor.diskio}
            percent={-1}
            stats={[]}
            values={history.diskRead.map((read, i) => read + (history.diskWrite[i] ?? 0))}
            zone={
              <RatePair items={[
                { glyph: "↓", label: t.monitor.readOp, value: formatRate(history.diskRead[history.diskRead.length - 1] ?? Number.NaN), color: COLOR_OK },
                { glyph: "↑", label: t.monitor.writeOp, value: formatRate(history.diskWrite[history.diskWrite.length - 1] ?? Number.NaN), color: COLOR_WARN },
              ]}/>
            }
          />
        </Col>
      </Row>
    </section>
  </AppLayout>;
}
