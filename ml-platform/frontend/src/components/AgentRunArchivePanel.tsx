import { useEffect, useMemo, useRef, useState } from "react";
import { Spin } from "antd";
import { LoadingOutlined } from "@ant-design/icons";
import OptReportPanel from "./OptReportPanel";
import ServitizeActions from "./ServitizeActions";
import { parseBackendTime } from "../utils/time";
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

export default function AgentRunArchivePanel({ runId, archive, archiveError, zh, active, onClose, onRefresh }: Props) {
  const escalation = archive?.memory_json?.escalation;
  const activeStage = active && archive ? STAGE_LABELS[archive.current_stage] : null;
  return (
    <div style={{ marginTop: 12, border: "1px solid var(--v2-line)", borderRadius: 10, background: "var(--v2-bg)", padding: "12px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <b style={{ color: "var(--v2-txt)", fontSize: 13 }}>{zh ? "运行档案" : "Run archive"}</b>
        <span className="v2-badge v2-bgray">{runId.slice(0, 8)}</span>
        {archive ? (
          <>
            <span className={`v2-badge ${statusBadge(archive.status)}`}>{archive.status}</span>
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
            <b style={{ color: "var(--v2-red)" }}>{zh ? "升级原因" : "Escalation detail"}</b>
            <div style={{ color: "var(--v2-sub)", wordBreak: "break-all" }}>{escalation.detail}</div>
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

interface StreamSection {
  id: string;
  label: string;
  node: React.ReactNode;
}

function AgentStream({ archive, zh, active }: { archive: AgentRunDetail; zh: boolean; active: boolean }) {
  const streamRef = useRef<HTMLDivElement | null>(null);
  const followRef = useRef(true);
  const [activeId, setActiveId] = useState<string>("");

  const sections: StreamSection[] = useMemo(() => {
    const list: StreamSection[] = [];
    const rounds = archive.memory_json?.rounds ?? [];
    for (const round of rounds) {
      const id = `round-${round.round}`;
      list.push({ id, label: zh ? `第 ${round.round} 轮` : `Round ${round.round}`, node: <RoundBlock key={id} round={round} zh={zh} /> });
    }
    if (!rounds.length) {
      list.push({
        id: "empty",
        label: zh ? "暂无轮次" : "No rounds",
        node: (
          <div className="agent-msg" id="sec-empty">
            <div className="meta"><b>{zh ? "暂无轮次记录" : "No recorded rounds"}</b></div>
            <div className="body">{zh
              ? "该任务运行早于阶段产物落档案功能上线（2026-10-27）；新任务将逐阶段流式记录。"
              : "This run predates per-stage artifact persistence."}</div>
          </div>
        ),
      });
    }
    list.push({
      id: "final",
      label: zh ? "终态" : "Final",
      node: (
        <div className="agent-msg" id="sec-final" style={{ color: archive.status === "waiting_escalate" ? "var(--v2-red)" : "var(--v2-green)" }}>
          <div className="meta">
            <b>{zh ? "终态" : "Final"}</b>
            <span className={`v2-badge ${statusBadge(archive.status)}`}>{archive.status}</span>
            {archive.error_code ? <span className="mono">{archive.error_code}</span> : null}
            <span>{relativeTime(archive.updated_at ?? archive.created_at, zh)}</span>
          </div>
        </div>
      ),
    });
    return list;
  }, [archive, zh]);

  // 新内容到达时若用户停留在底部附近则自动跟随到最新。
  const signature = `${archive.round_count}:${archive.updated_at ?? ""}:${archive.token_used}`;
  useEffect(() => {
    const el = streamRef.current;
    if (el && followRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [signature]);

  const onScroll = () => {
    const el = streamRef.current;
    if (!el) return;
    followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    let current = sections[0]?.id ?? "";
    for (const section of sections) {
      const node = el.querySelector(`#sec-${section.id}`);
      if (node && (node as HTMLElement).offsetTop - el.scrollTop <= 60) current = section.id;
    }
    setActiveId(current);
  };

  const jump = (id: string) => {
    const el = streamRef.current;
    const node = el?.querySelector(`#sec-${id}`);
    if (el && node) {
      el.scrollTo({ top: Math.max(0, (node as HTMLElement).offsetTop - 8), behavior: "smooth" });
      followRef.current = false;
    }
  };

  const activeStageLabel = active ? STAGE_LABELS[archive.current_stage] : null;

  return (
    <div className="agent-stream-wrap" style={{ marginTop: 4 }}>
      <div className="agent-outline" role="tablist" aria-label={zh ? "章节导航" : "Sections"}>
        {sections.map((section) => (
          <button
            key={section.id}
            type="button"
            role="tab"
            aria-selected={activeId === section.id}
            className={activeId === section.id ? "on" : ""}
            onClick={() => jump(`sec-${section.id}`)}
          >
            <span className="tick" />{section.label}
          </button>
        ))}
      </div>
      <div className="agent-stream" ref={streamRef} onScroll={onScroll}>
        {sections.map((section) => section.node)}
        {activeStageLabel ? (
          <div className="agent-spin-line">
            <Spin size="small" />
            {zh ? `正在 ${activeStageLabel.zh}…（10s 自动刷新）` : `${activeStageLabel.en}…`}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function RoundBlock({ round, zh }: { round: NonNullable<AgentRunDetail["memory_json"]["rounds"]>[number]; zh: boolean }) {
  return (
    <div className="agent-msg" id={`sec-round-${round.round}`}>
      <div className="meta">
        <b>{zh ? `第 ${round.round} 轮` : `Round ${round.round}`}</b>
        {round.verdict ? <span className={`v2-badge ${round.verdict === "gate_failed" ? "v2-br" : "v2-bgo"}`}>{round.verdict}</span> : null}
      </div>

      {round.s1 ? (
        <div className="body" style={{ marginBottom: 8 }}>
          <div className="meta"><b>S1 · {zh ? "数据分析" : "Analysis"}</b></div>
          {round.s1.domain ? <div className="kv">{zh ? "域假设" : "Domain"}：<b style={{ color: "var(--v2-txt)" }}>{round.s1.domain}</b></div> : null}
          {round.s1.reasoning ? <div>{round.s1.reasoning.length > 260 ? round.s1.reasoning.slice(0, 260) + "…" : round.s1.reasoning}</div> : null}
          {(round.s1.focus_channels ?? []).length ? <div className="kv">{zh ? "关键通道" : "Channels"}：{(round.s1.focus_channels ?? []).map((c) => c.channel).filter(Boolean).join("、")}</div> : null}
          {(round.s1.leakage ?? []).length ? <div className="kv" style={{ color: "var(--v2-gold)" }}>{zh ? "泄漏嫌疑" : "Leakage"}：{(round.s1.leakage ?? []).map((l) => l.column).filter(Boolean).join("、")}</div> : null}
          {(round.s1.quality_actions ?? []).length ? <div className="kv">{zh ? "数据质量动作" : "Quality"}：{(round.s1.quality_actions ?? []).map((q) => q.action).filter(Boolean).join("；")}</div> : null}
          {round.s1.class_balance ? <div className="kv">{zh ? "类不平衡" : "Balance"}：{round.s1.class_balance}</div> : null}
        </div>
      ) : null}

      {(round.s2_attempts ?? []).map((attempt) => (
        <div key={attempt.attempt} className="mono" style={{ color: attempt.ok ? "var(--v2-green)" : "var(--v2-gold)", marginBottom: 2 }}>
          $ S2 {zh ? "尝试" : "attempt"} {attempt.attempt}: {attempt.ok ? (zh ? "通过沙箱" : "sandbox OK") : (attempt.error ?? "failed")}
          {Array.isArray(attempt.detail) && attempt.detail.length ? ` (${attempt.detail.slice(0, 3).join("; ")})` : ""}
        </div>
      ))}

      {round.s2 ? (
        <div className="body" style={{ marginBottom: 8 }}>
          <div className="meta">
            <b>S2 · {zh ? "特征工程" : "Features"}</b>
            <span>{zh ? `${round.s2.attempts ?? 1} 次尝试` : `${round.s2.attempts ?? 1} attempts`}{round.s2.data_shape ? ` · ${round.s2.data_shape}` : ""}</span>
          </div>
          {round.s2.description ? <div>{round.s2.description.length > 240 ? round.s2.description.slice(0, 240) + "…" : round.s2.description}</div> : null}
          {(round.s2.generated_columns ?? []).length ? <div className="kv" style={{ color: "var(--v2-green)" }}>{zh ? "新增" : "Added"}：{(round.s2.generated_columns ?? []).join("、")}</div> : null}
          {(round.s2.dropped_columns ?? []).length ? <div className="kv" style={{ color: "var(--v2-dim)" }}>{zh ? "剔除" : "Dropped"}：{(round.s2.dropped_columns ?? []).join("、")}</div> : null}
        </div>
      ) : null}

      {round.s3 ? (
        <div className="body" style={{ marginBottom: 8 }}>
          <div className="meta"><b>S3 · {zh ? "候选训练" : "Training"}</b></div>
          {Object.keys(round.s3.metrics ?? {}).length ? (
            <div className="mono">{Object.entries(round.s3.metrics ?? {}).slice(0, 8).map(([k, v]) => `${k}=${v}`).join("  ")}</div>
          ) : null}
          {(round.s3.importance ?? []).length ? <div className="kv">{zh ? "特征重要性" : "Importance"}：{(round.s3.importance ?? []).slice(0, 5).map((i) => `${i.feature}(${i.importance})`).join("、")}</div> : null}
        </div>
      ) : null}

      {round.s4 ? (
        <div className="body" style={{ marginBottom: 8 }}>
          <div className="meta">
            <b>S4 · {zh ? "硬门禁" : "Gates"}</b>
            <span className={`v2-badge ${round.s4.gate_passed ? "v2-bg" : "v2-br"}`}>{round.s4.gate_passed ? (zh ? "通过" : "passed") : (zh ? "未过" : "failed")}</span>
          </div>
          {(round.s4.gate_failures ?? []).length ? (
            <div className="mono" style={{ color: "var(--v2-gold)" }}>{(round.s4.gate_failures ?? []).slice(0, 4).map((f, i) => <div key={i}>· {f}</div>)}</div>
          ) : null}
        </div>
      ) : null}

      {round.review ? (
        <div className="body" style={{ marginBottom: 8 }}>
          <div className="meta">
            <b>{zh ? "评审" : "Review"}</b>
            <span className={`v2-badge ${round.review.verdict === "pass" ? "v2-bg" : "v2-bgo"}`}>{round.review.verdict ?? "-"}</span>
          </div>
          {round.review.readiness ? <div>{round.review.readiness.length > 240 ? round.review.readiness.slice(0, 240) + "…" : round.review.readiness}</div> : null}
          {(round.review.surprises ?? []).length ? <div className="kv" style={{ color: "var(--v2-gold)" }}>{zh ? "意外发现" : "Surprises"}：{(round.review.surprises ?? []).join("；")}</div> : null}
        </div>
      ) : null}

      {(round.hints ?? []).length ? (
        <div className="body">
          {(round.hints ?? []).slice(0, 3).map((hint, i) => (
            <div key={i} className="kv">· {hint.length > 120 ? hint.slice(0, 120) + "…" : hint}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
