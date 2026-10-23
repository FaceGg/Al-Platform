import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ReloadOutlined, PlusOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { listClusters, listClusterNodes, type ClusterInfo, type NodeCapability } from "../api/kubernetes";
import { listJobRuns, type JobRun } from "../api/kubernetesJobs";
import { listNotebooks } from "../api/notebooks";
import { useI18n } from "../i18n";

const statusBadge = (status: string): string => {
  const s = status.toLowerCase();
  if (["running", "active", "pending", "queued"].some((k) => s.includes(k))) return "v2-bb";
  if (["succeeded", "completed", "connected", "healthy"].some((k) => s.includes(k))) return "v2-bg";
  if (["failed", "error", "unreachable", "timed_out"].some((k) => s.includes(k))) return "v2-br";
  if (["warning", "degraded"].some((k) => s.includes(k))) return "v2-bgo";
  return "v2-bgray";
};

function relativeTime(iso?: string | null, zh = true): string {
  if (!iso) return "-";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return zh ? "刚刚" : "just now";
  if (minutes < 60) return zh ? `${minutes} 分钟前` : `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return zh ? `${hours} 小时前` : `${hours}h ago`;
  return zh ? `${Math.round(hours / 24)} 天前` : `${Math.round(hours / 24)}d ago`;
}

export default function InfraOverviewPage() {
  const navigate = useNavigate();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [clusters, setClusters] = useState<ClusterInfo[]>([]);
  const [nodesByCluster, setNodesByCluster] = useState<Record<string, NodeCapability[]>>({});
  const [jobs, setJobs] = useState<JobRun[]>([]);
  const [notebookTotal, setNotebookTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    listClusters().then((res) => {
      setClusters(res.items || []);
      // Nodes per cluster (clusters are few; one bounded call each).
      (res.items || []).slice(0, 4).forEach((cluster) => {
        listClusterNodes(cluster.id)
          .then((nodes) => setNodesByCluster((current) => ({ ...current, [cluster.id]: nodes.items || [] })))
          .catch(() => setNodesByCluster((current) => ({ ...current, [cluster.id]: [] })));
      });
    }).catch(() => setClusters([]));
    listJobRuns(0, 6).then((res) => setJobs(res.items || [])).catch(() => setJobs([]));
    listNotebooks(0, 1).then((res) => setNotebookTotal(res.total ?? null)).catch(() => setNotebookTotal(null));
    apiClient.get("/monitor/current").catch(() => undefined);
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  const nodeTotal = Object.values(nodesByCluster).reduce((sum, list) => sum + list.length, 0);
  const healthyClusters = clusters.filter((c) => ["connected", "healthy"].includes(String(c.status).toLowerCase())).length;
  const runningJobs = jobs.filter((j) => ["running", "pending", "queued"].includes(String(j.status).toLowerCase())).length;

  const kpis = [
    { label: zh ? "集群" : "Clusters", value: clusters.length || "—", hint: clusters.length ? `${healthyClusters}/${clusters.length} ${zh ? "连通" : "connected"}` : "" },
    { label: zh ? "节点" : "Nodes", value: nodeTotal || "—", hint: zh ? "已接入集群节点" : "across clusters" },
    { label: zh ? "近期作业" : "Recent jobs", value: jobs.length || "—", hint: zh ? `${runningJobs} 运行/排队中` : `${runningJobs} active` },
    { label: zh ? "Notebook 会话" : "Notebooks", value: notebookTotal ?? "—", hint: zh ? "活跃会话总数" : "sessions" },
  ];

  return (
    <AppLayout>
      <div className="v2-crumb">{zh ? "基础设施 / " : "Infrastructure / "}<b>{zh ? "集群总览" : "Overview"}</b></div>
      <div className="v2-pagehead">
        <div>
          <h2>{zh ? "集群总览" : "Cluster overview"}</h2>
          <div className="v2-pdesc">{zh
            ? "运行时能力独立成中心；算法平台与智能体提交的训练全部调度到这里。"
            : "Runtime as its own center; every training job from the platform lands here."}</div>
        </div>
        <div style={{ display: "flex", gap: 9 }}>
          <button type="button" className="v2-btn" onClick={load}><ReloadOutlined spin={loading} />{zh ? "刷新" : "Refresh"}</button>
          <button type="button" className="v2-btn primary" onClick={() => navigate("/kubernetes")}>
            <PlusOutlined />{zh ? "接入集群" : "Connect cluster"}
          </button>
        </div>
      </div>

      <div className="v2-kpis">
        {kpis.map((k) => (
          <div key={k.label} className="v2-kpi">
            <div className="lb">{k.label}</div>
            <div className="v">{k.value}</div>
            <div className="t">{k.hint}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 15, flexWrap: "wrap" }}>
        <div className="v2-panel" style={{ flex: "1.5", minWidth: 320 }}>
          <h4>
            <span className="bar" />{zh ? "集群状态" : "Clusters"}
            <span className="more" onClick={() => navigate("/kubernetes")}>{zh ? "K8s 集群 ›" : "Clusters ›"}</span>
          </h4>
          <table className="v2-table">
            <thead><tr>
              <th>{zh ? "集群" : "Cluster"}</th><th>{zh ? "状态" : "Status"}</th>
              <th>K8s</th><th>{zh ? "节点" : "Nodes"}</th><th>{zh ? "延迟" : "Latency"}</th><th>{zh ? "检查时间" : "Checked"}</th>
            </tr></thead>
            <tbody>
              {clusters.length === 0 ? (
                <tr><td colSpan={6} className="v2-empty">{zh
                  ? "暂无接入集群 —— 点右上「接入集群」开始"
                  : "No clusters connected yet"}</td></tr>
              ) : null}
              {clusters.map((c) => (
                <tr key={c.id}>
                  <td className="tt">{c.display_name || c.name}</td>
                  <td><span className={`v2-badge ${statusBadge(c.status)}`}>{c.status}</span>
                    {c.last_check_error_code ? <span style={{ marginLeft: 6, fontSize: 11, color: "var(--v2-dim)" }}>{c.last_check_error_code}</span> : null}</td>
                  <td>{c.kubernetes_version ?? "-"}</td>
                  <td>{nodesByCluster[c.id]?.length ?? "…"}</td>
                  <td>{c.last_check_latency_ms != null ? `${c.last_check_latency_ms}ms` : "-"}</td>
                  <td>{relativeTime(c.last_checked_at, zh)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ flex: 1, minWidth: 280 }}>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "节点清单" : "Nodes"}</h4>
            {Object.keys(nodesByCluster).length === 0 ? (
              <div className="v2-empty">{zh ? "暂无节点数据" : "No node data"}</div>
            ) : Object.entries(nodesByCluster).map(([clusterId, nodeList]) => {
              const cluster = clusters.find((c) => c.id === clusterId);
              return (
                <div key={clusterId} style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 11.5, color: "var(--v2-dim)", margin: "6px 0 3px" }}>{cluster?.display_name || cluster?.name || clusterId}</div>
                  {nodeList.slice(0, 5).map((n) => (
                    <div key={n.hostname} style={{ display: "flex", justifyContent: "space-between", padding: "3.5px 0", fontSize: 12, color: "var(--v2-sub)", borderBottom: "1px dashed rgba(36,52,79,.6)" }}>
                      <span>● {n.hostname}</span>
                      <span>{n.cpu_cores || "-"}C · {n.memory || "-"}{n.gpu && n.gpu !== "0" ? ` · GPU ${n.gpu}` : ""}</span>
                    </div>
                  ))}
                  {nodeList.length > 5 ? <div style={{ fontSize: 11, color: "var(--v2-dim)", marginTop: 4 }}>+{nodeList.length - 5} …</div> : null}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="v2-panel">
        <h4>
          <span className="bar" />{zh ? "近期作业" : "Recent jobs"}
          <span className="more" onClick={() => navigate("/kubernetes/jobs")}>{zh ? "作业运行 ›" : "Jobs ›"}</span>
        </h4>
        <table className="v2-table">
          <thead><tr>
            <th>{zh ? "作业" : "Job"}</th><th>{zh ? "命名空间" : "Namespace"}</th>
            <th>{zh ? "镜像" : "Image"}</th><th>{zh ? "状态" : "Status"}</th><th>{zh ? "提交时间" : "Submitted"}</th>
          </tr></thead>
          <tbody>
            {jobs.length === 0 ? (
              <tr><td colSpan={5} className="v2-empty">{zh ? "暂无作业记录" : "No jobs yet"}</td></tr>
            ) : null}
            {jobs.map((job) => (
              <tr key={job.id}>
                <td className="tt">{job.job_name}</td>
                <td>{job.namespace}</td>
                <td title={job.image_ref}>{job.image_ref ? (job.image_ref.length > 30 ? job.image_ref.slice(0, 30) + "…" : job.image_ref) : "-"}</td>
                <td><span className={`v2-badge ${statusBadge(job.status)}`}>{job.status}</span></td>
                <td>{relativeTime(job.submitted_at, zh)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppLayout>
  );
}
