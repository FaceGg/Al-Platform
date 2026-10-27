import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeftOutlined, ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import AgentRunArchivePanel from "../components/AgentRunArchivePanel";
import { getAgentRun, type AgentRunDetail } from "../api/agentCenter";
import { formatLocalTime } from "../utils/time";
import { useI18n } from "../i18n";

/** 智能体中心→任务详情页：单个 Agent 运行的全链路档案（/agent/task/:runId）。 */

const ACTIVE_STATUSES = new Set(["pending", "running"]);
// 非终态轮询间隔：S2 沙箱/LLM 阶段秒级产出，10s 足够"有新消息自动出现"。
const ACTIVE_POLL_MS = 10_000;

function runSeconds(created?: string | null, updated?: string | null): string {
  if (!created || !updated) return "—";
  const start = new Date(`${created}Z`.endsWith("Z") ? created : `${created}Z`).getTime();
  const end = new Date(`${updated}Z`.endsWith("Z") ? updated : `${updated}Z`).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "—";
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

  return (
    <AppLayout>
      <div className="v2-pagehead">
        <div>
          <h2>{zh ? "任务详情" : "Run detail"}</h2>
        </div>
        <div style={{ display: "flex", gap: 9 }}>
          <button type="button" className="v2-btn" onClick={() => navigate("/agent?tab=tasks")}>
            <ArrowLeftOutlined /> {zh ? "返回任务列表" : "Back to jobs"}
          </button>
          <button type="button" className="v2-btn" onClick={load}>
            <ReloadOutlined /> {zh ? "刷新" : "Refresh"}
          </button>
        </div>
      </div>

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
            <h4><span className="bar" />{zh ? "提交配置（向导引导）" : "Submitted guidance"}</h4>
            <table className="v2-table">
              <tbody>
                {Object.keys(gates).length ? (
                  <tr>
                    <td className="tt" style={{ width: 130 }}>{zh ? "指标门禁" : "Metric gates"}</td>
                    <td>{Object.entries(gates).map(([k, v]) => `${k} ≥ ${v}`).join("；")}</td>
                  </tr>
                ) : null}
                {whitelist.length ? (
                  <tr>
                    <td className="tt">{zh ? "算法白名单" : "Algorithm whitelist"}</td>
                    <td>{whitelist.join("、")}</td>
                  </tr>
                ) : null}
                <tr>
                  <td className="tt">{zh ? "数据形态" : "Data shape"}</td>
                  <td>{guidance.feature?.data_shape ?? (zh ? "未指定（自动）" : "auto")}</td>
                </tr>
                {(guidance.analysis?.prompts ?? []).length || (guidance.feature?.prompts ?? []).length || (guidance.modeling?.prompts ?? []).length ? (
                  <tr>
                    <td className="tt">{zh ? "自定义提示" : "Custom prompts"}</td>
                    <td style={{ fontSize: 12 }}>
                      {[...(guidance.analysis?.prompts ?? []), ...(guidance.feature?.prompts ?? []), ...(guidance.modeling?.prompts ?? [])]
                        .slice(0, 4).map((p, i) => <div key={i} className="ts">{p.length > 100 ? p.slice(0, 100) + "…" : p}</div>)}
                    </td>
                  </tr>
                ) : null}
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

