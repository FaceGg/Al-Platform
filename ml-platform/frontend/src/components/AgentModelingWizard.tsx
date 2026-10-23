import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { App as AntApp } from "antd";
import apiClient from "../api/client";
import { getDatasetPreview, listDatasets } from "../api/datasets";
import { AUTOML_ALGORITHM_IDS } from "../pages/AutoMLPage";
import { useI18n } from "../i18n";

export type WizardStep = 1 | 2 | 3 | 4;

type SearchStrength = "light" | "medium" | "high" | "ultra";
type TimeBudget = 1800 | 3600 | 7200 | 14400;

interface DatasetOption { id: string; name?: string; filename?: string }
interface ProjectOption { id: string; name?: string }

const STRENGTH_OPTIONS: { value: SearchStrength; label: string; desc: string }[] = [
  { value: "light", label: "快速 light", desc: "最小搜索空间，几分钟出结果，适合首跑验证" },
  { value: "medium", label: "标准 medium", desc: "均衡搜索空间与时间（推荐）" },
  { value: "high", label: "深度 high", desc: "全空间展开，适合精调" },
  { value: "ultra", label: "极致 ultra", desc: "恒等全空间，最长时间" },
];

const TIME_OPTIONS: { value: TimeBudget; label: string }[] = [
  { value: 1800, label: "30 分钟" },
  { value: 3600, label: "60 分钟" },
  { value: 7200, label: "120 分钟" },
  { value: 14400, label: "240 分钟" },
];

