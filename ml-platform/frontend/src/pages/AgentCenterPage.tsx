import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ReloadOutlined, RocketOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import OptReportPanel from "../components/OptReportPanel";
import RecipeRow from "../components/RecipeRow";
import apiClient from "../api/client";
import { useI18n } from "../i18n";
import {
  getAgentRun,
  listAgentRuns,
  listPipelineRecipes,
  type AgentRunDetail,
  type AgentRunItem,
  type PipelineRecipeItem,
} from "../api/agentCenter";
import AgentModelingWizard from "../components/AgentModelingWizard";

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

type TabId = "wizard" | "tasks" | "recipes" | "knowledge";

const activeChipStyle: React.CSSProperties = { color: "#fff", background: "rgba(47,155,245,.22)", borderColor: "rgba(92,178,255,.45)" };

const statusBadge = (status: string): string => {
  const s = status.toLowerCase();
  if (["running", "progressing"].some((k) => s.includes(k))) return "v2-bb";
  if (["completed", "succeeded", "done"].some((k) => s.includes(k))) return "v2-bg";
  if (["failed", "error", "cancelled"].some((k) => s.includes(k))) return "v2-br";
  if (["queued", "pending", "waiting"].some((k) => s.includes(k))) return "v2-bgo";
  return "v2-bgray";
};

