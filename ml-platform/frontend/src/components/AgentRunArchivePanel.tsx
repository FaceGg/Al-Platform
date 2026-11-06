import { useEffect, useMemo, useRef, useState } from "react";
import { LoadingOutlined } from "@ant-design/icons";
import OptReportPanel from "./OptReportPanel";
import ServitizeActions from "./ServitizeActions";
import { parseBackendTime, formatLocalTime } from "../utils/time";
import apiClient from "../api/client";
import { agentStatusLabel } from "../utils/agentStatus";
import {
  resumeAgentRun,
  type AgentRunDetail,
} from "../api/agentCenter";

/** 与列表页/详情页共用的 Agent 运行档案面板（轮次时间线 + 产物 + L2 + 服务化）。 */

const statusBadge = (status: string): string => {
  const s = status.toLowerCase();
  if (["running", "progressing"].some((k) => s.includes(k))) return "v2-bb";
  if (["completed", "succeeded", "done"].some((k) => s.includes(k))) return "v2-bg";
  if (["failed", "error", "cancelled"].some((k) => s.includes(k))) return "v2-br";
  if (["queued", "pending", "waiting"].some((k) => s.includes(k))) return "v2-bgo";
  return "v2-bgray";
};

function relativeTime(iso?: string | null, zh = true): string {
  const parsed = parseBackendTime(iso);
  if (!parsed) return "-";
  const minutes = Math.round((Date.now() - parsed.getTime()) / 60000);
  if (minutes < 1) return zh ? "刚刚" : "just now";
  if (minutes < 60) return zh ? `${minutes} 分钟前` : `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return zh ? `${hours} 小时前` : `${hours}h ago`;
  return zh ? `${Math.round(hours / 24)} 天前` : `${Math.round(hours / 24)}d ago`;
}

function formatDecisionTime(iso?: string | null, zh = true): string {
  return formatLocalTime(iso, true);
}

interface Props {
  runId: string;
  archive: AgentRunDetail | null;
  archiveError: string;
  zh: boolean;
  /** 非终态：头部转圈指示当前阶段（详情页自动轮询驱动）。 */
  active?: boolean;
  onClose?: () => void;
  onRefresh: () => void;
}

const STAGE_LABELS: Record<string, { zh: string; en: string }> = {
  s1: { zh: "数据分析（LLM 思考中）", en: "Analysis (LLM)" },
  s2: { zh: "特征工程（生成/验证脚本）", en: "Feature script" },
  s3: { zh: "候选训练（全量重放+训练）", en: "Training" },
  s4: { zh: "硬门禁与评审", en: "Gates & review" },
};

/** 活跃态：结果块不渲染失败判定（running/pending 不是"未通过"）。 */
const ACTIVE_STATUSES = new Set(["pending", "running"]);

/** 终态人性化说明：失败给信号+归因+建议，而非裸错误码（ed95d930 类诉求）。 */
const TERMINAL_EXPLAIN: Record<string, { signal: string; why: string; advice: string }> = {
  AGENT_MAX_ROUNDS: {
    signal: "未达验收标准（自动迭代已达上限）",
    why: "多轮迭代均未通过硬门禁。常见原因是数据量不足、类别严重不平衡，或门禁阈值高于该数据集能达到的上限。",
    advice: "建议：放宽门禁阈值（如 recall ≥ 0.6）／换更大数据集／检查目标列语义是否正确。",
  },
  AGENT_S1_LLM_FAILED: {
    signal: "大模型服务不可用",
    why: "调用大模型失败（网络超时或服务无响应），与数据无关。",
    advice: "建议：稍后重试；到大模型管理页点「测试」确认供应商连通；持续失败请检查密钥与网络。",
  },
  AGENT_S1_CONTRACT_FAILED: {
    signal: "分析结果不合格",
    why: "大模型返回的分析报告不符合平台契约（字段缺失/格式错误）。",
    advice: "建议：重新提交任务即可（偶发）；频繁出现可尝试更换模型或收紧分析提示词。",
  },
  AGENT_S2_NOT_CONVERGED: {
    signal: "特征工程未收敛",
    why: "多轮生成的特征脚本均未通过沙箱验证（违反列数/泄漏/运行约束）。",
    advice: "建议：在向导第二步明确数据形态与必留列，或换个能力更强的模型档案。",
  },
  AGENT_S3_TRANSFORM_FAILED: {
    signal: "特征脚本全量执行失败",
    why: "特征脚本在沙箱样本上通过，但对全量数据重放时失败（行数/内存/超时）。",
    advice: "建议：重新提交；若复现请在第二步提示「避免高基数类别展开」。",
  },
  AGENT_S4_CONTRACT_FAILED: {
    signal: "评审结果不合格",
    why: "大模型评审输出不符合平台契约。",
    advice: "建议：重新提交任务即可（偶发）。",
  },
  AGENT_REVIEW_ESCALATE: {
    signal: "评审请求人工确认",
    why: "评审发现指标异常（如完美指标疑似数据泄漏），按设计暂停等待人工判断。",
    advice: "建议：查看各轮评审建议，确认泄漏点名是否属实后决定重提或采纳。",
  },
  AGENT_EXECUTOR_CRASHED: {
    signal: "执行异常终止",
    why: "执行线程发生未预期异常，堆栈已在下方留档。",
    advice: "建议：重新提交；若复现请把「待人工决策原因」中的堆栈反馈给平台维护者。",
  },
  AGENT_RUN_INTERRUPTED: {
    signal: "执行被中断",
    why: "执行进程重启导致任务中断（心跳超时被清扫标记）。",
    advice: "建议：重新提交任务即可。",
  },
  AGENT_TOKEN_BUDGET_EXCEEDED: {
    signal: "Token 预算耗尽",
    why: "迭代消耗超出设定的 Token 预算，主动熔断。",
    advice: "建议：提高预算或收紧门禁让任务更早收敛。",
  },
};

export default function AgentRunArchivePanel({ runId, archive, archiveError, zh, active, onClose, onRefresh }: Props) {
  const escalation = archive?.memory_json?.escalation;
  const activeStage = active && archive ? STAGE_LABELS[archive.current_stage] : null;
  const [cancelling, setCancelling] = useState(false);
  const [deciding, setDeciding] = useState<"accept" | "reject" | null>(null);
  const [decisionNote, setDecisionNote] = useState("");
  const [decisionError, setDecisionError] = useState("");
  const escalated = archive?.status === "waiting_escalate";
  const resolved = escalation?.resolved;

  const decide = async (decision: "accept" | "reject") => {
    setDeciding(decision);
    setDecisionError("");
    try {
      await apiClient.post(`/agent/runs/${runId}/decision`, {
        decision, note: decisionNote.trim() || null,
      });
      setDecisionNote("");
      onRefresh();
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: { message?: string; code?: string } } } })?.response?.data?.detail;
      setDecisionError(detail?.message || detail?.code || (zh ? "决策提交失败" : "Decision failed"));
    } finally {
      setDeciding(null);
    }
  };
  return (
    <div style={{ marginTop: 12, border: "1px solid var(--v2-line)", borderRadius: 10, background: "var(--v2-bg)", padding: "12px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <b style={{ color: "var(--v2-txt)", fontSize: 13 }}>{zh ? "运行档案" : "Run archive"}</b>
        <span className="v2-badge v2-bgray">{runId.slice(0, 8)}</span>
        {archive ? (
          <>
            <span className={`v2-badge ${statusBadge(archive.status)}`} title={archive.status}>
              {agentStatusLabel(archive.status, zh)}
            </span>
            {activeStage ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--v2-blue, #2f9bf5)" }}>
                <LoadingOutlined spin />{zh ? activeStage.zh : activeStage.en}
              </span>
            ) : null}
            {archive.llm_model_id ? <span className="v2-badge v2-bp">{archive.llm_model_id}</span> : null}
            <span style={{ fontSize: 11, color: "var(--v2-dim)" }}>
              {archive.token_used.toLocaleString()}{archive.token_budget ? ` / ${archive.token_budget.toLocaleString()}` : ""} tokens · {zh ? "轮" : "rounds "}{archive.round_count}
            </span>
            {archive.status === "waiting_guidance" ? (
              <button
                type="button"
                className="v2-btn primary sm"
                onClick={() => {
                  resumeAgentRun(archive.id)
                    .then(() => onRefresh())
                    .catch(() => undefined);
                }}
              >{zh ? "放行继续 →" : "Resume →"}</button>
            ) : null}
            {active ? (
              <button
                type="button"
                className="v2-btn sm"
                style={{ borderColor: "rgba(230,111,117,.55)", color: "var(--v2-red)" }}
                disabled={cancelling}
                onClick={() => {
                  setCancelling(true);
                  apiClient.post(`/agent/runs/${archive.id}/cancel`)
                    .then(() => onRefresh())
                    .catch(() => setCancelling(false));
                }}
                title={zh ? "终止任务：当前 LLM 调用（最长约 12 分钟）完成后在阶段边界停止" : "Cancel at the next stage boundary"}
              >{cancelling ? (zh ? "终止中…" : "Cancelling…") : (
                <>
                  <span aria-hidden style={{ width: 10, height: 10, background: "var(--v2-red)", borderRadius: 2, flexShrink: 0 }} />
                  {zh ? "终止" : "Cancel"}
                </>
              )}</button>
            ) : null}
          </>
        ) : null}
        {onClose ? (
          <span style={{ marginLeft: "auto", cursor: "pointer", color: "var(--v2-dim)", fontSize: 12 }} onClick={onClose}>✕</span>
        ) : null}
      </div>
      {archiveError ? <div className="v2-empty" style={{ padding: 12 }}>{archiveError}</div> : null}
      {!archive && !archiveError ? <div className="v2-empty" style={{ padding: 12 }}>{zh ? "档案加载中…" : "Loading…"}</div> : null}
      {archive ? (
        <>
        {escalation?.detail ? (
          <div style={{ marginBottom: 10, padding: "8px 10px", border: "1px solid var(--v2-line)", borderRadius: 8, background: "rgba(230,111,117,.08)", fontSize: 12, lineHeight: 1.7 }}>
            <b style={{ color: "var(--v2-red)" }}>{zh ? "待人工决策原因" : "Why this needs a decision"}</b>
            <div style={{ color: "var(--v2-sub)", wordBreak: "break-all" }}>{escalation.detail}</div>
            {resolved ? (
              <div style={{ marginTop: 6, color: "var(--v2-txt)" }}>
                {resolved.decision === "accept"
                  ? (zh ? "✓ 已人工采纳验收结论" : "✓ Accepted by human decision")
                  : (zh ? "✕ 已人工驳回（确认评审意见，任务终止）" : "✕ Rejected by human decision")}
                {resolved.note ? ` · ${resolved.note}` : ""}
                {resolved.at ? ` · ${formatDecisionTime(resolved.at, zh)}` : ""}
              </div>
            ) : null}
            {escalated && !resolved ? (
              <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <input
                  className="v2-select"
                  style={{ flex: 1, minWidth: 180 }}
                  aria-label={zh ? "决策备注（可选）" : "decision note"}
                  placeholder={zh ? "决策备注（可选，随档案留痕）" : "note (archived)"}
                  value={decisionNote}
                  onChange={(e) => setDecisionNote(e.target.value)}
                />
                <button
                  type="button" className="v2-btn primary sm" disabled={deciding !== null}
                  title={zh ? "人工确认指标可信：验收通过（采纳最后轮次冠军实测指标）" : "Accept the round champion metrics"}
                  onClick={() => void decide("accept")}
                >{deciding === "accept" ? (zh ? "提交中…" : "…") : (zh ? "✓ 人工采纳" : "Accept")}</button>
                <button
                  type="button" className="v2-btn sm" disabled={deciding !== null}
                  style={{ borderColor: "rgba(230,111,117,.55)", color: "var(--v2-red)" }}
                  title={zh ? "确认评审意见：任务终止，可调整引导后重新提交" : "Confirm review concerns and end the run"}
                  onClick={() => void decide("reject")}
                >{deciding === "reject" ? (zh ? "提交中…" : "…") : (zh ? "✕ 驳回" : "Reject")}</button>
                {decisionError ? <span style={{ color: "var(--v2-red)" }}>{decisionError}</span> : null}
              </div>
            ) : null}
          </div>
        ) : null}
        <AgentStream archive={archive} zh={zh} active={!!active} />
        <OptReportPanel resultJson={archive.result_json} zh={zh} />
        {/* 设计稿两块：轮次关键产物表 + 注入的经验（L2 检索） */}
        <div style={{ display: "flex", gap: 14, marginTop: 14, flexWrap: "wrap" }}>
          <div className="v2-panel" style={{ margin: 0, flex: 1, minWidth: 260 }}>
            <h4><span className="bar" />{zh ? "轮次关键产物" : "Round artifacts"}</h4>
            <table className="v2-table">
              <thead><tr><th>{zh ? "产物" : "Artifact"}</th><th>{zh ? "状态" : "Status"}</th></tr></thead>
              <tbody>
                {(archive.memory_json?.rounds ?? []).some((round) => (round.s2_attempts ?? []).some((a) => a.ok)) ? (
                  <>
                    <tr><td>AnalysisReport</td><td><span className="v2-badge v2-bgo">{zh ? "已校验" : "validated"}</span></td></tr>
                    {(archive.memory_json?.rounds ?? []).some((round) => (round.s2_attempts ?? []).some((a) => a.ok)) ? (
                      <tr><td>{zh ? "特征脚本（定稿）" : "Feature script (final)"}</td><td><span className="v2-badge v2-bgo">{zh ? "沙箱通过" : "sandbox OK"}</span></td></tr>
                    ) : null}
                    {archive.result_json?.metrics ? (
                      <tr><td>{zh ? "候选指标" : "Candidate metrics"}</td><td><span className="v2-badge v2-bg">{zh ? "已产出" : "produced"}</span></td></tr>
                    ) : null}
                    {(archive.memory_json?.rounds ?? []).some((round) => round.verdict) ? (
                      <tr><td>ReviewVerdict</td><td>
                        <span className={`v2-badge ${(archive.memory_json?.rounds ?? []).some((round) => round.verdict === "pass") ? "v2-bgo" : "v2-br"}`}>
                          {(archive.memory_json?.rounds ?? []).map((round) => round.verdict).filter(Boolean).pop()}
                        </span>
                      </td></tr>
                    ) : null}
                  </>
                ) : (
                  <tr><td colSpan={2} className="v2-empty">{zh ? "暂无产物——运行后此处展示各阶段交付物" : "No artifacts yet"}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="v2-panel" style={{ margin: 0, flex: 1, minWidth: 260 }}>
            <h4><span className="bar" />{zh ? "注入的经验（L2 检索）" : "Injected experience (L2)"}</h4>
            {(archive.memory_json?.injected_experience as Array<{ entry?: string; lesson?: string; confidence?: number }> | undefined)?.length ? (
              (archive.memory_json.injected_experience as Array<{ entry?: string; lesson?: string; confidence?: number }>).map((ref, index) => (
                <div key={ref.entry ?? index} style={{ fontSize: 12, lineHeight: 1.8, color: "var(--v2-sub)" }}>
                  · <span className="tt">[{ref.entry?.slice(0, 8) ?? "?"}]</span> {ref.lesson ?? ""}
                  {ref.confidence != null ? <span style={{ color: "var(--v2-dim)" }}>（{ref.confidence.toFixed(2)}）</span> : null}
                </div>
              ))
            ) : (
              <div className="v2-empty">{zh ? "本轮无命中经验（shadow 条目不计入注入）" : "No experience injected this round"}</div>
            )}
          </div>
        </div>
        {archive.status === "accepted" ? (
          <ServitizeActions
            runId={archive.id}
            projectId={archive.project_id}
            recipeId={(archive.result_json?.recipe_id as string | undefined) ?? null}
            zh={zh}
            onRecipeFixed={() => onRefresh()}
          />
        ) : null}
        </>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 流式控制台：左侧章节大纲（点击跳转）+ 右侧滚动条 + 运行态菊花 spinner */
/* ------------------------------------------------------------------ */

interface StreamLine {
  key: string;
  sectionId: string;
  sectionLabel?: string;
  kind: "section" | "text" | "mono" | "outcome";
  text?: string;
  tone?: "ok" | "warn" | "err" | "dim";
}

interface StreamSection {
  id: string;
  label: string;
  startIndex: number;
}

/** 把运行档案展开为控制台行流（一行一条），供逐行流式揭示。 */
function buildStreamLines(archive: AgentRunDetail, zh: boolean): StreamLine[] {
  const lines: StreamLine[] = [];
  const push = (sectionId: string, kind: StreamLine["kind"], text: string, tone?: StreamLine["tone"], sectionLabel?: string) => {
    lines.push({ key: `${sectionId}-${lines.length}`, sectionId, sectionLabel, kind, text, tone });
  };
  const rounds = archive.memory_json?.rounds ?? [];
  for (const round of rounds) {
    const sid = `round-${round.round}`;
    push(sid, "section", zh ? `第 ${round.round} 轮` : `Round ${round.round}`, undefined, zh ? `第 ${round.round} 轮` : `Round ${round.round}`);
    const s1 = round.s1;
    if (s1?.domain) push(sid, "text", `[S1] ${zh ? "域假设" : "Domain"}：${s1.domain}`, "ok");
    if (s1?.wide_table_note) push(sid, "text", `[S1] ⚠ ${s1.wide_table_note}`, "warn");
    if (s1?.reasoning) push(sid, "text", `[S1] ${s1.reasoning.length > 220 ? s1.reasoning.slice(0, 220) + "…" : s1.reasoning}`);
    if (s1?.focus_channels?.length) push(sid, "text", `[S1] ${zh ? "关键通道" : "Channels"}：${s1.focus_channels.map((c) => c.channel).filter(Boolean).join("、")}`);
    if (s1?.leakage?.length) push(sid, "text", `[S1] ${zh ? "泄漏嫌疑" : "Leakage"}：${s1.leakage.map((l) => l.column).filter(Boolean).join("、")}`, "warn");
    if (s1?.quality_actions?.length) push(sid, "text", `[S1] ${zh ? "数据质量动作" : "Quality"}：${s1.quality_actions.map((q) => q.action).filter(Boolean).join("；")}`);
    if (s1?.class_balance) push(sid, "text", `[S1] ${zh ? "类不平衡" : "Balance"}：${s1.class_balance}`);
    for (const attempt of round.s2_attempts ?? []) {
      push(sid, "mono", `$ S2 ${zh ? "尝试" : "attempt"} ${attempt.attempt}: ${attempt.ok ? (zh ? "通过沙箱" : "sandbox OK") : (attempt.error ?? "failed")}${Array.isArray(attempt.detail) && attempt.detail.length ? ` (${attempt.detail.slice(0, 3).join("; ")})` : ""}`, attempt.ok ? "ok" : "warn");
    }
    const s2 = round.s2;
    if (s2) {
      push(sid, "text", `[S2] ${zh ? "特征工程" : "Features"} · ${s2.attempts ?? 1} ${zh ? "次尝试" : "attempts"}${s2.data_shape ? ` · ${s2.data_shape}` : ""}`);
      if (s2.description) push(sid, "text", s2.description.length > 240 ? s2.description.slice(0, 240) + "…" : s2.description);
      if (s2.generated_columns?.length) push(sid, "text", `${zh ? "新增" : "Added"}：${s2.generated_columns.join("、")}`, "ok");
      if (s2.dropped_columns?.length) push(sid, "text", `${zh ? "剔除" : "Dropped"}：${s2.dropped_columns.join("、")}`, "dim");
    }
    const s3 = round.s3;
    if (s3) {
      push(sid, "text", `[S3] ${zh ? "候选训练" : "Training"} · ${zh ? "指标" : "metrics"}：${Object.entries(s3.metrics ?? {}).map(([k, v]) => `${k}=${v}`).join("  ")}`);
      if (s3.importance?.length) push(sid, "text", `${zh ? "特征重要性" : "Importance"}：${s3.importance.slice(0, 5).map((i) => `${i.feature}(${i.importance})`).join("、")}`);
      // 标签列被平台剥离的留痕（防标签自泄漏）：指标可信性的关键注脚
      if (s3.target_excluded_from_features) {
        push(sid, "text", `${zh ? "标签列已从特征矩阵剥离：" : "Target excluded from features: "}${s3.target_excluded_from_features}`, "dim");
      }
      // 集成学习留痕：成员与权重、是否被采纳为冠军
      if (s3.ensemble?.members?.length) {
        push(sid, "text",
          `[${zh ? "集成" : "Ensemble"}] soft-voting ${s3.ensemble.adopted
            ? (zh ? "已采用" : "adopted")
            : (zh ? "未采用" : "not adopted")} · ${(s3.ensemble.members ?? []).map((m) => `${m.name}(${m.weight})`).join("、")}${s3.ensemble.reason ? ` · ${s3.ensemble.reason}` : ""}`,
          s3.ensemble.adopted ? "ok" : "dim");
      }
    }
    const s4 = round.s4;
    if (s4) {
      push(sid, "text", `[S4] ${zh ? "硬门禁" : "Gates"}：${s4.gate_passed ? (zh ? "通过" : "passed") : (zh ? "未过" : "failed")}`, s4.gate_passed ? "ok" : "err");
      for (const f of (s4.gate_failures ?? []).slice(0, 4)) push(sid, "text", `· ${f}`, "warn");
    }
    const review = round.review;
    if (review) {
      push(sid, "text", `[${zh ? "评审" : "Review"}] ${review.verdict ?? "-"}`, review.verdict === "pass" ? "ok" : "warn");
      if (review.readiness) push(sid, "text", review.readiness.length > 220 ? review.readiness.slice(0, 220) + "…" : review.readiness);
      if (review.surprises?.length) push(sid, "text", `${zh ? "意外发现" : "Surprises"}：${review.surprises.join("；")}`, "warn");
    }
    for (const hint of (round.hints ?? []).slice(0, 3)) {
      push(sid, "text", `${zh ? "建议" : "Hint"}：${hint.length > 120 ? hint.slice(0, 120) + "…" : hint}`, "dim");
    }
  }
  if (!rounds.length) {
    // 空轮次有三种含义，不能一律解释成"旧任务"（真机 1c586acf：新任务
    // S1 三连失败升级，档案却显示"早于落档案功能上线"误导排障方向）：
    // 运行中=正在 S1 长生成；终态=第 1 阶段即失败；仅 2026-10-27 前的
    // 历史任务才是真的"功能未上线"。
    const created = parseBackendTime(archive.created_at);
    const predates = !!created && created.getTime() < Date.parse("2026-10-27T00:00:00Z");
    const emptyText = ACTIVE_STATUSES.has(archive.status)
      ? (zh ? "任务正在第 1 阶段（S1 大模型分析）——生成耗时可达数分钟（含重试最长约 12 分钟），阶段产物将在完成后逐段写入这里。" : "S1 LLM analysis in progress (up to ~12 min with retries); artifacts will stream here once complete.")
      : predates
        ? (zh ? "暂无轮次记录——该任务运行早于阶段产物落档案功能上线（2026-10-27），新任务将逐阶段流式记录。" : "This run predates per-stage artifact persistence.")
        : (zh ? "暂无轮次记录——任务在第 1 阶段（S1 大模型分析）即失败/升级，未产出阶段产物；原因见下方升级详情。" : "No stage artifacts: the run failed or escalated during S1; see the decision note below.");
    lines.push({
      key: "empty", sectionId: "rounds", sectionLabel: zh ? "轮次" : "Rounds", kind: "text",
      text: emptyText,
    });
  }
  // 结果块只在终态渲染——running/pending 不是"未通过"（a1d8bd26 误报修复）。
  if (!ACTIVE_STATUSES.has(archive.status)) {
    lines.push({ key: "final", sectionId: "final", sectionLabel: zh ? "结果" : "Result", kind: "outcome" });
  }
  return lines;
}

function AgentStream({ archive, zh, active }: { archive: AgentRunDetail; zh: boolean; active: boolean }) {
  const streamRef = useRef<HTMLDivElement | null>(null);
  const followRef = useRef(true);
  const [lines, setLines] = useState<StreamLine[]>([]);
  const [revealed, setRevealed] = useState(0);
  const [activeSection, setActiveSection] = useState("");
  const [nowTick, setNowTick] = useState(() => Date.now());
  const prevRunRef = useRef<string | null>(null);
  const prevLenRef = useRef(0);

  // 活跃任务 100ms 走表：工作时长 0.1s 精度持续更新。
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNowTick(Date.now()), 100);
    return () => window.clearInterval(timer);
  }, [active]);

  const elapsedText = (() => {
    const start = parseBackendTime(archive.created_at);
    if (!start) return null;
    const total = Math.max(0, (nowTick - start.getTime()) / 1000);
    if (total < 60) return `${total.toFixed(1)} 秒`;
    const minutes = Math.floor(total / 60);
    const sec = total - minutes * 60;
    if (minutes < 60) return `${minutes} 分 ${sec.toFixed(1)} 秒`;
    const hours = Math.floor(minutes / 60);
    return `${hours} 时 ${minutes % 60} 分 ${Math.floor(sec)} 秒`;
  })();


  // 数据到达 → 重建行；切换任务时从头流式展开。
  useEffect(() => {
    if (prevRunRef.current !== archive.id) {
      prevRunRef.current = archive.id;
      prevLenRef.current = 0;
      setRevealed(0);
    }
    setLines(buildStreamLines(archive, zh));
  }, [archive, zh]);

  // 逐行揭示：切换任务后的初始大段按较快步长扫屏；轮询新追加的行按
  // 固定小步长（~30ms/行）流式放出——绝不整块闪现。
  useEffect(() => {
    if (revealed >= lines.length) {
      prevLenRef.current = lines.length;
      return;
    }
    const initialSweep = revealed === 0 && lines.length > 0;
    const fresh = Math.max(1, lines.length - prevLenRef.current);
    const step = initialSweep
      ? Math.max(1, Math.ceil(lines.length / 90))
      : Math.max(1, Math.ceil(fresh / 20));
    const delay = initialSweep ? 24 : 30;
    const timer = window.setTimeout(() => {
      setRevealed((cur) => Math.min(lines.length, cur + step));
    }, delay);
    return () => window.clearTimeout(timer);
  }, [revealed, lines]);

  // 跟随最新：揭示与轮询更新时自动滚到底部（用户上翻即暂停跟随）。
  useEffect(() => {
    const el = streamRef.current;
    if (el && followRef.current) el.scrollTop = el.scrollHeight;
  }, [revealed, lines]);

  const visible = lines.slice(0, revealed);

  const sections = useMemo(() => {
    const out: StreamSection[] = [];
    lines.forEach((line, idx) => {
      if (line.kind === "section") out.push({ id: line.sectionId, label: line.sectionLabel ?? line.text ?? "", startIndex: idx });
    });
    const finalIdx = lines.findIndex((l) => l.kind === "outcome");
    if (finalIdx >= 0) out.push({ id: "final", label: zh ? "结果" : "Result", startIndex: finalIdx });
    return out;
  }, [lines, zh]);

  const onScroll = () => {
    const el = streamRef.current;
    if (!el) return;
    followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    let current = sections[0]?.id ?? "";
    for (const section of sections) {
      if (revealed > section.startIndex) current = section.id;
    }
    setActiveSection(current);
  };

  // 大纲点击：展开至该章节并平滑滚动定位（getBoundingClientRect 相对滚动容器计算，
  // 修复旧 offsetTop 相对错误定位父级导致的跳转失效）。
  const jump = (section: StreamSection) => {
    setRevealed(lines.length);
    followRef.current = false;
    window.setTimeout(() => {
      const el = streamRef.current;
      const node = el?.querySelector(`[data-line-idx="${section.startIndex}"]`);
      if (el && node) {
        const top = node.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop;
        el.scrollTo({ top: Math.max(0, top - 8), behavior: "smooth" });
      }
    }, 80);
  };

  return (
    <div className="agent-stream-wrap" style={{ marginTop: 4 }}>
      <div className="agent-outline" role="tablist" aria-label={zh ? "章节导航" : "Sections"}>
        {sections.map((section) => (
          <button
            key={section.id}
            type="button"
            role="tab"
            aria-selected={activeSection === section.id}
            className={activeSection === section.id ? "on" : ""}
            onClick={() => jump(section)}
          >
            <span className="tick" />{section.label}
          </button>
        ))}
      </div>
      <div className="agent-stream" ref={streamRef} onScroll={onScroll}>
        {visible.map((line, idx) => (
          <div
            key={line.key}
            data-line-idx={idx}
            className={`agent-line${line.kind === "section" ? " agent-line-section" : line.kind === "mono" ? " agent-line-mono" : ""}${line.tone ? ` tone-${line.tone}` : ""}`}
          >
            {line.kind === "outcome" ? <TerminalOutcome archive={archive} zh={zh} /> : line.text}
          </div>
        ))}
        {active ? (
          <div className="agent-line agent-spin-line">
            <span className="agent-workdot" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /><i /><i /></span>
            <span>{zh ? "工作中" : "Working"}</span>
            <span>{zh ? `阶段：${STAGE_LABELS[archive.current_stage]?.zh ?? archive.current_stage}` : `Stage: ${STAGE_LABELS[archive.current_stage]?.en ?? archive.current_stage}`}</span>
            <span className="agent-worktime">{elapsedText ?? "--"}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** 终态块：成功给绿色验收信号；失败给「信号+原因+建议」，技术码仅作小字备注。 */
function TerminalOutcome({ archive, zh }: { archive: AgentRunDetail; zh: boolean }) {
  const explain = archive.error_code ? TERMINAL_EXPLAIN[archive.error_code] : undefined;
  const accepted = archive.status === "accepted";
  // waiting_escalate 是"暂停待人工决策"而非致命失败：用琥珀色与 ⏸ 区分，
  // 避免用户误读为系统错误。
  const escalated = archive.status === "waiting_escalate";
  return (
    <div style={{
      border: `1px solid ${accepted ? "rgba(71,195,160,.45)" : escalated ? "rgba(250,173,20,.45)" : "rgba(230,111,117,.45)"}`,
      background: accepted ? "rgba(71,195,160,.07)" : escalated ? "rgba(250,173,20,.08)" : "rgba(230,111,117,.07)",
      borderRadius: 9, padding: "10px 12px", marginBottom: 6,
    }}>
      <div className="meta">
        <b style={{ color: accepted ? "var(--v2-green)" : escalated ? "var(--v2-gold)" : "var(--v2-red)", fontSize: 13 }}>
          {accepted
            ? (zh ? "✓ 验收通过" : "✓ Accepted")
            : escalated
              ? `⏸ ${zh ? "未达验收标准 · 待人工决策" : "Below gates · needs decision"}`
              : `✕ ${zh ? "任务未通过" : "Not accepted"}`}
        </b>
        <span>{explain?.signal ?? archive.status}</span>
        <span style={{ marginLeft: "auto" }}>{relativeTime(archive.updated_at ?? archive.created_at, zh)}</span>
      </div>
      {!accepted ? (
        <div className="body" style={{ marginTop: 4 }}>
          {explain ? (
            <>
              <div>{zh ? "原因：" : "Why: "}{explain.why}</div>
              <div style={{ color: "var(--v2-gold)" }}>{explain.advice}</div>
            </>
          ) : (
            <div>{zh ? "原因与建议见上方「待人工决策原因」与技术详情。" : "See the decision note and technical details above."}</div>
          )}
          {archive.error_code ? <div className="mono" style={{ marginTop: 4 }}>code: {archive.error_code} · {archive.status}</div> : null}
        </div>
      ) : (
        <div className="body" style={{ marginTop: 4 }}>
          {zh ? "全部硬门禁与评审通过，配方可在下方固化与服务化。" : "All gates and review passed."}
        </div>
      )}
    </div>
  );
}

