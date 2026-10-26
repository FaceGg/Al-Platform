import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeftOutlined, ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import AgentRunArchivePanel from "../components/AgentRunArchivePanel";
import { getAgentRun, type AgentRunDetail } from "../api/agentCenter";
import { useI18n } from "../i18n";

/** 智能体中心→任务详情页：单个 Agent 运行的全链路档案（/agent/task/:runId）。 */
export default function AgentRunDetailPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [archive, setArchive] = useState<AgentRunDetail | null>(null);
  const [archiveError, setArchiveError] = useState("");

  const load = useCallback(() => {
    setArchiveError("");
    getAgentRun(runId).then(setArchive).catch(() => {
      setArchive(null);
      setArchiveError(zh ? "档案加载失败——任务不存在或已被清理" : "Failed to load archive");
    });
  }, [runId, zh]);

  useEffect(() => { load(); }, [load]);

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
        <div className="v2-panel" style={{ marginBottom: 12 }}>
          <table className="v2-table">
            <tbody>
              <tr>
                <td className="tt" style={{ width: 120 }}>{zh ? "目标列" : "Target"}</td>
                <td>{archive.target_column ?? "-"}</td>
                <td className="tt" style={{ width: 120 }}>{zh ? "项目" : "Project"}</td>
                <td>{archive.project_name ?? "-"}</td>
              </tr>
              <tr>
                <td className="tt">{zh ? "模型" : "Model"}</td>
                <td>{archive.llm_model_id ?? "-"}</td>
                <td className="tt">{zh ? "阶段/轮次" : "Stage/Rounds"}</td>
                <td>{archive.current_stage.toUpperCase()} · {zh ? "轮" : "r"}{archive.round_count}</td>
              </tr>
            </tbody>
          </table>
        </div>
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
