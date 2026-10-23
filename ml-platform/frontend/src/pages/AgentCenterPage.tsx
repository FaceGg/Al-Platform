import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ReloadOutlined, RocketOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

interface AgentJob {
  id: number | string;
  name?: string;
  task_name?: string;
  status?: string;
  state?: string;
  progress?: number;
  created_at?: string;
  updated_at?: string;
  project_id?: number | string;
  project_name?: string;
}

type TabId = "jobs" | "wizard" | "recipes";

const statusBadge = (status: string): string => {
  const s = status.toLowerCase();
  if (["running", "progressing"].some((k) => s.includes(k))) return "v2-bb";
  if (["completed", "succeeded", "done"].some((k) => s.includes(k))) return "v2-bg";
  if (["failed", "error", "cancelled"].some((k) => s.includes(k))) return "v2-br";
  if (["queued", "pending", "waiting"].some((k) => s.includes(k))) return "v2-bgo";
  return "v2-bgray";
};

function relativeTime(iso?: string, zh = true): string {
  if (!iso) return "-";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return zh ? "刚刚" : "just now";
  if (minutes < 60) return zh ? `${minutes} 分钟前` : `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return zh ? `${hours} 小时前` : `${hours}h ago`;
  return zh ? `${Math.round(hours / 24)} 天前` : `${Math.round(hours / 24)}d ago`;
}

export default function AgentCenterPage() {
  const navigate = useNavigate();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [tab, setTab] = useState<TabId>("jobs");
  const [jobs, setJobs] = useState<AgentJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const loadJobs = () => {
    setLoading(true);
    setError("");
    apiClient.get("/training/automl/jobs").then((res) => {
      const items = Array.isArray(res.data?.items) ? res.data.items : Array.isArray(res.data) ? res.data : [];
      setJobs(items);
    }).catch(() => {
      setJobs([]);
      setError(zh ? "任务列表加载失败" : "Failed to load jobs");
    }).finally(() => setLoading(false));
  };

  useEffect(() => { loadJobs(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const kpis = useMemo(() => {
    const running = jobs.filter((j) => statusBadge(String(j.status ?? j.state ?? "")) === "v2-bb").length;
    const done = jobs.filter((j) => statusBadge(String(j.status ?? j.state ?? "")) === "v2-bg").length;
    return [
      { label: zh ? "任务总数" : "Total jobs", value: jobs.length },
      { label: zh ? "运行中" : "Running", value: running },
      { label: zh ? "已完成" : "Completed", value: done },
      { label: zh ? "配方" : "Recipes", value: "—" },
    ];
  }, [jobs, zh]);

  const wizardSteps = [
    { n: 1, title: zh ? "选择项目与数据" : "Project & data", desc: zh ? "选择项目与数据集版本；平台自动完成确定性画像（S1）。" : "Pick project and dataset version; S1 deterministic profiling runs automatically." },
    { n: 2, title: zh ? "确认目标与门禁" : "Target & gates", desc: zh ? "确认预测目标、S4 硬门禁指标与验收阈值，LLM 只能收紧不能放宽。" : "Confirm target, S4 hard gates and acceptance thresholds; LLM may only tighten." },
    { n: 3, title: zh ? "选择算法强度" : "Search strength", desc: zh ? "fast / standard / ultra 三档搜索空间，或启用大模型全自主迭代（四步循环）。" : "fast / standard / ultra search space, or the LLM-driven four-step loop." },
    { n: 4, title: zh ? "启动全自动迭代" : "Launch", desc: zh ? "沙箱执行特征脚本，双门禁验收，产物沉淀配方与经验，S5 一键服务化。" : "Sandboxed feature scripts, dual-gate acceptance, recipes and experience, S5 serving." },
  ];

  return (
    <AppLayout>
      <div className="v2-pagehead">
        <div>
          <h2>🤖 {zh ? "智能体中心" : "Agent Center"}</h2>
          <div className="v2-pdesc">{zh
            ? "大模型驱动的自动建模 Agent：四步向导 · 任务全链路 · 配方固化复用 · 经验越用越强"
            : "LLM-driven modeling agent: wizard, job pipeline, versioned recipes, accumulated experience"}</div>
        </div>
        <button type="button" className="v2-btn primary" onClick={() => navigate("/automl")}>
          <RocketOutlined />{zh ? "新建智能体建模任务" : "New agent job"}
        </button>
      </div>

      <div className="v2-kpis">
        {kpis.map((k) => (
          <div key={k.label} className="v2-kpi">
            <div className="lb">{k.label}</div>
            <div className="v">{k.value}</div>
          </div>
        ))}
      </div>

      <div className="v2-subtabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "jobs"} className={`v2-subtab${tab === "jobs" ? " on" : ""}`} onClick={() => setTab("jobs")}>
          {zh ? "智能体任务" : "Jobs"}
        </button>
        <button type="button" role="tab" aria-selected={tab === "wizard"} className={`v2-subtab${tab === "wizard" ? " on" : ""}`} onClick={() => setTab("wizard")}>
          {zh ? "建模向导" : "Wizard"}
        </button>
        <button type="button" role="tab" aria-selected={tab === "recipes"} className={`v2-subtab${tab === "recipes" ? " on" : ""}`} onClick={() => setTab("recipes")}>
          {zh ? "配方库" : "Recipes"}
        </button>
      </div>

      {tab === "jobs" && (
        <div className="v2-panel">
          <h4>
            <span className="bar" />{zh ? "全部自动建模任务" : "All modeling jobs"}
            <span className="more" style={{ display: "flex", alignItems: "center", gap: 6 }} onClick={loadJobs} role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter") loadJobs(); }}>
              <ReloadOutlined spin={loading} />{zh ? "刷新" : "Refresh"}
            </span>
          </h4>
          <table className="v2-table">
            <thead><tr>
              <th>{zh ? "任务" : "Job"}</th><th>{zh ? "状态" : "Status"}</th>
              <th>{zh ? "进度" : "Progress"}</th><th>{zh ? "更新时间" : "Updated"}</th>
              <th>{zh ? "操作" : "Actions"}</th>
            </tr></thead>
            <tbody>
              {error ? <tr><td colSpan={5} className="v2-empty">{error}</td></tr> : null}
              {!error && jobs.length === 0 ? (
                <tr><td colSpan={5} className="v2-empty">{zh
                  ? "暂无任务 —— 点击右上「新建智能体建模任务」，四步向导即可启动全自动迭代"
                  : "No jobs yet — start the wizard to launch a fully automated run"}</td></tr>
              ) : null}
              {jobs.map((job) => {
                const status = String(job.status ?? job.state ?? "-");
                const progress = typeof job.progress === "number" ? Math.round(job.progress) : null;
                return (
                  <tr key={String(job.id)}>
                    <td className="tt">{job.name ?? job.task_name ?? String(job.id)}</td>
                    <td><span className={`v2-badge ${statusBadge(status)}`}>{status}</span></td>
                    <td>{progress != null ? `${progress}%` : "-"}</td>
                    <td>{relativeTime(job.updated_at ?? job.created_at, zh)}</td>
                    <td><a onClick={() => navigate(`/automl/task/${job.id}`)}>{zh ? "全链路档案 ›" : "Details ›"}</a></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {tab === "wizard" && (
        <>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "四步向导 · 全自动建模迭代" : "Four-step wizard"}</h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
              {wizardSteps.map((s) => (
                <div key={s.n} style={{ background: "var(--v2-bg)", border: "1px solid var(--v2-line)", borderRadius: 10, padding: "12px 14px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <span style={{ width: 24, height: 24, borderRadius: "50%", border: "1.5px solid var(--v2-blue)", color: "var(--v2-blue2)", display: "grid", placeItems: "center", fontSize: 12 }}>{s.n}</span>
                    <b style={{ color: "var(--v2-txt)", fontSize: 13 }}>{s.title}</b>
                  </div>
                  <div style={{ fontSize: 12, color: "var(--v2-sub)" }}>{s.desc}</div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button type="button" className="v2-btn primary" onClick={() => navigate("/automl")}>
                <RocketOutlined />{zh ? "启动向导" : "Launch wizard"}
              </button>
              <button type="button" className="v2-btn ghost" onClick={() => navigate("/knowledge-center")}>
                {zh ? "先逛知识中心" : "Browse knowledge center"}
              </button>
            </div>
          </div>
          <div className="v2-note">💡 {zh
            ? "向导在「自动建模」页内完成配置与提交；本页负责任务总览与全链路档案查看。"
            : "Configuration and submission happen on the AutoML page; this center tracks jobs and archives."}</div>
        </>
      )}

      {tab === "recipes" && (
        <>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "配方库（Pipeline Recipe）" : "Recipe library"}</h4>
            <div className="v2-empty">
              {zh ? "配方服务化接口接入中 —— 验收通过的建模配方（特征脚本 + 建模配置 + 门禁 + 评审记录）将在此版本化展示，支持回滚与复用。"
                : "Recipe serving APIs are being wired — accepted recipes (feature script + config + gates + review) will appear here with versioning, rollback and reuse."}
            </div>
          </div>
          <div className="v2-note">🧪 {zh
            ? "配方在后端已随 P3 交付（版本化 / 回滚 / delta 复用 / 换模跟随），列表 API 接入后此处立即呈现。"
            : "Backend recipes landed with P3 (versioning, rollback, delta reuse); the list lands here once the API is wired."}</div>
        </>
      )}
    </AppLayout>
  );
}
