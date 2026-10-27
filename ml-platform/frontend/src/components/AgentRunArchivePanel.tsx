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
  onClose?: () => void;
  onRefresh: () => void;
}

export default function AgentRunArchivePanel({ runId, archive, archiveError, zh, onClose, onRefresh }: Props) {
  const escalation = archive?.memory_json?.escalation;
  return (
    <div style={{ marginTop: 12, border: "1px solid var(--v2-line)", borderRadius: 10, background: "var(--v2-bg)", padding: "12px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <b style={{ color: "var(--v2-txt)", fontSize: 13 }}>{zh ? "运行档案" : "Run archive"}</b>
        <span className="v2-badge v2-bgray">{runId.slice(0, 8)}</span>
        {archive ? (
          <>
            <span className={`v2-badge ${statusBadge(archive.status)}`}>{archive.status}</span>
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
