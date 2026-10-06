import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";
import { useTheme } from "../stores/themeContext";
import "./MonitorPage.css";

const HISTORY_LENGTH = 30;

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

interface MonitorData {
  cpu: ResourceMetric;
  memory: ResourceMetric;
  disk: ResourceMetric;
  gpus: GpuMetric[];
}

interface MonitorHistory {
  cpu: number[];
  memory: number[];
  disk: number[];
  gpu: number[][];
}

const EMPTY_HISTORY: MonitorHistory = { cpu: [], memory: [], disk: [], gpu: [] };

function toGigaBytes(bytes: number): number {
  return bytes / (1024 * 1024 * 1024);
}

const LEVEL_COLORS = {
  dark: { ok: "#47e0c2", warn: "#f5b942", danger: "#ff5f6e" },
  light: { ok: "#0da48a", warn: "#c07f14", danger: "#d94350" },
};

function levelColor(percent: number, theme: "light" | "dark"): { main: string; state: "" | "warn" | "danger" } {
  const palette = LEVEL_COLORS[theme];
  if (percent > 80) return { main: palette.danger, state: "danger" };
  if (percent > 60) return { main: palette.warn, state: "warn" };
  return { main: palette.ok, state: "" };
}

/* 260° arc gauge with tick ring, glowing value arc and centered readout. */
function HudGauge({ percent, color, idPrefix }: { percent: number; color: string; idPrefix: string }) {
  const radius = 78;
  const circumference = 2 * Math.PI * radius;
  const arcLength = circumference * (260 / 360);
  const clamped = Math.max(0, Math.min(100, percent));
  const visible = arcLength * (clamped / 100);
  const ticks = useMemo(() => Array.from({ length: 27 }, (_, i) => {
    const angle = 140 + (i * 260) / 26;
    const major = i % 5 === 0;
    return { angle, major };
  }), []);
  return (
    <div className="hud-gauge-wrap">
      <svg width={168} height={128} viewBox="0 0 200 200" aria-hidden="true"
        style={{ transform: "translateY(-14px)" }}>
        <defs>
          <linearGradient id={`${idPrefix}-arc`} x1="0%" y1="100%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={color} stopOpacity={0.55} />
            <stop offset="100%" stopColor={color} />
          </linearGradient>
        </defs>
        <g transform="rotate(140 100 100)">
          <circle cx={100} cy={100} r={radius} fill="none"
            style={{ stroke: "var(--hud-track)" }} strokeWidth={9}
            strokeDasharray={`${arcLength} ${circumference - arcLength}`} strokeLinecap="round" />
          <circle cx={100} cy={100} r={radius} fill="none"
            stroke={`url(#${idPrefix}-arc)`} strokeWidth={9}
            strokeDasharray={`${visible} ${circumference}`}
            strokeLinecap="round"
            style={{
              transition: "stroke-dasharray 0.9s ease",
              filter: `drop-shadow(0 0 6px ${color})`,
            }} />
          {ticks.map((tick, index) => (
            <line key={index} x1={100} y1={16} x2={100} y2={tick.major ? 26 : 22}
              style={{ stroke: tick.major ? "var(--hud-tick)" : "var(--hud-tick-minor)" }}
              strokeWidth={tick.major ? 2 : 1}
              transform={`rotate(${tick.angle} 100 100)`} />
          ))}
        </g>
      </svg>
      <div className="hud-gauge-value" style={{ color }}>{Math.round(clamped)}<span style={{ fontSize: 15 }}>%</span></div>
      <div className="hud-gauge-unit">LOAD</div>
    </div>
  );
}

/* Glowing trend line with gradient area fill. */
function HudSparkline({ values, color, idPrefix }: { values: number[]; color: string; idPrefix: string }) {
  const width = 220;
  const height = 52;
  if (values.length < 2) return null;
  const maxVal = Math.max(...values, 5);
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * width;
    const y = height - (value / (maxVal || 1)) * (height - 4) - 2;
    return { x, y };
  });
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${width},${height} L0,${height} Z`;
  return (
    <div className="hud-spark">
      <svg width={width} height={height} aria-hidden="true">
        <defs>
          <linearGradient id={`${idPrefix}-area`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <path d={areaPath} fill={`url(#${idPrefix}-area)`} />
        <path d={linePath} fill="none" stroke={color} strokeWidth={1.6}
          style={{ filter: `drop-shadow(0 0 4px ${color})` }} />
        {points.map((p, index) => (
          <circle key={index} cx={p.x} cy={p.y} r={1.8} fill={color} />
        ))}
      </svg>
    </div>
  );
}

function HudCard({ idPrefix, title, percent, stats, values, extra, theme }: {
  idPrefix: string;
  title: string;
  percent: number;
  stats: string[];
  values: number[];
  extra?: string[];
  theme: "light" | "dark";
}) {
  const { main, state } = levelColor(percent, theme);
  return (
    <div className={`hud-card${state ? ` hud-card--${state}` : ""}`}>
      <HudGauge percent={percent} color={main} idPrefix={idPrefix} />
      <div className="hud-card-title">{title}</div>
      {stats.map((line) => <div className="hud-stat" key={line}>{line}</div>)}
      {extra?.map((line) => <div className="hud-stat" key={line}>{line}</div>)}
      <HudSparkline values={values} color={main} idPrefix={idPrefix} />
    </div>
  );
}

