import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeftOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import PageHeading from "../components/PageHeading";
import AgentRunArchivePanel from "../components/AgentRunArchivePanel";
import { getAgentRun, type AgentRunDetail } from "../api/agentCenter";
import { formatLocalTime, parseBackendTime } from "../utils/time";
import { useI18n } from "../i18n";

/** 智能体中心→任务详情页：单个 Agent 运行的全链路档案（/agent/task/:runId）。 */

const ACTIVE_STATUSES = new Set(["pending", "running"]);
// 非终态轮询间隔：S2 沙箱/LLM 阶段秒级产出，10s 足够"有新消息自动出现"。
const ACTIVE_POLL_MS = 10_000;

function runSeconds(created?: string | null, updated?: string | null): string {
  if (!created || !updated) return "—";
  const start = parseBackendTime(created)?.getTime();
  const end = parseBackendTime(updated)?.getTime();
  if (start === undefined || end === undefined) return "—";
  return `${Math.max(0, Math.round((end - start) / 1000))} s`;
}

export default function AgentRunDetailPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [archive, setArchive] = useState<AgentRunDetail | null>(null);
  const [archiveError, setArchiveError] = useState("");
  const timer = useRef<number | null>(null);

  const load = useCallback(() => {
    setArchiveError("");
    getAgentRun(runId).then(setArchive).catch(() => {
      setArchive(null);
      setArchiveError(zh ? "档案加载失败——任务不存在或已被清理" : "Failed to load archive");
    });
  }, [runId, zh]);

  useEffect(() => { load(); }, [load]);

  const isActive = archive != null && ACTIVE_STATUSES.has(archive.status);

  // 非终态自动轮询：新阶段产物/状态变化自动出现；终态即停。
  useEffect(() => {
    if (timer.current != null) { window.clearInterval(timer.current); timer.current = null; }
    if (isActive) {
      timer.current = window.setInterval(load, ACTIVE_POLL_MS);
    }
    return () => { if (timer.current != null) window.clearInterval(timer.current); };
  }, [isActive, load]);

  const guidance = archive?.guidance_json ?? null;
  const gates = guidance?.evaluation?.metric_gates ?? {};
  const whitelist = guidance?.modeling?.algorithm_whitelist ?? [];
  const ensemble = guidance?.modeling?.ensemble;
  const feature = guidance?.feature;
  const analysis = guidance?.analysis;
  const evaluation = guidance?.evaluation;
  const modeling = guidance?.modeling;
  const taskType = guidance?.task_type ?? "supervised";
  const shapeText: Record<string, string> = {
    tabular: zh ? "表格" : "tabular",
    waveform: zh ? "波形编码" : "waveform",
    mixed: zh ? "混合（自动）" : "mixed",
  };
  // 四阶段配置行的统一渲染：无配置的阶段整行隐藏，避免空行噪音。
  const cfgRow = (label: string, value?: ReactNode | null) =>
    value == null || value === "" || (Array.isArray(value) && value.length === 0) ? null : (
      <tr>
        <td className="tt" style={{ width: 130 }}>{label}</td>
        <td>{value}</td>
      </tr>
    );
  const promptsLine = (items: string[] | undefined) =>
    items?.length
      ? <span style={{ fontSize: 12 }}>{items.map((p, i) => <div key={i} className="ts">{p.length > 90 ? p.slice(0, 90) + "…" : p}</div>)}</span>
      : null;

  return (
    <AppLayout>
      <PageHeading
        section="agent"
        parent={{ navKey: "agent_tasks", to: "/agent?tab=tasks" }}
        title={zh ? "任务详情" : "Run detail"}
        actions={(
          <button type="button" className="v2-btn" onClick={() => navigate("/agent?tab=tasks")}>
            <ArrowLeftOutlined /> {zh ? "返回任务列表" : "Back to jobs"}
          </button>
        )}
      />

      {archive ? (
        <>
        <div className="v2-panel" style={{ marginBottom: 12 }}>
          <h4><span className="bar" />{zh ? "基本信息" : "Overview"}</h4>
          <table className="v2-table">
            <tbody>
              <tr>
                <td className="tt" style={{ width: 130 }}>{zh ? "目标列" : "Target"}</td>
                <td>{archive.target_column ?? "-"}</td>
                <td className="tt" style={{ width: 130 }}>{zh ? "项目" : "Project"}</td>
                <td>{archive.project_name ?? "-"}</td>
              </tr>
              <tr>
                <td className="tt">{zh ? "模型 / 档案" : "Model / profile"}</td>
                <td>{archive.llm_model_id ?? "-"}{archive.llm_profile_name ? ` · ${archive.llm_profile_name}` : ""}</td>
                <td className="tt">{zh ? "阶段 / 轮次" : "Stage / rounds"}</td>
                <td>{archive.current_stage.toUpperCase()} · {zh ? "第" : "r"}{archive.round_count}{zh ? "轮" : ""}</td>
              </tr>
              <tr>
                <td className="tt">{zh ? "创建时间" : "Created"}</td>
                <td>{formatLocalTime(archive.created_at, true)}</td>
                <td className="tt">{zh ? "最后更新" : "Updated"}</td>
                <td>{formatLocalTime(archive.updated_at, true)}</td>
              </tr>
              <tr>
                <td className="tt">{zh ? "运行时长" : "Duration"}</td>
                <td>{runSeconds(archive.created_at, archive.updated_at)}</td>
                <td className="tt">Token</td>
                <td>{archive.token_used.toLocaleString()}{archive.token_budget ? ` / ${archive.token_budget.toLocaleString()}` : ""}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {guidance ? (
          <div className="v2-panel" style={{ marginBottom: 12 }}>
            <h4><span className="bar" />{zh ? "提交配置" : "Submitted guidance"}</h4>
            <table className="v2-table">
              <tbody>
                {cfgRow(
                  zh ? "建模范式" : "Paradigm",
                  <>
                    {taskType === "anomaly"
                      ? zh ? "无监督异常检测" : "anomaly"
                      : zh ? "有监督分类" : "supervised"}
                    <span style={{ color: "var(--v2-dim)" }}>
                      {" · "}{zh ? "迭代上限" : "max rounds"} {guidance.max_rounds ?? 3}
                      {guidance.auto_servitize ? ` · ${zh ? "验收通过自动起草服务化" : "auto servitize"}` : ""}
                    </span>
                  </>,
                )}
                {/* 数据分析阶段 */}
                {cfgRow(zh ? "数据分析 · 全量训练" : "Full data",
                  analysis?.full_data === false ? (zh ? "关闭（超大数据集降采样验收）" : "off") : zh ? "开启（100% 真实数据）" : "on")}
                {cfgRow(zh ? "数据分析 · 重点排查列" : "Suspect focus", (analysis?.suspect_focus ?? []).join("、"))}
                {cfgRow(zh ? "数据分析 · 列/行备注" : "Column/row notes",
                  analysis?.column_notes?.length || analysis?.row_notes?.length
                    ? `${(analysis?.column_notes ?? []).length} / ${(analysis?.row_notes ?? []).length} ${zh ? "条" : ""}`
                    : null)}
                {cfgRow(zh ? "数据分析 · 自定义提示" : "Prompts", promptsLine(analysis?.prompts))}
                {/* 特征工程阶段 */}
                {cfgRow(zh ? "特征工程 · 数据形态" : "Data shape", shapeText[feature?.data_shape ?? "mixed"] ?? feature?.data_shape)}
                {cfgRow(zh ? "特征工程 · 列类型标注" : "Column types",
                  feature?.column_shapes && Object.keys(feature.column_shapes).length
                    ? <span className="ts" style={{ fontSize: 12 }}>{Object.entries(feature.column_shapes).map(([c, s]) => `${c}=${s === "waveform" ? (zh ? "波形" : "wave") : zh ? "表格" : "tab"}`).join("，")}</span>
                    : null)}
                {cfgRow(zh ? "特征工程 · 必须保留列" : "Must keep", (feature?.must_keep ?? []).join("、"))}
                {cfgRow(zh ? "特征工程 · 建议剔除" : "Suggest drop",
                  feature?.suggest_drop?.length
                    ? feature.suggest_drop.map((d, i) => <span key={i} style={{ marginRight: 8 }} className="ts">{(d as { column?: string }).column ?? ""}</span>)
                    : null)}
                {cfgRow(zh ? "特征工程 · 自定义提示" : "Prompts", promptsLine(feature?.prompts))}
                {/* 自动建模阶段 */}
                {cfgRow(
                  zh ? "自动建模 · 算法白名单" : "Algorithm whitelist",
                  whitelist.length
                    ? <>
                        {whitelist.join("、")}
                        <span style={{ color: "var(--v2-dim)" }}>
                          {" · "}{zh ? "集成学习" : "Ensemble"}：
                          {ensemble?.enabled
                            ? `${zh ? "已启用" : "on"}（Top-${ensemble.top_k ?? 3} ${zh ? "加权投票" : "soft-voting"}）`
                            : zh ? "未启用" : "off"}
                        </span>
                      </>
                    : <>{zh ? "未指定（全族搜索）" : "auto"}<span style={{ color: "var(--v2-dim)" }}>{" · "}{zh ? "集成学习" : "Ensemble"}：{ensemble?.enabled ? `${zh ? "已启用" : "on"}（Top-${ensemble.top_k ?? 3}）` : zh ? "未启用" : "off"}</span></>,
                )}
                {cfgRow(zh ? "自动建模 · 参数提示" : "Param hints",
                  modeling?.param_hints && Object.keys(modeling.param_hints).length
                    ? <span className="ts" style={{ fontSize: 12 }}>{Object.entries(modeling.param_hints).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join("，")}</span>
                    : null)}
                {cfgRow(zh ? "自动建模 · 预期异常比例" : "Contamination",
                  taskType === "anomaly" && modeling?.contamination != null ? String(modeling.contamination) : null)}
                {cfgRow(zh ? "自动建模 · 分工况列" : "Condition column", modeling?.condition_column || null)}
                {cfgRow(zh ? "自动建模 · 自定义提示" : "Prompts", promptsLine(modeling?.prompts))}
                {/* 评估验收阶段 */}
                {cfgRow(zh ? "评估验收 · 指标门禁" : "Metric gates",
                  Object.keys(gates).length
                    ? Object.entries(gates).map(([k, v]) => `${k} ≥ ${v}`).join("；")
                    : zh ? "未设硬门禁" : "none")}
                {cfgRow(zh ? "评估验收 · 评审关注点" : "Review focus", (evaluation?.review_focus ?? []).join("；"))}
                {cfgRow(zh ? "评估验收 · 独立验证集" : "Holdout dataset", evaluation?.custom_test_dataset_id || null)}
                {cfgRow(zh ? "评估验收 · 已知异常样本" : "Known anomalies",
                  taskType === "anomaly" && evaluation?.known_anomaly_rows?.length
                    ? `${evaluation.known_anomaly_rows.length} ${zh ? "条" : "rows"}`
                    : null)}
                {/* 知识源 */}
                {cfgRow(
                  zh ? "知识源" : "Knowledge",
                  <>
                    {guidance.use_platform_experience === false
                      ? zh ? "平台经验：关闭" : "experience off"
                      : zh ? "平台经验：注入" : "experience on"}
                    <span style={{ color: "var(--v2-dim)" }}>
                      {` · Top-${guidance.experience_top_k ?? 5} · ≥${guidance.experience_min_confidence ?? 0.8}`}
                      {guidance.knowledge_base_ids?.length ? ` · ${zh ? "知识库" : "KB"}×${guidance.knowledge_base_ids.length}` : ""}
                    </span>
                  </>,
                )}
              </tbody>
            </table>
          </div>
        ) : null}
        </>
      ) : null}

      <AgentRunArchivePanel
        runId={runId}
        archive={archive}
        archiveError={archiveError}
        zh={zh}
        active={isActive}
        onRefresh={load}
      />
    </AppLayout>
  );
}

