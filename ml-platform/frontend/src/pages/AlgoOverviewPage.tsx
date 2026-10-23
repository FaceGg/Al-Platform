import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ReloadOutlined, RocketOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

interface DashStats {
  core_assets?: { total_datasets?: number; total_models?: number };
  business_stats?: {
    total_training_jobs?: number;
    total_api_calls?: number;
    successful_api_calls?: number;
  };
  model_status?: { training?: number; completed?: number; published?: number };
  algorithm_coverage?: { name: string; count: number }[];
}

interface TopModel {
  id: string;
  name: string;
  framework?: string;
  backbone?: string;
  metrics?: Record<string, number>;
  status?: string;
}

function metricOf(metrics: Record<string, number> | undefined, keys: string[]): string {
  for (const key of keys) {
    const value = metrics?.[key];
    if (typeof value === "number") return value.toFixed(3);
  }
  return "-";
}

export default function AlgoOverviewPage() {
  const navigate = useNavigate();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [stats, setStats] = useState<DashStats | null>(null);
  const [models, setModels] = useState<TopModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([
      apiClient.get("/dashboard/stats").then((r) => r.data as DashStats).catch(() => null),
      apiClient.get("/dashboard/top-models").then((r) => (Array.isArray(r.data?.items) ? r.data.items : [])).catch(() => []),
    ]).then(([s, m]) => {
      if (!s) setFailed(true);
      else { setFailed(false); setStats(s); }
      setModels(m as TopModel[]);
    }).finally(() => setLoading(false));
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

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
      <div className="v2-crumb">{zh ? "算法平台 / " : "Algorithms / "}<b>{zh ? "建模总览" : "Overview"}</b></div>
      <div className="v2-pagehead">
        <div>
          <h2>{zh ? "建模总览" : "Modeling overview"}</h2>
          <div className="v2-pdesc">{zh
            ? "原全局仪表板收拢为算法平台首页：数据、建模、服务化状态一屏总览。"
            : "The former global dashboard, consolidated as the algorithm platform home."}</div>
        </div>
        <div style={{ display: "flex", gap: 9 }}>
          <button type="button" className="v2-btn" onClick={load}>
            <ReloadOutlined spin={loading} />{zh ? "刷新" : "Refresh"}
          </button>
          <button type="button" className="v2-btn primary" onClick={() => navigate("/agent")}>
            <RocketOutlined />{zh ? "新建智能体任务" : "New agent job"}
          </button>
        </div>
      </div>

      {failed ? (
        <div className="v2-note" style={{ marginBottom: 14 }}>⚠ {zh ? "统计数据加载失败，请刷新重试。" : "Failed to load stats."}</div>
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
            <span className="bar" />{zh ? "最近模型版本" : "Top model versions"}
            <span className="more" onClick={() => navigate("/models")}>{zh ? "模型库 ›" : "Library ›"}</span>
          </h4>
          <table className="v2-table">
            <thead><tr>
              <th>{zh ? "模型" : "Model"}</th><th>{zh ? "算法" : "Algorithm"}</th>
              <th>F1</th><th>{zh ? "召回(少数类)" : "Recall (minority)"}</th><th>{zh ? "状态" : "Status"}</th>
            </tr></thead>
            <tbody>
              {models.length === 0 ? (
                <tr><td colSpan={5} className="v2-empty">{zh
                  ? "暂无模型版本 —— 从「自动建模」或智能体向导开始第一次训练"
                  : "No model versions yet"}</td></tr>
              ) : null}
              {models.slice(0, 6).map((m) => (
                <tr key={m.id}>
                  <td className="tt">{m.name}</td>
                  <td>{m.backbone ?? m.framework ?? "-"}</td>
                  <td>{metricOf(m.metrics, ["f1", "test_f1", "best_f1"])}</td>
                  <td>{metricOf(m.metrics, ["recall_minority", "recall", "test_recall"])}</td>
                  <td><span className={`v2-badge ${m.status === "published" ? "v2-bg" : "v2-bb"}`}>{m.status ?? "-"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ flex: 1, minWidth: 280, display: "flex", flexDirection: "column", gap: 15 }}>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "模型状态" : "Model status"}</h4>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)", borderBottom: "1px dashed rgba(36,52,79,.6)" }}>
              <span>● {zh ? "训练中" : "Training"}</span><b style={{ color: "var(--v2-blue2)" }}>{stats?.model_status?.training ?? "—"}</b>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)", borderBottom: "1px dashed rgba(36,52,79,.6)" }}>
              <span>● {zh ? "已完成" : "Completed"}</span><b style={{ color: "var(--v2-green)" }}>{stats?.model_status?.completed ?? "—"}</b>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)" }}>
              <span>● {zh ? "已发布" : "Published"}</span><b style={{ color: "var(--v2-gold)" }}>{stats?.model_status?.published ?? "—"}</b>
            </div>
          </div>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "算法覆盖" : "Algorithm coverage"}</h4>
            {(stats?.algorithm_coverage ?? []).slice(0, 5).map((entry) => (
              <div key={entry.name} style={{ padding: "4px 0", fontSize: 12, color: "var(--v2-sub)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                  <span>{entry.name}</span><span>{entry.count}</span>
                </div>
                <div style={{ height: 4, borderRadius: 2, background: "var(--v2-bg)", overflow: "hidden" }}>
                  <div style={{ height: "100%", borderRadius: 2, background: "linear-gradient(90deg, var(--v2-blue), var(--v2-blue2))", width: `${Math.min(100, entry.count * 12)}%` }} />
                </div>
              </div>
            ))}
            {(stats?.algorithm_coverage ?? []).length === 0 ? (
              <div className="v2-empty" style={{ padding: "14px 0" }}>{zh ? "暂无数据" : "No data"}</div>
            ) : null}
          </div>
        </div>
      </div>

      <div className="v2-note" style={{ marginTop: 4 }}>💡 {zh ? (
        <>重复建模流程可交给<b>智能体中心</b>：<a onClick={() => navigate("/agent")}>前往 →</a></>
      ) : (
        <>Repetitive modeling belongs to the <b>Agent Center</b>: <a onClick={() => navigate("/agent")}>open →</a></>
      )}</div>
    </AppLayout>
  );
}
