import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeftOutlined, DeleteOutlined, ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import AgentRunArchivePanel from "../components/AgentRunArchivePanel";
import { deleteAgentRun, getAgentRun, type AgentRunDetail } from "../api/agentCenter";
import { formatLocalTime } from "../utils/time";
import { useI18n } from "../i18n";

/** 智能体中心→任务详情页：单个 Agent 运行的全链路档案（/agent/task/:runId）。 */

const ACTIVE_STATUSES = new Set(["pending", "running"]);

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
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(() => {
    setArchiveError("");
    getAgentRun(runId).then(setArchive).catch(() => {
      setArchive(null);
      setArchiveError(zh ? "档案加载失败——任务不存在或已被清理" : "Failed to load archive");
    });
  }, [runId, zh]);

  useEffect(() => { load(); }, [load]);

  const remove = () => {
    setDeleting(true);
    deleteAgentRun(runId).then(() => {
      navigate("/agent?tab=tasks");
    }).catch(() => {
      setDeleting(false);
    });
  };

  const guidance = archive?.guidance_json ?? null;
  const gates = guidance?.evaluation?.metric_gates ?? {};
  const whitelist = guidance?.modeling?.algorithm_whitelist ?? [];
  const deletable = archive != null && !ACTIVE_STATUSES.has(archive.status);

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
          <button
            type="button"
            className="v2-btn"
            style={{ color: "var(--v2-red)", borderColor: "var(--v2-red)" }}
            disabled={!deletable || deleting}
            title={deletable ? "" : zh ? "运行中的任务不可删除" : "Active runs cannot be deleted"}
            onClick={() => { if (window.confirm(zh ? "确认删除该任务及其档案？此操作不可恢复。" : "Delete this run and its archive?")) remove(); }}
          >
            <DeleteOutlined /> {zh ? "删除任务" : "Delete"}
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
                <td className="tt">{zh ? "运行 ID" : "Run ID"}</td>
                <td className="tt" style={{ fontSize: 12 }}>{archive.id}</td>
                <td className="tt">{zh ? "数据集工件" : "Dataset artifact"}</td>
                <td className="tt" style={{ fontSize: 12 }}>{archive.dataset_artifact_id ?? "-"}</td>
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
                <td className="tt">{zh ? "最近心跳" : "Last heartbeat"}</td>
                <td>{archive.heartbeat_at ? formatLocalTime(archive.heartbeat_at, true) : "—"}</td>
              </tr>
              <tr>
                <td className="tt">Token</td>
                <td>{archive.token_used.toLocaleString()}{archive.token_budget ? ` / ${archive.token_budget.toLocaleString()}` : ""}</td>
                <td className="tt">{zh ? "逐步确认" : "Step-by-step"}</td>
                <td>{(guidance?.pause_at_stages ?? []).length ? (guidance!.pause_at_stages!.join(" → ").toUpperCase()) : (zh ? "关闭" : "off")}</td>
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
                <tr>
                  <td className="tt">{zh ? "泄漏关注列" : "Leakage focus"}</td>
                  <td>{(guidance.analysis?.suspect_focus ?? []).length ? (guidance.analysis!.suspect_focus!.join("、")) : (zh ? "未指定" : "none")}</td>
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
        onRefresh={load}
      />
    </AppLayout>
  );
}
