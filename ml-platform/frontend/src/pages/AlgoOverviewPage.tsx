import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ReloadOutlined, RocketOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import PageHeading from "../components/PageHeading";
import apiClient from "../api/client";
import { DASHBOARD_STATS_CHANGED } from "../events/dashboardStats";
import { useAdaptivePolling } from "../hooks/useAdaptivePolling";
import { useI18n } from "../i18n";
import { algorithmLabel } from "../utils/automlAlgorithms";
import { formatLocalTime } from "../utils/time";

interface DashStats {
  core_assets?: { total_datasets?: number; total_models?: number };
  business_stats?: {
    total_training_jobs?: number;
    total_api_calls?: number;
    successful_api_calls?: number;
  };
  model_status?: { training?: number; completed?: number; published?: number };
  /** 模型库各算法被多少个模型版本采用，按数量降序 */
  model_algorithm_coverage?: { name: string; count: number }[];
}

interface RecentModelVersion {
  id: string;
  model_name: string;
  version_number: number;
  algorithm?: string;
  metrics?: Record<string, unknown>;
  approval_status?: string;
  lifecycle_state?: string;
  published?: boolean;
  created_at?: string | null;
}

/** 与原全局仪表板一致：每 15 秒自动刷新；切回页面、其他页面改了数据时立即刷新 */
const REFRESH_INTERVAL_MS = 15_000;
const RECENT_VERSION_LIMIT = 6;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function metricOf(metrics: Record<string, unknown> | undefined, keys: string[]): string {
  // 顶层优先；集成、多输出版本的指标嵌在下一层（metrics.metrics、按目标列分组）
  const scopes = [metrics ?? {}, ...Object.values(metrics ?? {}).filter(isRecord)];
  for (const scope of scopes) {
    for (const key of keys) {
      const value = scope[key];
      if (typeof value === "number" && Number.isFinite(value)) return value.toFixed(3);
    }
  }
  return "-";
}

function versionStatus(version: RecentModelVersion, zh: boolean): { label: string; tone: string } {
  if (version.published) return { label: zh ? "已发布" : "Published", tone: "v2-bgo" };
  if (version.approval_status === "rejected") return { label: zh ? "已拒绝" : "Rejected", tone: "v2-br" };
  switch (version.lifecycle_state) {
    case "enabled": return { label: zh ? "已启用" : "Enabled", tone: "v2-bg" };
    case "disabled": return { label: zh ? "已停用" : "Disabled", tone: "v2-bp" };
    case "revoked": return { label: zh ? "已撤销" : "Revoked", tone: "v2-br" };
    case "archived": return { label: zh ? "已归档" : "Archived", tone: "v2-bp" };
    default: return { label: zh ? "待审批" : "Pending review", tone: "v2-bb" };
  }
}