function requestIdentifier(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function AgentModelingWizard() {
  const navigate = useNavigate();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { message } = AntApp.useApp();

  const [step, setStep] = useState<WizardStep>(1);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState("");
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [targetColumn, setTargetColumn] = useState("");
  const [taskType, setTaskType] = useState<"classification" | "regression">("classification");
  const [strength, setStrength] = useState<SearchStrength>("medium");
  const [timeBudget, setTimeBudget] = useState<TimeBudget>(3600);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiClient.get("/projects").then((res) => {
      const items = Array.isArray(res.data) ? res.data : res.data?.items;
      setProjects(Array.isArray(items) ? items : []);
    }).catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    setDatasets([]);
    setDatasetId("");
    if (!projectId) return;
    listDatasets(projectId).then((items) => setDatasets(Array.isArray(items) ? items : [])).catch(() => setDatasets([]));
  }, [projectId]);

  useEffect(() => {
    setColumns([]);
    setTargetColumn("");
    if (!datasetId) return;
    getDatasetPreview(datasetId).then((data) => {
      const cols: string[] = Array.isArray(data.columns)
        ? data.columns.filter((c: unknown): c is string => typeof c === "string")
        : [];
      setColumns(cols);
      const preferred = ["label", "DECIDE(判定（最终判定）（0-不合格，1-合格）)", "fault"];
      setTargetColumn(preferred.find((name) => cols.includes(name)) ?? "");
    }).catch(() => setColumns([]));
  }, [datasetId]);

  const datasetName = useMemo(
    () => datasets.find((d) => d.id === datasetId)?.name ?? datasets.find((d) => d.id === datasetId)?.filename ?? datasetId,
    [datasets, datasetId],
  );
  const projectName = useMemo(() => projects.find((p) => p.id === projectId)?.name ?? projectId, [projects, projectId]);
  const inputColumns = useMemo(() => columns.filter((c) => c !== targetColumn), [columns, targetColumn]);

  const stepStatus = (n: WizardStep): "on" | "done" | "" => (n === step ? "on" : n < step ? "done" : "");
  const canNext = step === 1 ? Boolean(projectId && datasetId) : step === 2 ? Boolean(targetColumn) : true;

  const submit = async () => {
    if (!projectId || !datasetId || !targetColumn) return;
    setSubmitting(true);
    setError("");
    try {
      const experiment = await apiClient.post("/experiments", {
        project_id: projectId,
        name: `agent-wizard-${Date.now()}`,
        description: zh ? "智能体中心四步向导创建" : "Created by the agent center wizard",
      });
      const experimentId = experiment.data?.id;
      if (!experimentId) throw new Error(zh ? "实验创建失败" : "experiment creation failed");
      const res = await apiClient.post("/training/automl/run", {
        project_id: projectId,
        experiment_id: experimentId,
        dataset_artifact_id: datasetId,
        input_columns: inputColumns,
        algorithm_ids: [...AUTOML_ALGORITHM_IDS],
        search_method: "bayesian",
        time_budget: timeBudget,
        search_strength: strength,
        class_weight: true,
        cross_validation_enabled: true,
        cross_validation_folds: 5,
        task: taskType,
        target_column: targetColumn,
      }, {
        headers: { "Idempotency-Key": requestIdentifier(), "X-Request-ID": requestIdentifier() },
      });
      const runId = res.data?.run_id || res.data?.id || res.data?.job_id;
      if (!runId) throw new Error(zh ? "任务创建失败" : "run creation failed");
      navigate(`/automl/task/${runId}`);
    } catch (e: any) {
      const detail = e?.response?.data?.detail?.message || e?.response?.data?.detail || e?.message;
      setError(String(detail || (zh ? "提交失败" : "submission failed")));
      setSubmitting(false);
    }
  };

  const steps = [
    { n: 1 as WizardStep, title: zh ? "选择项目与数据" : "Project & data", hint: zh ? "数据集将自动画像" : "auto profiling" },
    { n: 2 as WizardStep, title: zh ? "确认目标" : "Target", hint: zh ? "预测目标与任务类型" : "target & task" },
    { n: 3 as WizardStep, title: zh ? "选择算法强度" : "Strength", hint: zh ? "搜索空间与时长" : "space & budget" },
    { n: 4 as WizardStep, title: zh ? "启动" : "Launch", hint: zh ? "确认提交" : "confirm" },
  ];

  return (
    <div className="v2-panel">
      <div className="v2-steps" role="tablist" aria-label={zh ? "向导步骤" : "Wizard steps"}>
        {steps.map((s) => (
          <button key={s.n} type="button" className={`v2-step ${stepStatus(s.n)}`}
            onClick={() => s.n < step && setStep(s.n)}>
            <span className="n">{s.n < step ? "✓" : s.n}</span>
            <span><span className="tt">{s.title}</span><br /><span className="st">{s.hint}</span></span>
          </button>
        ))}
      </div>

      {step === 1 && (
        <div>
          <div className="v2-form-row">
            <span style={{ color: "var(--v2-sub)", minWidth: 70 }}>{zh ? "项目" : "Project"}</span>
            <select className="v2-select" value={projectId} onChange={(e) => setProjectId(e.target.value)}
              aria-label={zh ? "选择项目" : "Select project"}>
              <option value="">{zh ? "— 选择项目 —" : "— select —"}</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name ?? p.id}</option>)}
            </select>
          </div>
          <div className="v2-form-row">
            <span style={{ color: "var(--v2-sub)", minWidth: 70 }}>{zh ? "数据集" : "Dataset"}</span>
            <select className="v2-select" value={datasetId} onChange={(e) => setDatasetId(e.target.value)}
              disabled={!projectId} aria-label={zh ? "选择数据集" : "Select dataset"}>
              <option value="">{zh ? "— 选择数据集 —" : "— select —"}</option>
              {datasets.map((d) => <option key={d.id} value={d.id}>{d.name ?? d.filename ?? d.id}</option>)}
            </select>
          </div>
          {projectId && datasets.length === 0 ? (
            <div className="v2-note">📂 {zh ? "该项目暂无数据集——请先在「算法平台 → 数据管理」上传。" : "No datasets in this project yet."}</div>
          ) : null}
        </div>
      )}

      {step === 2 && (
        <div>
          <div className="v2-form-row">
            <span style={{ color: "var(--v2-sub)", minWidth: 70 }}>{zh ? "目标列" : "Target"}</span>
            <select className="v2-select" value={targetColumn} onChange={(e) => setTargetColumn(e.target.value)}
              aria-label={zh ? "选择目标列" : "Select target column"}>
              <option value="">{zh ? "— 选择目标列 —" : "— select —"}</option>
              {columns.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="v2-form-row">
            <span style={{ color: "var(--v2-sub)", minWidth: 70 }}>{zh ? "任务类型" : "Task"}</span>
            <div className="v2-radio-cards" style={{ flex: 1 }}>
              <button type="button" className={`v2-radio-card${taskType === "classification" ? " on" : ""}`} onClick={() => setTaskType("classification")}>
                <b>{zh ? "分类" : "Classification"}</b>
                <span>{zh ? "预测类别（合格/不合格、故障类型）" : "predict a class"}</span>
              </button>
              <button type="button" className={`v2-radio-card${taskType === "regression" ? " on" : ""}`} onClick={() => setTaskType("regression")}>
                <b>{zh ? "回归" : "Regression"}</b>
                <span>{zh ? "预测连续值（扭矩、尺寸）" : "predict a value"}</span>
              </button>
            </div>
          </div>
          <div className="v2-note">🛡 {zh
            ? `输入特征默认为其余 ${inputColumns.length} 列；S4 硬门禁（少数类召回 ≥0.90）先于 LLM 评审，不可放宽。`
            : `Inputs default to the other ${inputColumns.length} columns; hard gates run before any LLM review.`}</div>
        </div>
      )}

      {step === 3 && (
        <div>
          <div className="v2-radio-cards" style={{ marginBottom: 12 }}>
            {STRENGTH_OPTIONS.map((opt) => (
              <button key={opt.value} type="button" className={`v2-radio-card${strength === opt.value ? " on" : ""}`}
                onClick={() => setStrength(opt.value)}>
                <b>{opt.label}</b><span>{opt.desc}</span>
              </button>
            ))}
          </div>
          <div className="v2-form-row">
            <span style={{ color: "var(--v2-sub)", minWidth: 70 }}>{zh ? "时长上限" : "Budget"}</span>
            <select className="v2-select" value={timeBudget} onChange={(e) => setTimeBudget(Number(e.target.value) as TimeBudget)}
              aria-label={zh ? "选择时长上限" : "Select time budget"}>
              {TIME_OPTIONS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          <div className="v2-note">⚙ {zh
            ? "算法族默认启用全族（LightGBM/XGBoost/CatBoost/GBDT/RF/ET/HGB/MLP），贝叶斯搜索 + 5 折交叉验证 + 类别加权。"
            : "All algorithm families enabled by default; bayesian search, 5-fold CV, class weighting."}</div>
        </div>
      )}

      {step === 4 && (
        <div>
          <table className="v2-table">
            <tbody>
              <tr><td>{zh ? "项目" : "Project"}</td><td className="tt">{projectName}</td></tr>
              <tr><td>{zh ? "数据集" : "Dataset"}</td><td className="tt">{datasetName}</td></tr>
              <tr><td>{zh ? "目标列" : "Target"}</td><td className="tt">{targetColumn}</td></tr>
              <tr><td>{zh ? "任务" : "Task"}</td><td className="tt">{taskType === "classification" ? (zh ? "分类" : "Classification") : (zh ? "回归" : "Regression")}</td></tr>
              <tr><td>{zh ? "输入特征" : "Inputs"}</td><td className="tt">{inputColumns.length} {zh ? "列" : "columns"}</td></tr>
              <tr><td>{zh ? "算法强度 / 时长" : "Strength / budget"}</td><td className="tt">{strength} / {timeBudget / 60}min</td></tr>
            </tbody>
          </table>
          {error ? <div className="v2-note" style={{ borderColor: "rgba(230,111,117,.4)", background: "rgba(230,111,117,.07)", marginTop: 10 }}>⚠ {error}</div> : null}
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 16, gap: 10 }}>
        <button type="button" className="v2-btn ghost" disabled={step === 1 || submitting}
          onClick={() => setStep((step - 1) as WizardStep)}>{zh ? "上一步" : "Back"}</button>
        {step < 4 ? (
          <button type="button" className="v2-btn primary" disabled={!canNext} onClick={() => setStep((step + 1) as WizardStep)}>
            {zh ? "下一步" : "Next"} →
          </button>
        ) : (
          <button type="button" className="v2-btn primary" disabled={submitting || !targetColumn} onClick={() => void submit()}>
            {submitting ? (zh ? "提交中…" : "Submitting…") : (zh ? "🚀 启动全自动建模" : "Launch")}
          </button>
        )}
      </div>
      <div style={{ marginTop: 8 }}>
        <button type="button" className="v2-btn ghost" style={{ fontSize: 11.5, padding: "2px 8px" }}
          onClick={() => { message.info(zh ? "完整配置（算法族精调/超参/MLP 定制）在「自动建模」页" : "Full configuration lives on the AutoML page"); navigate("/automl"); }}>
          {zh ? "需要完整配置？去自动建模页 ›" : "Need full config? Open AutoML ›"}
        </button>
      </div>
    </div>
  );
}