export default function MonitorPage() {
  const { t } = useI18n();
  const { theme } = useTheme();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<MonitorData | null>(null);
  const [history, setHistory] = useState<MonitorHistory>(EMPTY_HISTORY);
  const [clock, setClock] = useState(() => new Date());
  const [updatedAt, setUpdatedAt] = useState<string>("--:--:--");

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
  });

  // Backfill trend lines from the backend in-memory buffer so charts survive
  // page reloads instead of restarting from an empty client-side array.
  const fetchHistory = useCallback(async () => {
    try {
      const res = await apiClient.get("/monitor/history", { params: { limit: 60 } });
      const items = Array.isArray(res.data) ? res.data : [];
      const backfilled: MonitorHistory = { cpu: [], memory: [], disk: [], gpu: [] };
      for (const snapshot of items) {
        backfilled.cpu.push(snapshot?.cpu?.percent ?? 0);
        backfilled.memory.push(snapshot?.memory?.percent ?? 0);
        backfilled.disk.push(snapshot?.disk?.percent ?? 0);
        const gpus = Array.isArray(snapshot?.gpu) ? snapshot.gpu : [];
        gpus.forEach((g: any, index: number) => {
          backfilled.gpu[index] = [...(backfilled.gpu[index] ?? []), g?.gpu_util ?? 0];
        });
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
      setHistory((prev) => ({
        cpu: [...prev.cpu.slice(-HISTORY_LENGTH + 1), mapped.cpu.usage_percent],
        memory: [...prev.memory.slice(-HISTORY_LENGTH + 1), mapped.memory.usage_percent],
        disk: [...prev.disk.slice(-HISTORY_LENGTH + 1), mapped.disk.usage_percent],
        gpu: mapped.gpus.length
          ? mapped.gpus.map((g, index) => [...(prev.gpu[index] ?? []).slice(-HISTORY_LENGTH + 1), g.util])
          : prev.gpu,
      }));
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
    const clockTimer = window.setInterval(() => setClock(new Date()), 1000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(clockTimer);
    };
  }, [fetchData, fetchHistory]);

  const metricCards = [
    { key: "cpu", title: t.monitor.cpu, metric: data?.cpu, values: history.cpu },
    { key: "memory", title: t.monitor.memory, metric: data?.memory, values: history.memory },
    { key: "disk", title: t.monitor.disk, metric: data?.disk, values: history.disk },
  ];
  const gpus = data?.gpus ?? [];
  const gpuCards = gpus.length
    ? gpus.map((gpu, index) => ({
        key: `gpu-${index}`,
        title: gpus.length > 1 ? `GPU ${index + 1}` : t.monitor.gpu,
        metric: gpu,
        values: history.gpu[index] ?? [],
      }))
    : [{ key: "gpu", title: t.monitor.gpu, metric: null, values: [] }];
  const cards = [...metricCards, ...gpuCards];

  if (loading) {
    return <AppLayout>
      <div className="monitor-page page-shell fade-in" style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: 300 }}>
        <div style={{ fontFamily: "ui-monospace, Consolas, monospace", letterSpacing: "0.3em", color: "#2b9ad8" }}>INITIALIZING…</div>
      </div>
    </AppLayout>;
  }

  return <AppLayout>
    <section className="monitor-page page-shell fade-in">
      <div className={`hud-console${theme === "light" ? " hud-console--light" : ""}`}>
        <div className="hud-scanline" />
        <div className="hud-header">
          <div>
            <div className="hud-kicker">System Monitor // Realtime</div>
            <h3 className="hud-title">{t.monitor.title}</h3>
          </div>
          <div className="hud-header-right">
            <span className="hud-live"><span className="hud-live-dot" />LIVE</span>
            <span className="hud-clock">{clock.toLocaleTimeString("en-GB")}</span>
            <Button className="hud-refresh" icon={<ReloadOutlined />}
              onClick={() => { void fetchHistory(); void fetchData(); }}>{t.monitor.refresh}</Button>
          </div>
        </div>
        <div className="hud-grid">
          {cards.map((card) => {
            const isGpuCard = card.key === "gpu" || card.key.startsWith("gpu-");
            const gpuMetric = isGpuCard ? (card.metric as GpuMetric | null) : null;
            const baseMetric = isGpuCard ? undefined : (card.metric as ResourceMetric | undefined);
            const percent = gpuMetric ? gpuMetric.util : baseMetric?.usage_percent ?? 0;
            const stats: string[] = [];
            if (baseMetric?.total_gb != null) {
              stats.push(`${t.monitor.used} ${baseMetric.used_gb?.toFixed(1)} / ${t.monitor.total} ${baseMetric.total_gb?.toFixed(1)} GB`);
            }
            const extra: string[] = [];
            if (gpuMetric?.temperature_c != null) {
              extra.push(`${t.monitor.temperature}: ${Math.round(gpuMetric.temperature_c)}°C`);
            }
            if (gpuMetric?.memory_total_gb != null) {
              extra.push(`VRAM ${gpuMetric.memory_used_gb?.toFixed(1)} / ${gpuMetric.memory_total_gb?.toFixed(1)} GB`);
            }
            if (card.key === "gpu" && !gpuMetric) {
              extra.push(t.monitor.no_gpu);
            }
            return <HudCard
              key={card.key}
              idPrefix={`hud-${card.key}`}
              title={card.title}
              percent={percent}
              stats={stats}
              extra={extra}
              values={card.values}
              theme={theme}
            />;
          })}
        </div>
        <div className="hud-footer">
          <span>SAMPLING 3s · BUFFER 120 · SOURCE HOST-0</span>
          <span>UPDATED {updatedAt}</span>
        </div>
      </div>
    </section>
  </AppLayout>;
}
