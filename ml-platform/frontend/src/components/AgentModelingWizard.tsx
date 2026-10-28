import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { RocketOutlined } from "@ant-design/icons";
import { getDatasetPreview, listDatasets } from "../api/datasets";
import { fetchDatasetProfile } from "../api/agentCenter";
import apiClient from "../api/client";
import { createAgentRun, listAgentRuns, getAgentRun } from "../api/agentCenter";
import { AUTOML_ALGORITHM_OPTIONS } from "../pages/AutoMLPage";
import { useI18n } from "../i18n";

/**
 * 建模智能体五步向导（平台改版设计稿 v-agent）：
 * 数据分析（选列+备注+提示词）→ 特征工程（形态+列指令）→ 自动建模
 * （算法白名单+参数）→ 评估验收（指标阈值）→ 服务化发布。
 * 配置条含项目/数据集/目标列/模型与「逐步确认模式」；提交即归档
 * UserGuidance（第四契约）并创建 pending AgentRun。
 */
type StepId = 1 | 2 | 3 | 4 | 5;
type DataShape = "tabular" | "waveform" | "mixed";

const ANALYSIS_PROMPT_CHIPS = [
  { label: "聚焦扭矩-目标偏差", prompt: "聚焦扭矩与目标设定值的偏差通道" },
  { label: "关注时序漂移", prompt: "关注批次间的时序漂移与工装变化" },
  { label: "怀疑判定中间列泄漏", prompt: "怀疑判定中间列（DECIDE_ONE/TWO 等）与目标同源泄漏，重点排查" },
  { label: "不平衡数据按召回优先", prompt: "类别不平衡，少数类召回优先于整体精度" },
];
const FEATURE_PROMPT_CHIPS = [
  { label: "优先比值特征", prompt: "派生特征优先比值/裕度类" },
  { label: "中位数+标记", prompt: "缺失值用中位数填充并加缺失标记列" },
];
const MODELING_PROMPT_CHIPS = [
  { label: "召回优先", prompt: "召回优先于精度" },
  { label: "可解释性优先", prompt: "特征重要性可解释优先" },
  { label: "限轻量模型", prompt: "限制轻量模型，避免大容量过拟合" },
];
const METRIC_ROWS: { key: string; label: string }[] = [
  { key: "recall_minority", label: "召回(少数类)" },
  { key: "precision", label: "精度" },
  { key: "f1", label: "F1" },
  { key: "accuracy", label: "Acc" },
  { key: "roc_auc", label: "AUC" },
];

interface ProjectOption { id: string; name?: string }
interface DatasetOption { id: string; name?: string; filename?: string; row_count?: number; column_count?: number }
interface ProfileOption { id: string; name: string; model_id: string; is_default?: boolean }