function relativeTime(iso?: string | null, zh = true): string {
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
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab = (["wizard", "tasks", "recipes", "knowledge"] as const).includes(searchParams.get("tab") as TabId)
    ? (searchParams.get("tab") as TabId) : "wizard";
  const [tab, setTab] = useState<TabId>(initialTab);
  const switchTab = (next: TabId) => {
    setTab(next);
    setSearchParams(next === "wizard" ? {} : { tab: next }, { replace: true });
  };
  const [jobs, setJobs] = useState<AgentJob[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [jobSource, setJobSource] = useState<"automl" | "agent">("automl");
  const [agentRuns, setAgentRuns] = useState<AgentRunItem[]>([]);
  const [agentRunsError, setAgentRunsError] = useState("");
  const [archiveRunId, setArchiveRunId] = useState<string | null>(null);
  const [archive, setArchive] = useState<AgentRunDetail | null>(null);
  const [archiveError, setArchiveError] = useState("");
  const [recipes, setRecipes] = useState<PipelineRecipeItem[]>([]);
  const [recipesError, setRecipesError] = useState("");

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

  const loadAgentData = () => {
    listAgentRuns().then(setAgentRuns).catch(() => {
      setAgentRuns([]);
      setAgentRunsError(zh ? "Agent 运行列表加载失败" : "Failed to load agent runs");
    });
    listPipelineRecipes().then(setRecipes).catch(() => {
      setRecipes([]);
      setRecipesError(zh ? "配方列表加载失败" : "Failed to load recipes");
    });
  };

  const openArchive = (runId: string) => {
    if (archiveRunId === runId) { setArchiveRunId(null); setArchive(null); return; }
    setArchiveRunId(runId);
    setArchive(null);
    setArchiveError("");
    getAgentRun(runId).then(setArchive).catch(() => {
      setArchive(null);
      setArchiveError(zh ? "档案加载失败" : "Failed to load archive");
    });
  };

  useEffect(() => { loadJobs(); loadAgentData(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const kpis = useMemo(() => {
    const running = jobs.filter((j) => statusBadge(String(j.status ?? j.state ?? "")) === "v2-bb").length;
    const done = jobs.filter((j) => statusBadge(String(j.status ?? j.state ?? "")) === "v2-bg").length;
    return [
      { label: zh ? "AutoML 任务" : "AutoML jobs", value: jobs.length },
      { label: zh ? "运行中" : "Running", value: running },
      { label: zh ? "Agent 运行" : "Agent runs", value: agentRuns.length },
      { label: zh ? "配方" : "Recipes", value: recipes.length },
    ];
  }, [jobs, agentRuns, recipes, zh]);

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
        <button type="button" role="tab" aria-selected={tab === "wizard"} className={`v2-subtab${tab === "wizard" ? " on" : ""}`} onClick={() => switchTab("wizard")}>
          🧭 {zh ? "新建向导" : "Wizard"}
        </button>
        <button type="button" role="tab" aria-selected={tab === "tasks"} className={`v2-subtab${tab === "tasks" ? " on" : ""}`} onClick={() => switchTab("tasks")}>
          📋 {zh ? "任务列表" : "Jobs"}
        </button>
        <button type="button" role="tab" aria-selected={tab === "recipes"} className={`v2-subtab${tab === "recipes" ? " on" : ""}`} onClick={() => switchTab("recipes")}>
          📚 {zh ? "配方库" : "Recipes"}
        </button>
        <button type="button" role="tab" aria-selected={tab === "knowledge"} className={`v2-subtab${tab === "knowledge" ? " on" : ""}`} onClick={() => switchTab("knowledge")}>
          🧠 {zh ? "知识中心" : "Knowledge"}
        </button>
      </div>

      {tab === "tasks" && (
        <div className="v2-panel">
          <h4>
            <span className="bar" />{jobSource === "automl" ? (zh ? "全部自动建模任务" : "All modeling jobs") : (zh ? "Agent 运行记录" : "Agent runs")}
            <span style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 10 }}>
              <button
                type="button"
                className={`v2-lang${jobSource === "automl" ? " on" : ""}`}
                style={jobSource === "automl" ? activeChipStyle : undefined}
                onClick={() => setJobSource("automl")}
              >{zh ? "AutoML 任务" : "AutoML"}</button>
              <button
                type="button"
                className={`v2-lang${jobSource === "agent" ? " on" : ""}`}
                style={jobSource === "agent" ? activeChipStyle : undefined}
                onClick={() => setJobSource("agent")}
              >{zh ? "Agent 运行" : "Agent"}</button>
            </span>
            <span className="more" style={{ display: "flex", alignItems: "center", gap: 6 }} onClick={() => (jobSource === "automl" ? loadJobs() : loadAgentData())} role="button" tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter") jobSource === "automl" ? loadJobs() : loadAgentData(); }}>
              <ReloadOutlined spin={loading} />{zh ? "刷新" : "Refresh"}
            </span>
          </h4>
          {jobSource === "automl" ? (
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
          ) : (
            <table className="v2-table">
              <thead><tr>
                <th>{zh ? "运行" : "Run"}</th><th>{zh ? "项目" : "Project"}</th><th>{zh ? "目标列" : "Target"}</th>
                <th>{zh ? "状态" : "Status"}</th><th>{zh ? "阶段/轮次" : "Stage/Rounds"}</th>
                <th>{zh ? "Token" : "Tokens"}</th><th>{zh ? "更新时间" : "Updated"}</th>
              </tr></thead>
              <tbody>
                {agentRunsError ? <tr><td colSpan={7} className="v2-empty">{agentRunsError}</td></tr> : null}
                {!agentRunsError && agentRuns.length === 0 ? (
                  <tr><td colSpan={7} className="v2-empty">{zh
                    ? "暂无 Agent 运行记录 —— Agent 任务由智能体建模主线创建（AutoML 绑定全链接入中），P2 真实收敛验证已在拧紧/电焊两域跑通全链"
                    : "No agent runs yet — agent jobs are created by the modeling agent mainline (AutoML binding in progress); P2 convergence was verified on both real domains"}</td></tr>
                ) : null}
                {agentRuns.map((run) => (
                  <tr key={run.id} style={{ cursor: "pointer" }} onClick={() => openArchive(run.id)}>
                    <td className="tt" title={run.id}>{run.id.slice(0, 8)}…</td>
                    <td>{run.project_name ?? "-"}</td>
                    <td className="tt">{run.target_column ?? "-"}</td>
                    <td>
                      <span className={`v2-badge ${statusBadge(run.status)}`}>{run.status}</span>
                      {run.error_code ? <span style={{ marginLeft: 6, fontSize: 11, color: "var(--v2-dim)" }}>{run.error_code}</span> : null}
                    </td>
                    <td>{run.current_stage.toUpperCase()} · {zh ? "轮" : "r"}{run.round_count}</td>
                    <td>{run.token_used.toLocaleString()}</td>
                    <td>{relativeTime(run.updated_at ?? run.created_at, zh)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {jobSource === "agent" && archiveRunId && (
            <div style={{ marginTop: 12, border: "1px solid var(--v2-line)", borderRadius: 10, background: "var(--v2-bg)", padding: "12px 14px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
                <b style={{ color: "var(--v2-txt)", fontSize: 13 }}>{zh ? "运行档案" : "Run archive"}</b>
                <span className="v2-badge v2-bgray">{archiveRunId.slice(0, 8)}</span>
                {archive ? (
                  <>
                    <span className={`v2-badge ${statusBadge(archive.status)}`}>{archive.status}</span>
                    {archive.llm_model_id ? <span className="v2-badge v2-bp">{archive.llm_model_id}</span> : null}
                    <span style={{ fontSize: 11, color: "var(--v2-dim)" }}>
                      {archive.token_used.toLocaleString()}{archive.token_budget ? ` / ${archive.token_budget.toLocaleString()}` : ""} tokens · {zh ? "轮" : "rounds "}{archive.round_count}
                    </span>
                  </>
                ) : null}
                <span style={{ marginLeft: "auto", cursor: "pointer", color: "var(--v2-dim)", fontSize: 12 }} onClick={() => { setArchiveRunId(null); setArchive(null); }}>✕</span>
              </div>
              {archiveError ? <div className="v2-empty" style={{ padding: 12 }}>{archiveError}</div> : null}
              {!archive && !archiveError ? <div className="v2-empty" style={{ padding: 12 }}>{zh ? "档案加载中…" : "Loading…"}</div> : null}
              {archive ? (
                <>
                <div className="v2-timeline">
                  {(archive.memory_json?.rounds ?? []).map((round) => (
                    <div key={round.round} className="v2-tl-item run">
                      <div className="tt">{zh ? `第 ${round.round} 轮` : `Round ${round.round}`}
                        {round.verdict ? <span className={`v2-badge ${round.verdict === "gate_failed" ? "v2-br" : "v2-bgo"}`} style={{ marginLeft: 8 }}>{round.verdict}</span> : null}
                      </div>
                      {(round.s2_attempts ?? []).map((attempt) => (
                        <div key={attempt.attempt} className="ts" style={{ color: attempt.ok ? "var(--v2-green)" : "var(--v2-gold)" }}>
                          · S2 {zh ? "尝试" : "attempt"} {attempt.attempt}: {attempt.ok ? (zh ? "通过沙箱" : "sandbox OK") : (attempt.error ?? "failed")}
                          {Array.isArray(attempt.detail) && attempt.detail.length ? ` (${attempt.detail.slice(0, 3).join("; ")})` : ""}
                        </div>
                      ))}
                      {(round.hints ?? []).length ? (
                        <div className="ts" style={{ marginTop: 3 }}>
                          {zh ? "评审建议：" : "Hints: "}{(round.hints ?? []).slice(0, 3).map((hint, i) => (
                            <span key={i} style={{ display: "block", color: "var(--v2-sub)" }}>{i + 1}. {hint.length > 90 ? hint.slice(0, 90) + "…" : hint}</span>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                  {(archive.memory_json?.rounds ?? []).length === 0 ? (
                    <div className="v2-tl-item"><div className="tt">{zh ? "暂无轮次记录" : "No recorded rounds"}</div></div>
                  ) : null}
                  <div className={`v2-tl-item ${archive.status === "waiting_escalate" ? "warn" : "ok"}`}>
                    <div className="tt">{zh ? "终态：" : "Final: "}{archive.status}{archive.error_code ? ` · ${archive.error_code}` : ""}</div>
                    <div className="ts">{relativeTime(archive.updated_at ?? archive.created_at, zh)}</div>
                  </div>
                </div>
                <OptReportPanel resultJson={archive.result_json} zh={zh} />
                </>
              ) : null}
            </div>
          )}
        </div>
      )}

      {tab === "wizard" && (
        <>
          <AgentModelingWizard onSubmitted={() => { loadAgentData(); }} />
          <div className="v2-note" style={{ marginTop: 10 }}>💡 {zh
            ? "提交即归档 UserGuidance（第四契约）并创建智能体任务；执行引擎接线随 AutoML worker 绑定后自动开始迭代。"
            : "Submission archives the guidance contract and creates the run; the engine starts once the worker binding lands."}</div>
        </>
      )}

      {tab === "recipes" && (
        <>
          <div className="v2-panel">
            <h4>
              <span className="bar" />{zh ? "配方库（Pipeline Recipe）" : "Recipe library"}
              <span className="more" onClick={loadAgentData} role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter") loadAgentData(); }}>
                <ReloadOutlined />{zh ? "刷新" : "Refresh"}
              </span>
            </h4>
            {recipesError ? <div className="v2-empty">{recipesError}</div> : null}
            {!recipesError && recipes.length === 0 ? (
              <div className="v2-empty">
                {zh ? "暂无已固化的配方 —— 验收通过的建模任务将配方（特征脚本 + 建模配置 + 门禁 + 评审记录）自动固化到此处，版本化可回滚、换模跟随复用。"
                  : "No recipes yet — accepted modeling runs persist their recipes here with versioning, rollback and swap-following reuse."}
              </div>
            ) : null}
            {recipes.length > 0 ? (
              <table className="v2-table">
                <thead><tr>
                  <th>{zh ? "配方" : "Recipe"}</th><th>{zh ? "项目" : "Project"}</th>
                  <th>{zh ? "域" : "Domain"}</th><th>{zh ? "目标列" : "Target"}</th>
                  <th>{zh ? "版本" : "Version"}</th><th>{zh ? "状态" : "Status"}</th>
                  <th>{zh ? "变更说明" : "Change note"}</th><th>{zh ? "更新时间" : "Updated"}</th>
                  <th>{zh ? "操作" : "Actions"}</th>
                </tr></thead>
                <tbody>
                  {recipes.map((recipe) => (
                    <RecipeRow key={recipe.id} recipe={recipe} zh={zh} onChanged={loadAgentData} />
                  ))}
                </tbody>
              </table>
            ) : null}
          </div>
          <div className="v2-note">🧪 {zh
            ? "验收通过的任务在档案页一键固化配方；版本树支持展开与 git 式回滚（回滚=发新版本携带旧内容）；delta 复用与换模跟随复用走服务化链路。"
            : "Accepted runs fixate their recipe from the archive panel; version tree supports expand and git-style rollback; delta reuse and swap-following ride the servitization chain."}</div>
        </>
      )}

      {tab === "knowledge" && (
        <>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "知识中心（知识库 + 平台经验合并）" : "Knowledge center"}</h4>
            <div style={{ fontSize: 12.5, color: "var(--v2-sub)", lineHeight: 2 }}>
              {zh ? "一个入口管理全部知识：用户上传的工艺文档/标准/法规 + 系统自动管理的「平台经验」分区；S1 分析与 AI 对话统一检索全部绑定库。"
                : "One entry for uploaded documents and the platform experience partition; S1 and chat share the unified retrieval."}
            </div>
            <button type="button" className="v2-btn primary" style={{ marginTop: 10 }} onClick={() => navigate("/knowledge-center")}>
              {zh ? "进入知识中心 →" : "Open knowledge center →"}
            </button>
          </div>
          <div className="v2-note">🧠 {zh
            ? "完整知识中心（绑定配置/经验分区/检索引用）在独立页面维护；此处为智能体中心的合并入口。"
            : "The full center lives on its own page; this is the merged agent-center entry."}</div>
        </>
      )}
    </AppLayout>
  );
}