export default function AlgoOverviewPage() {
  const navigate = useNavigate();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [stats, setStats] = useState<DashStats | null>(null);
  const [versions, setVersions] = useState<RecentModelVersion[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const requestSeq = useRef(0);

  // manual 只用于首屏与点「刷新」：后台自动刷新不转圈
  const load = useCallback(async (manual = false) => {
    const seq = ++requestSeq.current;
    if (manual) setLoading(true);
    try {
      const [nextStats, nextVersions] = await Promise.all([
        apiClient.get("/dashboard/stats").then((r) => r.data as DashStats).catch(() => null),
        apiClient.get("/dashboard/recent-model-versions", { params: { limit: RECENT_VERSION_LIMIT } })
          .then((r) => (Array.isArray(r.data?.items) ? r.data.items as RecentModelVersion[] : null))
          .catch(() => null),
      ]);
      // 轮询、切回页面、手动刷新可能并发：只采用最后发出的那次结果
      if (seq !== requestSeq.current) return;
      if (nextStats) setStats(nextStats);
      if (nextVersions) setVersions(nextVersions);
      setFailed(!nextStats || !nextVersions);
      if (nextStats && nextVersions) setUpdatedAt(new Date());
    } finally {
      if (manual) setLoading(false);
    }
  }, []);

  useEffect(() => { void load(true); }, [load]);

  useAdaptivePolling(() => {
    // 页面在后台时不刷新，切回时由 visibilitychange 立即补刷
    if (document.visibilityState === "hidden") return undefined;
    return load();
  }, { enabled: true, intervalMs: REFRESH_INTERVAL_MS, maxIntervalMs: REFRESH_INTERVAL_MS });

  useEffect(() => {
    const refresh = () => { void load(); };
    // 模型库、训练、自动建模等页面改了数据会发这个事件（其他标签页经 localStorage 同步）
    const refreshFromOtherTab = (event: StorageEvent) => {
      if (event.key === DASHBOARD_STATS_CHANGED) refresh();
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    window.addEventListener(DASHBOARD_STATS_CHANGED, refresh);
    window.addEventListener("storage", refreshFromOtherTab);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener(DASHBOARD_STATS_CHANGED, refresh);
      window.removeEventListener("storage", refreshFromOtherTab);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [load]);

  const algorithmText = (name: string | undefined) =>
    !name || name === "unknown" ? (zh ? "未标注算法" : "Unspecified") : algorithmLabel(name);
  const coverage = stats?.model_algorithm_coverage ?? [];
  const coverageTotal = coverage.reduce((sum, entry) => sum + entry.count, 0);
  const clock = updatedAt?.toLocaleTimeString(zh ? "zh-CN" : "en-GB", { hour12: false });

  const kpis = [
    {
      label: zh ? "数据集" : "Datasets",
      value: stats?.core_assets?.total_datasets ?? "—",
      hint: zh ? "可见数据资产" : "visible datasets",
      spark: [30, 55, 42, 70, 62, 88],
    },
    {
      label: zh ? "模型版本" : "Model versions",
      value: stats?.core_assets?.total_models ?? "—",
      hint: zh ? `训练中 ${stats?.model_status?.training ?? 0} · 已发布 ${stats?.model_status?.published ?? 0}` : `${stats?.model_status?.training ?? 0} training`,
      spark: [45, 38, 66, 58, 76, 80],
    },
    {
      label: zh ? "训练任务（累计）" : "Training jobs",
      value: stats?.business_stats?.total_training_jobs ?? "—",
      hint: zh ? `已完成模型 ${stats?.model_status?.completed ?? 0}` : `${stats?.model_status?.completed ?? 0} completed`,
      spark: [20, 48, 35, 60, 52, 67],
    },
    {
      label: zh ? "API 调用（累计）" : "API calls",
      value: stats?.business_stats?.total_api_calls?.toLocaleString?.() ?? "—",
      hint: zh
        ? `成功率 ${stats?.business_stats?.total_api_calls ? Math.round(((stats.business_stats.successful_api_calls ?? 0) / stats.business_stats.total_api_calls) * 1000) / 10 : "—"}%`
        : "platform total",
      spark: [50, 62, 48, 75, 83, 95],
    },
  ];

  return (
    <AppLayout>
      <PageHeading
        section="algo"
        navKey="dashboard"
        actions={(
          <>
            {clock ? (
              <span style={{ fontSize: 12, color: "var(--v2-dim)" }}>
                {zh ? `每 15 秒自动刷新 · 更新于 ${clock}` : `Auto-refresh every 15s · updated ${clock}`}
              </span>
            ) : null}
            <button type="button" className="v2-btn" onClick={() => { void load(true); }}>
              <ReloadOutlined spin={loading} />{zh ? "刷新" : "Refresh"}
            </button>
            <button type="button" className="v2-btn primary" onClick={() => navigate("/agent")}>
              <RocketOutlined />{zh ? "新建智能体任务" : "New agent job"}
            </button>
          </>
        )}
      />

      {failed ? (
        <div className="v2-note" style={{ marginBottom: 14 }}>注意：{zh ? "统计数据加载失败，将自动重试，也可点击刷新。" : "Failed to load stats; retrying automatically."}</div>
      ) : null}

      <div className="v2-kpis">
        {kpis.map((k) => (
          <div key={k.label} className="v2-kpi">
            <div className="lb">{k.label}</div>
            <div className="v">{k.value}</div>
            <div className="t">{k.hint}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 15, flexWrap: "wrap" }}>
        <div className="v2-panel" style={{ flex: "1.35", minWidth: 320 }}>
          <h4>
            <span className="bar" />{zh ? "最近模型版本" : "Recent model versions"}
            <span className="more" onClick={() => navigate("/models")}>{zh ? "模型库 ›" : "Library ›"}</span>
          </h4>
          {/* 名称或算法较长时在面板内横向滚动，不会盖到右侧面板 */}
          <div style={{ overflowX: "auto" }}>
            <table className="v2-table">
              <thead><tr>
                <th>{zh ? "模型" : "Model"}</th><th>{zh ? "算法" : "Algorithm"}</th>
                <th>F1</th><th>{zh ? "召回(少数类)" : "Recall (minority)"}</th><th>{zh ? "状态" : "Status"}</th>
              </tr></thead>
              <tbody>
                {versions.length === 0 ? (
                  <tr><td colSpan={5} className="v2-empty">{zh
                    ? "暂无模型版本 —— 训练完成后在「模型库」注册，即会显示在这里"
                    : "No model versions yet — register a trained model in the library"}</td></tr>
                ) : null}
                {versions.map((version) => {
                  const status = versionStatus(version, zh);
                  return (
                    <tr key={version.id}>
                      <td className="tt">
                        {version.model_name}
                        <div style={{ fontSize: 11, fontWeight: 400, color: "var(--v2-dim)" }}>
                          v{version.version_number} · {formatLocalTime(version.created_at)}
                        </div>
                      </td>
                      <td>{algorithmText(version.algorithm)}</td>
                      <td>{metricOf(version.metrics, ["f1", "test_f1", "best_f1"])}</td>
                      <td>{metricOf(version.metrics, ["recall_minority", "recall", "test_recall"])}</td>
                      <td><span className={`v2-badge ${status.tone}`} style={{ whiteSpace: "nowrap" }}>{status.label}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 280, display: "flex", flexDirection: "column", gap: 15 }}>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "模型状态" : "Model status"}</h4>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)", borderBottom: "1px dashed rgba(36,52,79,.6)" }}>
              <span>· {zh ? "训练中" : "Training"}</span><b style={{ color: "var(--v2-blue2)" }}>{stats?.model_status?.training ?? "—"}</b>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)", borderBottom: "1px dashed rgba(36,52,79,.6)" }}>
              <span>· {zh ? "已完成" : "Completed"}</span><b style={{ color: "var(--v2-green)" }}>{stats?.model_status?.completed ?? "—"}</b>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)" }}>
              <span>· {zh ? "已发布" : "Published"}</span><b style={{ color: "var(--v2-gold)" }}>{stats?.model_status?.published ?? "—"}</b>
            </div>
          </div>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "算法覆盖" : "Algorithm coverage"}
              <span className="more">{zh ? "按模型采用数排序" : "by model adoption"}</span></h4>
            <div style={{ fontSize: 11, color: "var(--v2-dim)", marginBottom: 8 }}>
              {zh ? "模型库中各算法被多少个模型版本采用（进度条为占全部版本的比例）"
                : "Model versions in the library per algorithm (bar = share of all versions)"}
            </div>
            {coverage.slice(0, 5).map((entry) => (
              <div key={entry.name} style={{ padding: "4px 0", fontSize: 12, color: "var(--v2-sub)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                  <span>{algorithmText(entry.name)}</span><span>{entry.count}</span>
                </div>
                <div style={{ height: 4, borderRadius: 2, background: "var(--v2-bg)", overflow: "hidden" }}>
                  <div style={{ height: "100%", borderRadius: 2, background: "linear-gradient(90deg, var(--v2-blue), var(--v2-blue2))", width: `${coverageTotal ? Math.round((entry.count / coverageTotal) * 100) : 0}%` }} />
                </div>
              </div>
            ))}
            {coverage.length === 0 ? (
              <div className="v2-empty" style={{ padding: "14px 0" }}>{zh ? "暂无数据" : "No data"}</div>
            ) : null}
          </div>
        </div>
      </div>

      <div className="v2-note" style={{ marginTop: 4 }}>{zh ? (
        <>重复建模流程可交给<b>智能体中心</b>：<a onClick={() => navigate("/agent")}>前往 →</a></>
      ) : (
        <>Repetitive modeling belongs to the <b>Agent Center</b>: <a onClick={() => navigate("/agent")}>open →</a></>
      )}</div>
    </AppLayout>
  );
}