export default function AgentModelingWizard({ onSubmitted }: { onSubmitted?: () => void }) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [, setSearchParams] = useSearchParams();

  const [step, setStep] = useState<StepId>(1);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState("");
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [selectedColumns, setSelectedColumns] = useState<Record<string, boolean>>({});
  const [columnNotes, setColumnNotes] = useState<Record<string, string>>({});
  const [targetColumn, setTargetColumn] = useState("");
  const [profiles, setProfiles] = useState<ProfileOption[]>([]);
  const [llmProfileId, setLlmProfileId] = useState("");
  const [stepByStep, setStepByStep] = useState(false);

  // Step 2
  const [dataShape, setDataShape] = useState<DataShape>("mixed");
  const [columnDirectives, setColumnDirectives] = useState<Record<string, "keep" | "drop" | "">>({});
  const [featurePrompt, setFeaturePrompt] = useState("");

  // Step 3
  const [algorithmWhitelist, setAlgorithmWhitelist] = useState<Record<string, boolean>>({});
  const [paramHints, setParamHints] = useState({ trials: "", budget_seconds: "", cv_folds: "" });
  const [modelingPrompt, setModelingPrompt] = useState("");

  // Step 4
  const [metricGates, setMetricGates] = useState<Record<string, string>>({ recall_minority: "0.90" });
  const [reviewFocus, setReviewFocus] = useState("");
  const [testDatasetId, setTestDatasetId] = useState("");
  const [maxRounds, setMaxRounds] = useState("3");
  const [analysisPrompt, setAnalysisPrompt] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  // sp-1 画像（缺失率/互信息排名——列级出域，无行样例）
  const [profileStats, setProfileStats] = useState<{
    missing: Record<string, number>;
    miRank: Record<string, number>;
  }>({ missing: {}, miRank: {} });
  const [templateSaved, setTemplateSaved] = useState("");

  // 最近一次运行的定稿脚本（sp-2 脚本预览数据源）
  const [lastScript, setLastScript] = useState("");

  useEffect(() => {
    if (!datasetId || !targetColumn) {
      setProfileStats({ missing: {}, miRank: {} });
      return;
    }
    let cancelled = false;
    fetchDatasetProfile(datasetId, targetColumn, projectId || undefined)
      .then((profile) => {
        if (cancelled) return;
        const missing: Record<string, number> = {};
        profile.columns.forEach((column) => {
          missing[column.name] = column.missing_rate;
        });
        const miRank: Record<string, number> = {};
        profile.mutual_info_top.forEach((item, index) => {
          miRank[item.column] = index + 1;
        });
        setProfileStats({ missing, miRank });
      })
      .catch(() => setProfileStats({ missing: {}, miRank: {} }));
    return () => {
      cancelled = true;
    };
  }, [datasetId, targetColumn, projectId]);

  useEffect(() => {
    apiClient.get("/projects").then((res) => {
      const items = Array.isArray(res.data) ? res.data : res.data?.items;
      setProjects(Array.isArray(items) ? items : []);
    }).catch(() => setProjects([]));
    apiClient.get("/llm-profiles").then((res) => {
      const items = Array.isArray(res.data) ? res.data : res.data?.items || [];
      setProfiles(items);
      const preferred = items.find((p: ProfileOption) => p.is_default) ?? items[0];
      if (preferred) setLlmProfileId(String(preferred.id));
    }).catch(() => setProfiles([]));
  }, []);

  useEffect(() => {
    setDatasets([]); setDatasetId("");
    if (!projectId) return;
    listDatasets(projectId).then((items) => setDatasets(Array.isArray(items) ? items : [])).catch(() => setDatasets([]));
  }, [projectId]);

  // sp-2 脚本预览数据源：本项目最近一次 Agent 运行的定稿脚本
  useEffect(() => {
    if (!projectId) { setLastScript(""); return; }
    let cancelled = false;
    listAgentRuns(10).then(async (runs) => {
      if (cancelled) return;
      const mine = runs.find((run) => run.project_id === projectId);
      if (!mine) { setLastScript(""); return; }
      try {
        const detail = await getAgentRun(mine.id);
        if (cancelled) return;
        const rounds = detail.memory_json?.rounds ?? [];
        for (let i = rounds.length - 1; i >= 0; i -= 1) {
          const attempts = rounds[i]?.s2_attempts ?? [];
          for (let j = attempts.length - 1; j >= 0; j -= 1) {
            const script = (attempts[j] as { script?: string; ok?: boolean });
            if (script?.ok && script.script) { setLastScript(script.script); return; }
          }
        }
        setLastScript("");
      } catch { setLastScript(""); }
    }).catch(() => setLastScript(""));
    return () => { cancelled = true; };
  }, [projectId]);

  useEffect(() => {
    setColumns([]); setSelectedColumns({}); setColumnNotes({}); setColumnDirectives({}); setTargetColumn("");
    if (!datasetId) return;
    getDatasetPreview(datasetId).then((data) => {
      const cols: string[] = Array.isArray(data.columns)
        ? data.columns.filter((c: unknown): c is string => typeof c === "string")
        : [];
      setColumns(cols);
      setTargetColumn(cols.includes("DECIDE(判定（最终判定）（0-不合格，1-合格）)")
        ? "DECIDE(判定（最终判定）（0-不合格，1-合格）)"
        : cols.includes("label") ? "label" : cols.includes("fault") ? "fault" : "");
    }).catch(() => setColumns([]));
  }, [datasetId]);

  const dataset = datasets.find((d) => d.id === datasetId);
  const datasetLabel = dataset ? (dataset.name ?? dataset.filename ?? dataset.id) : "";
  const chosenNotes = useMemo(
    () => Object.entries(columnNotes)
      .filter(([column, note]) => note.trim() && selectedColumns[column])
      .map(([column, note]) => ({ column, note: note.trim() })),
    [columnNotes, selectedColumns],
  );

  const stepStatus = (n: StepId) => (n === step ? "on" : n < step ? "done" : "");
  const steps: { n: StepId; tt: string; st: string }[] = [
    { n: 1, tt: zh ? "数据分析" : "Analysis", st: zh ? "选列说明 · 提示词" : "columns · prompts" },
    { n: 2, tt: zh ? "特征工程" : "Features", st: zh ? "表格/波形 · 列指令" : "shape · directives" },
    { n: 3, tt: zh ? "自动建模" : "Modeling", st: zh ? "算法白名单 · 参数" : "whitelist · params" },
    { n: 4, tt: zh ? "评估验收" : "Evaluation", st: zh ? "测试集 · 指标阈值" : "gates" },
    { n: 5, tt: zh ? "服务化发布" : "Serving", st: zh ? "闭环 · 编排 · API" : "closed loop · API" },
  ];

  const submit = async (servitize: boolean) => {
    if (!datasetId || !targetColumn) return;
    setSubmitting(true); setError("");
    const gates: Record<string, number> = {};
    Object.entries(metricGates).forEach(([key, value]) => {
      const num = Number(value);
      if (value.trim() !== "" && Number.isFinite(num)) gates[key] = num;
    });
    const whitelist = Object.entries(algorithmWhitelist).filter(([, on]) => on).map(([id]) => id);
    const hints: Record<string, number | string> = {};
    if (paramHints.trials) hints.n_trials = Number(paramHints.trials);
    if (paramHints.budget_seconds) hints.budget_seconds = Number(paramHints.budget_seconds);
    if (paramHints.cv_folds) hints.cv_folds = Number(paramHints.cv_folds);
    try {
      await createAgentRun({
        dataset_artifact_id: datasetId,
        target_column: targetColumn,
        project_id: projectId || null,
        llm_profile_id: llmProfileId || null,
        step_by_step: stepByStep,
        guidance: {
          analysis: {
            column_notes: chosenNotes,
            prompts: analysisPrompt.trim() ? [analysisPrompt.trim()] : [],
          },
          feature: {
            data_shape: dataShape,
            must_keep: Object.entries(columnDirectives).filter(([, v]) => v === "keep").map(([c]) => c),
            suggest_drop: Object.entries(columnDirectives).filter(([, v]) => v === "drop").map(([c]) => ({ column: c })),
            prompts: featurePrompt.trim() ? [featurePrompt.trim()] : [],
          },
          modeling: {
            algorithm_whitelist: whitelist,
            param_hints: hints,
            prompts: modelingPrompt.trim() ? [modelingPrompt.trim()] : [],
          },
          evaluation: {
            custom_test_dataset_id: testDatasetId || null,
            metric_gates: gates,
            review_focus: reviewFocus.trim() ? [reviewFocus.trim()] : [],
          },
          max_rounds: Math.max(1, Math.min(5, Number(maxRounds) || 3)),
          auto_servitize: servitize,
        },
      });
      setSearchParams({ tab: "tasks" }, { replace: true });
      onSubmitted?.();
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      setError(typeof detail === "object"
        ? `${detail?.code ?? "failed"}: ${JSON.stringify(detail?.errors ?? detail?.message ?? "")}`.slice(0, 300)
        : String(detail || e?.message || e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      {/* 配置条 */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", background: "var(--v2-panel)", border: "1px solid var(--v2-line)", borderRadius: 12, padding: "10px 14px", marginBottom: 14 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
          {zh ? "项目" : "Project"}
          <select className="v2-select" style={{ minWidth: 130 }} value={projectId} onChange={(e) => setProjectId(e.target.value)} aria-label={zh ? "选择项目" : "Project"}>
            <option value="">—</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.name ?? p.id}</option>)}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
          {zh ? "数据集" : "Dataset"}
          <select className="v2-select" style={{ minWidth: 210 }} value={datasetId} onChange={(e) => setDatasetId(e.target.value)} disabled={!projectId} aria-label={zh ? "选择数据集" : "Dataset"}>
            <option value="">{zh ? "— 选择数据集 —" : "—"}</option>
            {datasets.map((d) => <option key={d.id} value={d.id}>
              {d.name ?? d.filename ?? d.id}{d.row_count != null ? `（${d.row_count.toLocaleString()} 行 × ${d.column_count ?? "?"} 列）` : ""}
            </option>)}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
          {zh ? "目标列" : "Target"}
          <select className="v2-select" style={{ minWidth: 180 }} value={targetColumn} onChange={(e) => setTargetColumn(e.target.value)} disabled={!columns.length} aria-label={zh ? "选择目标列" : "Target column"}>
            <option value="">—</option>
            {columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5 }}>
          {zh ? "模型" : "Model"}
          <select className="v2-select" style={{ minWidth: 170 }} value={llmProfileId} onChange={(e) => setLlmProfileId(e.target.value)} aria-label={zh ? "选择大模型档案" : "LLM profile"}>
            {profiles.length === 0 ? <option value="">{zh ? "（无档案）" : "(none)"}</option> : null}
            {profiles.map((p) => <option key={String(p.id)} value={String(p.id)}>{p.name} · {p.model_id}{p.is_default ? (zh ? "（默认）" : " (default)") : ""}</option>)}
          </select>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, marginLeft: "auto", cursor: "pointer" }}>
          {zh ? "逐步确认模式" : "Step-by-step"}
          <span
            role="switch"
            aria-checked={stepByStep}
            aria-label={zh ? "逐步确认模式" : "Step-by-step mode"}
            tabIndex={0}
            onClick={() => setStepByStep(!stepByStep)}
            onKeyDown={(e) => { if (e.key === "Enter") setStepByStep(!stepByStep); }}
            style={{ width: 34, height: 18, borderRadius: 10, background: stepByStep ? "var(--v2-blue)" : "var(--v2-line)", position: "relative", transition: ".18s", flexShrink: 0 }}
          >
            <span style={{ position: "absolute", top: 2, left: stepByStep ? 18 : 2, width: 14, height: 14, borderRadius: "50%", background: stepByStep ? "#fff" : "var(--v2-sub)", transition: ".18s" }} />
          </span>
        </label>
      </div>

      {/* 步骤条 */}
      <div className="v2-steps" role="tablist" aria-label={zh ? "向导步骤" : "Wizard steps"}>
        {steps.map((s) => (
          <button key={s.n} type="button" className={`v2-step ${stepStatus(s.n)}`}
            onClick={() => s.n < step && setStep(s.n)}>
            <span className="n">{s.n < step ? "✓" : s.n}</span>
            <span><span className="tt">{s.tt}</span><br /><span className="st">{s.st}</span></span>
          </button>
        ))}
      </div>

      {/* Step 1 数据分析 */}
      {step === 1 && (
        <>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "选择数据并说明（勾选列 + 行内备注，帮助大模型理解业务语义）" : "Columns + inline notes"}
              <span className="more">{zh ? `已选 ${Object.values(selectedColumns).filter(Boolean).length} / ${columns.length} 列` : ""}</span></h4>
            <table className="v2-table">
              <thead><tr>
                <th></th><th>{zh ? "列名" : "Column"}</th>
                <th>{zh ? "缺失率" : "Missing"}</th>
                <th>{zh ? "互信息排名" : "MI rank"}</th>
                <th>{zh ? "我的备注（直接进分析提示词）" : "My note (joins the analysis prompt)"}</th>
              </tr></thead>
              <tbody>
                {columns.length === 0 ? (
                  <tr><td colSpan={5} className="v2-empty">{projectId
                    ? (zh ? "选择数据集后展示列清单" : "Pick a dataset to list columns")
                    : (zh ? "先在上方选择项目与数据集" : "Choose a project and dataset above")}</td></tr>
                ) : null}
                {columns.map((column) => (
                  <tr key={column}>
                    <td><input type="checkbox" aria-label={`select ${column}`} checked={!!selectedColumns[column]}
                      onChange={(e) => setSelectedColumns((cur) => ({ ...cur, [column]: e.target.checked }))} /></td>
                    <td className="tt" style={{ color: column === targetColumn ? "var(--v2-gold)" : undefined }}>
                      {column}{column === targetColumn ? (zh ? "（目标列）" : " (target)") : ""}
                    </td>
                    <td>{profileStats.missing[column] !== undefined
                      ? `${(profileStats.missing[column] * 100).toFixed(1)}%` : "-"}</td>
                    <td>{profileStats.miRank[column] ? `#${profileStats.miRank[column]}` : "—"}</td>
                    <td><input className="v2-select" style={{ minWidth: 260, width: "90%" }} value={columnNotes[column] ?? ""}
                      placeholder={zh ? "选中的列与备注会成为大模型的重点输入" : "note"}
                      onChange={(e) => setColumnNotes((cur) => ({ ...cur, [column]: e.target.value }))} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "分析提示词（可选）" : "Analysis prompt (optional)"}</h4>
            <input className="v2-select" style={{ width: "100%", minWidth: 0 }} value={analysisPrompt}
              placeholder={zh ? "例如：这批数据来自换夹具后的产线，重点排查工装相关漂移…" : "e.g. focus on fixture drift…"}
              onChange={(e) => setAnalysisPrompt(e.target.value)} />
            <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginTop: 8 }}>
              {ANALYSIS_PROMPT_CHIPS.map((chip) => (
                <button key={chip.label} type="button" className="v2-chip" style={{ cursor: "pointer" }}
                  onClick={() => setAnalysisPrompt((cur) => (cur ? cur + "；" : "") + chip.prompt)}>{chip.label}</button>
              ))}
              <button type="button" className="v2-chip" style={{ cursor: analysisPrompt.trim() ? "pointer" : "not-allowed", opacity: analysisPrompt.trim() ? 1 : 0.5 }}
                onClick={() => {
                  const content = analysisPrompt.trim();
                  if (!content) return;
                  apiClient.post("/prompt-templates", {
                    name: (zh ? "分析模板 " : "analysis ") + new Date().toISOString().slice(5, 16).replace("T", " "),
                    stage: "analysis",
                    content,
                  }).then(() => {
                    setTemplateSaved(zh ? "已存为模板 ✓" : "saved ✓");
                    setTimeout(() => setTemplateSaved(""), 2500);
                  }).catch(() => setTemplateSaved(zh ? "保存失败" : "failed"));
                }}>{zh ? "存为模板" : "Save template"}{templateSaved ? ` ${templateSaved}` : ""}</button>
            </div>
          </div>
        </>
      )}

      {/* Step 2 特征工程 */}
      {step === 2 && (
        <>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "数据形态（约束特征脚本的处理方式）" : "Data shape"}</h4>
            <div className="v2-radio-cards">
              {([["tabular", "" + (zh ? "表格数据" : "Tabular"), zh ? "常规列式制造记录（拧紧样例适用）" : "columnar records"],
                ["waveform", "" + (zh ? "波形数据" : "Waveform"), zh ? "含编码波形列，需解码后统计（电焊 cvei/cvev/cver/cvep）" : "encoded waveform columns"],
                ["mixed", "" + (zh ? "混合形态" : "Mixed"), zh ? "报告列 + 波形列并存，两者兼顾" : "both"]] as [DataShape, string, string][]).map(([value, title, desc]) => (
                <button key={value} type="button" className={`v2-radio-card${dataShape === value ? " on" : ""}`} onClick={() => setDataShape(value)}>
                  <b>{title}</b><span>{desc}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "列级指令（可选）" : "Column directives (optional)"}</h4>
            <table className="v2-table">
              <thead><tr><th>{zh ? "列" : "Column"}</th><th>{zh ? "指令" : "Directive"}</th></tr></thead>
              <tbody>
                {columns.filter((c) => c !== targetColumn).slice(0, 30).map((column) => (
                  <tr key={column}>
                    <td className="tt">{column}</td>
                    <td>
                      <select className="v2-select" style={{ minWidth: 150 }} value={columnDirectives[column] ?? ""}
                        onChange={(e) => setColumnDirectives((cur) => ({ ...cur, [column]: e.target.value as "keep" | "drop" | "" }))}>
                        <option value="">{zh ? "无" : "none"}</option>
                        <option value="keep">{zh ? "必须保留" : "must keep"}</option>
                        <option value="drop">{zh ? "建议剔除" : "suggest drop"}</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "特征提示词（可选）" : "Feature prompt (optional)"}</h4>
            <input className="v2-select" style={{ width: "100%", minWidth: 0 }} value={featurePrompt}
              placeholder={zh ? "派生特征优先比值/裕度类；缺失用中位数+缺失标记" : "e.g. prefer ratio features"}
              onChange={(e) => setFeaturePrompt(e.target.value)} />
            <div className="prompt-chips">
              {FEATURE_PROMPT_CHIPS.map((chip) => (
                <span key={chip.label} className="pchip" style={{ cursor: "pointer" }}
                  onClick={() => setFeaturePrompt((cur) => (cur ? cur + "；" : "") + chip.prompt)}>{chip.label}</span>
              ))}
            </div>
          </div>
          {/* 智能体生成的脚本预览（最近一次运行的定稿脚本，运行后实时更新） */}
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "智能体生成的脚本预览（运行后实时更新）" : "Agent script preview (live after runs)"}
              {lastScript ? <span className="more">{zh ? "最近定稿" : "latest final"} · {lastScript.length} {zh ? "字符" : "chars"}</span> : null}</h4>
            {lastScript ? (
              <div className="codebox"><span className="cm"># {zh ? "最近一次通过沙箱的特征脚本" : "latest sandbox-passed feature script"}</span>
{lastScript}</div>
            ) : (
              <div className="v2-empty">{zh ? "暂无运行记录——提交任务后此处实时展示智能体生成的脚本" : "No runs yet — the generated script appears here"}</div>
            )}
          </div>
        </>
      )}

      {/* Step 3 自动建模 */}
      {step === 3 && (
        <>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "算法白名单（不选 = 全算法族自动搜索）" : "Algorithm whitelist (empty = all)"}</h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 8 }}>
              {AUTOML_ALGORITHM_OPTIONS.map((alg) => (
                <label key={alg.value} className={`v2-radio-card${algorithmWhitelist[alg.value] ? " on" : ""}`} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", marginBottom: 0 }}>
                  <input type="checkbox" checked={!!algorithmWhitelist[alg.value]}
                    onChange={(e) => setAlgorithmWhitelist((cur) => ({ ...cur, [alg.value]: e.target.checked }))} />
                  <span style={{ fontSize: 12.5 }}>{alg.label}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "参数约束（留空 = 智能体按数据画像决定）" : "Param hints (empty = agent decides)"}</h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
              <label style={{ fontSize: 12 }}>{zh ? "搜索试验数" : "Trials"}
                <input className="v2-select" style={{ width: "100%", marginTop: 4 }} value={paramHints.trials} placeholder={zh ? "自动" : "auto"}
                  onChange={(e) => setParamHints((cur) => ({ ...cur, trials: e.target.value }))} /></label>
              <label style={{ fontSize: 12 }}>{zh ? "时间预算(秒)" : "Budget (s)"}
                <input className="v2-select" style={{ width: "100%", marginTop: 4 }} value={paramHints.budget_seconds} placeholder={zh ? "自动" : "auto"}
                  onChange={(e) => setParamHints((cur) => ({ ...cur, budget_seconds: e.target.value }))} /></label>
              <label style={{ fontSize: 12 }}>{zh ? "CV 折数" : "CV folds"}
                <input className="v2-select" style={{ width: "100%", marginTop: 4 }} value={paramHints.cv_folds} placeholder="5"
                  onChange={(e) => setParamHints((cur) => ({ ...cur, cv_folds: e.target.value }))} /></label>
            </div>
          </div>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "建模提示词（可选）" : "Modeling prompt (optional)"}</h4>
            <input className="v2-select" style={{ width: "100%", minWidth: 0 }} value={modelingPrompt}
              placeholder={zh ? "召回优先于精度；需要特征重要性可解释" : "e.g. recall over precision"}
              onChange={(e) => setModelingPrompt(e.target.value)} />
            <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginTop: 8 }}>
              {MODELING_PROMPT_CHIPS.map((chip) => (
                <button key={chip.label} type="button" className="v2-chip" style={{ cursor: "pointer" }}
                  onClick={() => setModelingPrompt((cur) => (cur ? cur + "；" : "") + chip.prompt)}>{chip.label}</button>
              ))}
            </div>
          </div>
        </>
      )}

      {/* Step 4 评估验收 */}
      {step === 4 && (
        <>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "测试集（不选 = 自动留出切分）" : "Test set (auto split by default)"}</h4>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5, flexWrap: "wrap" }}>
              {zh ? "从项目数据集选择独立测试集" : "Pick a hold-out test dataset"}
              <select className="v2-select" style={{ minWidth: 220 }} value={testDatasetId}
                onChange={(e) => setTestDatasetId(e.target.value)} aria-label={zh ? "测试集" : "Test dataset"}>
                <option value="">{zh ? "— 自动留出 20%（分层抽样）—" : "— auto hold-out 20% —"}</option>
                {datasets.filter((d) => d.id !== datasetId).map((d) => (
                  <option key={d.id} value={d.id}>{d.name ?? d.id}</option>
                ))}
              </select>
            </label>
            <div style={{ color: "var(--v2-dim)", fontSize: 11.5, marginTop: 6 }}>
              {zh
                ? "未上传独立测试集时自动留出；测试集与训练集走同一特征工程管线。如需新数据集，请先到「算法平台 → 数据管理」上传后回到此处选择。"
                : "Auto hold-out when unset; uploads go through Data Management first."}
            </div>
          </div>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "搜索轮数上限" : "Iteration rounds"}</h4>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
              {zh ? "双门禁迭代最多轮数" : "Max rounds"}
              <input className="v2-select" style={{ width: 90 }} type="number" min={1} max={5}
                value={maxRounds} onChange={(e) => setMaxRounds(e.target.value)}
                aria-label={zh ? "搜索轮数" : "Rounds"} />
              <span style={{ color: "var(--v2-dim)", fontSize: 11.5 }}>{zh ? "（1-5，默认 3；轮数越多耗时与 Token 越多）" : "1-5, default 3"}</span>
            </label>
          </div>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "验收指标阈值（留空项不设门禁；对大模型一票否决）" : "Acceptance gates (blank = no gate)"}</h4>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
              {METRIC_ROWS.map((metric) => (
                <label key={metric.key} style={{ background: "var(--v2-bg)", border: "1px solid var(--v2-line)", borderRadius: 9, padding: "8px 11px", fontSize: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", color: "var(--v2-sub)" }}>{metric.label} <span>≥</span></div>
                  <input className="v2-select" style={{ border: "none", background: "transparent", padding: "2px 0 0", minWidth: 0, width: "100%" }}
                    value={metricGates[metric.key] ?? ""} placeholder="—"
                    onChange={(e) => setMetricGates((cur) => ({ ...cur, [metric.key]: e.target.value }))} />
                </label>
              ))}
            </div>
          </div>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "评审重点提示词（可选）" : "Review focus (optional)"}</h4>
            <input className="v2-select" style={{ width: "100%", minWidth: 0 }} value={reviewFocus}
              placeholder={zh ? "例如：重点解释假阴性样本的共同特征；对比上一版配方是否退化" : "e.g. explain false negatives"}
              onChange={(e) => setReviewFocus(e.target.value)} />
          </div>
          {error ? <div className="v2-note" style={{ borderColor: "rgba(230,111,117,.4)", background: "rgba(230,111,117,.07)" }}>注意：{error}</div> : null}
        </>
      )}

      {/* Step 5 服务化发布 */}
      {step === 5 && (
        <>
          <div className="v2-note" style={{ marginBottom: 12 }}>
            {zh ? "提交后智能体将开始迭代（S1 分析 → S2 特征脚本（沙箱）→ S3 建模 → S4 双门禁评审）；"
              + (stepByStep ? "已开启逐步确认：每个阶段之间会暂停等待你的确认。" : "逐步确认未开启：全自动迭代至终态。")
              : "The agent iterates S1→S4 with sandboxed scripts and hard gates; "
              + (stepByStep ? "step-by-step pauses between stages are ON." : "fully automatic.")}
          </div>
          <div className="v2-panel">
            <h4><span className="bar" />{zh ? "验收通过后的服务化（届时在此确认）" : "Post-acceptance serving (confirmed later)"}</h4>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 240, border: "1px solid var(--v2-line)", borderRadius: 10, padding: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <b style={{ fontSize: 13 }}>① {zh ? "模型上线" : "Model serving"}</b>
                  <span className="v2-badge v2-bg">{zh ? "将执行" : "will run"}</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--v2-sub)", lineHeight: 1.7 }}>
                  {zh ? "最优模型注册 → 批准 → 部署启动；模型 API 进市场前保持 draft（offline）"
                    : "Best model register → approve → deploy; the model API stays offline until approval"}
                </div>
              </div>
              <div style={{ flex: 1, minWidth: 240, border: "1px solid var(--v2-line)", borderRadius: 10, padding: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <b style={{ fontSize: 13 }}>② {zh ? "闭环自动化任务" : "Closed loop"}</b>
                  <span className="v2-badge v2-bb">{zh ? "将创建" : "will create"}</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--v2-sub)", lineHeight: 1.7 }}>
                  {zh ? "按配方创建（特征脚本 script 模式）；缺陷类从目标语义自动推导："
                    : "Created from the recipe (script-mode features); defect classes derived from target semantics: "}
                  <b style={{ color: "var(--v2-gold)" }}>{zh ? "将把「0」（不合格）判为报错回流" : "「0」 will be treated as error backflow"}</b>
                </div>
              </div>
              <div style={{ flex: 1, minWidth: 240, border: "1px solid var(--v2-line)", borderRadius: 10, padding: 12 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <b style={{ fontSize: 13 }}>③ {zh ? "应用编排 API" : "Orchestration API"}</b>
                  <span className="v2-badge v2-bp">{zh ? "将发布" : "will publish"}</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--v2-sub)", lineHeight: 1.7 }}>
                  {zh ? "从全局闭环模板生成（工具自动特征对齐）；dry_run 冒烟零回流后，人工批准一次即全部对外"
                    : "From the closed-loop template; after a zero-backflow dry-run smoke, one approval lists everything"}
                </div>
              </div>
            </div>
            <div style={{ color: "var(--v2-dim)", fontSize: 11.5, marginTop: 8 }}>
              {zh ? "提交后智能体迭代；验收通过 → 任务档案页「固化配方」→「一键服务化」（draft 三资产 → 批准发布）。"
                : "After acceptance: fixate the recipe in the run archive, then one-click servitize (draft → approve)."}
            </div>
          </div>
          {error ? <div className="v2-note" style={{ borderColor: "rgba(230,111,117,.4)", background: "rgba(230,111,117,.07)" }}>注意：{error}</div> : null}
        </>
      )}

      {/* 导航 */}
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, gap: 10 }}>
        <button type="button" className="v2-btn ghost" disabled={step === 1 || submitting}
          onClick={() => setStep((step - 1) as StepId)}>{zh ? "上一步" : "Back"}</button>
        {step < 5 ? (
          <button type="button" className="v2-btn primary" disabled={!datasetId || !targetColumn}
            onClick={() => setStep((step + 1) as StepId)}>{zh ? "下一步" : "Next"} →</button>
        ) : (
          <div style={{ display: "flex", gap: 10 }}>
            <button type="button" className="v2-btn" disabled={submitting || !datasetId || !targetColumn} onClick={() => void submit(false)}>
              <RocketOutlined />{submitting ? (zh ? "提交中…" : "Submitting…") : (zh ? "启动智能体" : "Launch agent")}
            </button>
            <button type="button" className="v2-btn primary" disabled={submitting || !datasetId || !targetColumn} onClick={() => void submit(true)}>
              <RocketOutlined />{zh ? "启动智能体并服务化（验收通过后自动起草发布资产）" : "Launch & servitize"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
