import { useState } from "react";

/**
 * 本次优化总结面板（设计稿 sub-wiz 内 opt-report 的实现，§13.2 第五契约）：
 * what_optimized / findings / strengths / unsatisfactory（必带因果与缺失项）/
 * next_hints + cost（token/档案/轮数——全部平台计量，LLM 只做归因叙述）。
 * 数据来自 run.result_json.optimization_report（P0 收尾链自动生成）。
 */

interface OptimizationReportData {
  what_optimized?: string[];
  findings?: string[];
  strengths?: string[];
  unsatisfactory?: Array<{
    issue: string;
    cause: string;
    missing: string;
    suggestion: string;
  }>;
  next_hints?: string[];
  cost?: {
    llm_tokens?: number;
    llm_profile?: string;
    llm_model_id?: string;
    rounds_total?: number;
    token_budget?: number | null;
  };
}

export default function OptReportPanel({
  resultJson,
  zh,
}: {
  resultJson: Record<string, unknown> | null | undefined;
  zh: boolean;
}) {
  const [expanded, setExpanded] = useState(true);
  const report = (resultJson?.optimization_report ?? null) as OptimizationReportData | null;
  const distilled = (resultJson?.distilled_experience ?? []) as string[];
  if (!report) return null;

  const section = (
    title: string,
    items: string[] | undefined,
    color?: string
  ) =>
    items && items.length ? (
      <div style={{ minWidth: 220, flex: 1 }}>
        <div style={{ fontSize: 12, color: "var(--v2-dim)", marginBottom: 4 }}>{title}</div>
        {items.map((item, index) => (
          <div key={index} style={{ fontSize: 12, lineHeight: 1.7, color: color ?? "var(--v2-txt)" }}>
            · {item}
          </div>
        ))}
      </div>
    ) : null;

  return (
    <div style={{ marginTop: 10, border: "1px solid var(--v2-line)", borderRadius: 10, background: "var(--v2-bg)", padding: "10px 14px" }}>
      <div
        style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}
        onClick={() => setExpanded((cur) => !cur)}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter") setExpanded((cur) => !cur);
        }}
      >
        <b style={{ color: "var(--v2-txt)", fontSize: 13 }}>
          📋 {zh ? "本次优化总结" : "Optimization report"}
        </b>
        <span className="v2-badge v2-bgo">{zh ? "自动生成" : "auto"}</span>
        {report.cost?.llm_model_id ? (
          <span className="v2-badge v2-bp">{report.cost.llm_model_id}</span>
        ) : null}
        <span style={{ fontSize: 11, color: "var(--v2-dim)" }}>
          {report.cost?.llm_tokens?.toLocaleString() ?? "-"} tokens ·{" "}
          {zh ? "轮" : "rounds "}
          {report.cost?.rounds_total ?? "-"}
          {report.cost?.token_budget
            ? ` / ${report.cost.token_budget.toLocaleString()}`
            : ""}
        </span>
        <span style={{ marginLeft: "auto", color: "var(--v2-dim)", fontSize: 12 }}>
          {expanded ? "▾" : "▸"}
        </span>
      </div>

      {expanded ? (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginTop: 8 }}>
            {section(zh ? "优化了什么" : "What was optimized", report.what_optimized)}
            {section(zh ? "发现了什么" : "Findings", report.findings)}
            {section(zh ? "擅长什么" : "Strengths", report.strengths, "var(--v2-green)")}
            {section(zh ? "下一轮建议" : "Next hints", report.next_hints, "var(--v2-gold)")}
          </div>
          {report.unsatisfactory?.length ? (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 12, color: "var(--v2-dim)", marginBottom: 4 }}>
                {zh ? "不理想之处（带因果与缺失项）" : "Unsatisfactory (cause + missing)"}
              </div>
              {report.unsatisfactory.map((item, index) => (
                <div
                  key={index}
                  style={{
                    fontSize: 12,
                    lineHeight: 1.7,
                    padding: "4px 8px",
                    borderLeft: "2px solid var(--v2-gold)",
                    marginBottom: 4,
                    background: "rgba(255,209,102,.05)",
                  }}
                >
                  <b>{item.issue}</b>
                  {" — "}
                  {zh ? "因为" : "because "}
                  {item.cause}
                  {zh ? "；缺少" : "; missing "}
                  {item.missing}
                  {zh ? "；建议" : "; suggestion: "}
                  {item.suggestion}
                </div>
              ))}
            </div>
          ) : null}
          {distilled.length ? (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--v2-sub)" }}>
              🧬 {zh ? "本任务蒸馏经验" : "Distilled lessons"}：{distilled.length}{" "}
              {zh ? "条（已入经验库 shadow 冷静期）" : "(shadow cooldown)"}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
