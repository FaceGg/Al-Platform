import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Tag } from "antd";
import {
  AppstoreOutlined,
  ClusterOutlined,
  CloudUploadOutlined,
  DeploymentUnitOutlined,
  ApiOutlined,
  ExperimentOutlined,
  PushpinOutlined,
  RobotOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { listAgentRuns } from "../api/agentCenter";
import { useI18n } from "../i18n";
import { parseBackendTime } from "../utils/time";

interface RecentJob {
  id: number | string;
  name?: string;
  task_name?: string;
  status?: string;
  state?: string;
  progress?: number;
  created_at?: string;
  updated_at?: string;
  project_name?: string;
}

// 「我的最近」合并条目：AutoML 任务与智能体任务统一形态，按时间排序
interface RecentItem {
  key: string;
  type: "automl" | "agent";
  name: string;
  status: string;
  time?: string | null;
  path: string;
}

interface ServiceReadiness {
  ready?: boolean;
  database?: { ready?: boolean };
  redis?: { ready?: boolean };
  storage?: { ready?: boolean };
  mlflow?: { ready?: boolean };
  celery?: { ready?: boolean };
}

interface Announcement {
  id: string;
  title: string;
  content: string;
  pinned: boolean;
  created_at?: string;
}

function greeting(zh: boolean): string {
  const hour = new Date().getHours();
  const word = hour < 6 ? (zh ? "凌晨好" : "Good early morning")
    : hour < 12 ? (zh ? "早上好" : "Good morning")
    : hour < 18 ? (zh ? "下午好" : "Good afternoon")
    : zh ? "晚上好" : "Good evening";
  return word;
}

function relativeTime(iso?: string, zh = true): string {
  // 后端时间为无时区 UTC ISO，必须经 parseBackendTime 补 Z 再解析。
  const parsed = parseBackendTime(iso);
  if (!parsed) return "-";
  const delta = Date.now() - parsed.getTime();
  const minutes = Math.round(delta / 60000);
  if (minutes < 1) return zh ? "刚刚" : "just now";
  if (minutes < 60) return zh ? `${minutes} 分钟前` : `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return zh ? `${hours} 小时前` : `${hours}h ago`;
  const days = Math.round(hours / 24);
  return zh ? `${days} 天前` : `${days}d ago`;
}

const statusBadge = (status: string): string => {
  const s = status.toLowerCase();
  if (["running", "progressing", "迭代中"].some((k) => s.includes(k))) return "v2-bb";
  if (["completed", "succeeded", "done", "成功", "accepted"].some((k) => s.includes(k))) return "v2-bg";
  if (["failed", "error", "cancelled"].some((k) => s.includes(k))) return "v2-br";
  if (["queued", "pending", "waiting"].some((k) => s.includes(k))) return "v2-bgo";
  return "v2-bgray";
};

export default function PortalPage() {
  const navigate = useNavigate();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const username = localStorage.getItem("username") || "admin";

  const [automlItems, setAutomlItems] = useState<RecentItem[]>([]);
  const [agentItems, setAgentItems] = useState<RecentItem[]>([]);
  const [agentRunningCount, setAgentRunningCount] = useState(0);
  const [projectCount, setProjectCount] = useState<number | null>(null);
  const [health, setHealth] = useState<string>("…");
  const [services, setServices] = useState<string>("…");
  const [announcements, setAnnouncements] = useState<Announcement[]>([]);
  const [gateway, setGateway] = useState<{ label: string; ok: boolean }>({ label: zh ? "检测中…" : "checking…", ok: false });

  useEffect(() => {
    apiClient.get("/training/automl/jobs").then((res) => {
      const items = Array.isArray(res.data?.items) ? res.data.items : Array.isArray(res.data) ? res.data : [];
      setAutomlItems(items.slice(0, 4).map((job: RecentJob): RecentItem => ({
        key: `automl-${job.id}`,
        type: "automl",
        name: job.name ?? job.task_name ?? String(job.id),
        status: String(job.status ?? job.state ?? "-"),
        time: job.updated_at ?? job.created_at,
        path: `/automl/task/${job.id}`,
      })));
    }).catch(() => setAutomlItems([]));
    listAgentRuns().then((runs) => {
      setAgentRunningCount(runs.filter((r) => r.status === "running").length);
      setAgentItems(runs.slice(0, 8).map((run) => ({
        key: `agent-${run.id}`,
        type: "agent" as const,
        name: run.project_name
          ? `${run.project_name} · ${run.target_column ?? "-"}`
          : `${zh ? "智能体任务" : "Agent"} ${run.id.slice(0, 8)}`,
        status: run.status,
        time: run.updated_at ?? run.created_at,
        path: `/agent/task/${run.id}`,
      })));
    }).catch(() => {
      setAgentRunningCount(0);
      setAgentItems([]);
    });
    apiClient.get("/projects").then((res) => {
      const items = res.data?.items ?? res.data;
      setProjectCount(Array.isArray(items) ? items.length : null);
    }).catch(() => setProjectCount(null));
    // 平台健康度：/health 探活 + /ready 细分基础服务就绪状态（均为真实接口）
    apiClient.get("/health").then(() => setHealth(zh ? "正常" : "OK")).catch(() => setHealth(zh ? "不可用" : "down"));
    apiClient.get("/ready").then((res) => {
      const data: ServiceReadiness = res.data ?? {};
      const parts: Array<[string, boolean | undefined]> = [
        [zh ? "数据库" : "DB", data.database?.ready],
        ["Redis", data.redis?.ready],
        [zh ? "存储" : "Storage", data.storage?.ready],
        ["MLflow", data.mlflow?.ready],
      ];
      const bad = parts.filter(([, ok]) => ok === false);
      setServices(bad.length === 0
        ? (zh ? "正常" : "OK")
        : (zh ? `异常（${bad.map(([n]) => n).join("、")}）` : `down (${bad.map(([n]) => n).join(", ")})`));
    }).catch(() => setServices(zh ? "不可用" : "down"));
    apiClient.get("/announcements").then((res) => {
      setAnnouncements(Array.isArray(res.data) ? res.data.slice(0, 5) : []);
    }).catch(() => setAnnouncements([]));
    apiClient.get("/llm-profiles").then((res) => {
      const profiles = Array.isArray(res.data) ? res.data : [];
      const fallback = profiles.find((p: { is_default?: boolean }) => p.is_default) ?? profiles[0];
      setGateway(fallback
        ? { label: `${fallback.model_id ?? fallback.name ?? (zh ? "已配置" : "configured")} · ${zh ? "已配置" : "configured"}`, ok: true }
        : { label: zh ? "未配置" : "not configured", ok: false });
    }).catch(() => setGateway({ label: zh ? "未配置" : "not configured", ok: false }));
  }, [zh]);

  // 「我的最近」= AutoML + 智能体任务合并，按更新时间倒序取前 6。
  // 两路数据独立落 state、在此单向合并——先到的响应不会覆盖后到的。
  const recentItems = useMemo(() => {
    const time = (item: RecentItem) => parseBackendTime(item.time ?? undefined)?.getTime() ?? 0;
    return [...automlItems, ...agentItems].sort((a, b) => time(b) - time(a)).slice(0, 6);
  }, [automlItems, agentItems]);

  const go = (path: string) => navigate(path);

  const quickButtons = [
    { icon: <RobotOutlined />, cls: "v2-c-purple", title: zh ? "新建智能体建模任务" : "New agent modeling job", desc: zh ? "四步向导 · 全自动迭代" : "4-step wizard · auto iteration", path: "/agent?tab=wizard" },
    { icon: <CloudUploadOutlined />, cls: "v2-c-blue", title: zh ? "上传数据集" : "Upload dataset", desc: zh ? "CSV / Excel，自动画像" : "CSV / Excel, auto profile", path: "/data" },
    { icon: <DeploymentUnitOutlined />, cls: "v2-c-blue", title: zh ? "新建闭环任务" : "New closed-loop job", desc: zh ? "推理-回流-重训-换模" : "infer - retrain - rollout", path: "/demo-loop" },
    { icon: <ApiOutlined />, cls: "v2-c-blue", title: zh ? "API 市场" : "API market", desc: zh ? "模型 / 编排服务调用" : "model / orchestration APIs", path: "/api-marketplace" },
    { icon: <ClusterOutlined />, cls: "v2-c-green", title: zh ? "集群状态" : "Cluster status", desc: zh ? "K8s 节点与作业" : "K8s nodes and jobs", path: "/kubernetes" },
  ];

  const cards = [
    {
      icon: <ExperimentOutlined />, cls: "v2-c-blue", title: zh ? "算法平台（建模中心）" : "Algorithm Platform",
      desc: zh ? "数据到模型的主链路：数据、标注、建模、编排与闭环服务化。" : "Data-to-model pipeline: datasets, labeling, modeling, orchestration and closed loops.",
      chips: zh ? ["数据管理", "数据标注", "自动建模", "模型训练", "模型库", "应用编排", "闭环自动化", "API 市场"] : ["Datasets", "Labeling", "AutoML", "Training", "Models", "Orchestration", "Closed loop", "API market"],
      stat: projectCount != null ? (zh ? `${projectCount} 项目` : `${projectCount} projects`) : "",
      path: "/automl",
    },
    {
      icon: <RobotOutlined />, cls: "v2-c-purple", title: zh ? "智能体中心" : "Agent Center",
      desc: zh ? "大模型驱动的自动建模 Agent 与知识体系：四步向导引导、配方固化复用、经验越用越强。" : "LLM-driven modeling agent with recipes, experience and knowledge.",
      chips: zh ? ["建模智能体向导", "任务列表", "配方库", "知识中心", "AI 对话", "知识图谱"] : ["Wizard", "Jobs", "Recipes", "Knowledge", "Chat", "Graph"],
      hot: [0, 1, 2, 3],
      stat: agentRunningCount > 0 ? (zh ? `${agentRunningCount} 任务运行中` : `${agentRunningCount} running`) : "",
      path: "/agent",
    },
    {
      icon: <ClusterOutlined />, cls: "v2-c-green", title: zh ? "基础设施（运行时）" : "Infrastructure",
      desc: zh ? "算力与运行环境：K8s 集群、作业、Notebook、镜像与资源治理。" : "Compute and runtime: K8s, jobs, notebooks, images and governance.",
      chips: zh ? ["K8s 集群", "作业运行", "Notebook 会话", "镜像目录", "集群治理", "资源监控", "计算资源"] : ["K8s", "Jobs", "Notebooks", "Images", "Governance", "Monitor", "Compute"],
      path: "/kubernetes",
    },
    {
      icon: <SettingOutlined />, cls: "v2-c-gold", title: zh ? "系统管理" : "Administration",
      desc: zh ? "平台级管理：用户、权限、大模型管理与审计。" : "Platform administration: users, roles, LLM management and audit.",
      chips: zh ? ["用户管理", "公告管理", "审计日志", "平台状态", "大模型管理"] : ["Users", "Announcements", "Audit", "Platform status", "LLM management"],
      path: "/admin/users",
    },
  ];

  return (
    <AppLayout>
      <div className="v2-hero">
        <div>
          <h1>{greeting(zh)}，{username} —— {zh ? "一个平台，三大中心：" : "One platform, three centers: "}
            <em>{zh ? "算法 · 智能体 · 基础设施" : "Algorithms · Agents · Infra"}</em>
          </h1>
        </div>
        <div className="meta">
          {new Date().toLocaleDateString(zh ? "zh-CN" : "en-US", { year: "numeric", month: "2-digit", day: "2-digit", weekday: "long" })}
          <br />{zh ? "平台运行中" : "Platform up"}<br />
          {zh ? "后端 API：" : "API: "}{health}
        </div>
      </div>

      <div className="v2-quickbar">
        {quickButtons.map((b) => (
          <button type="button" key={b.title} className="v2-qbtn" onClick={() => go(b.path)}>
            <span className={`ic ${b.cls}`}>{b.icon}</span>
            <div style={{ textAlign: "left" }}><b style={{ color: "inherit" }}>{b.title}</b><br />
              <span style={{ fontSize: 11, color: "var(--v2-dim)" }}>{b.desc}</span></div>
          </button>
        ))}
      </div>

      <div className="v2-cards">
        {cards.map((c) => (
          <div key={c.title} className="v2-card" role="button" tabIndex={0}
            onClick={() => go(c.path)}
            onKeyDown={(e) => { if (e.key === "Enter") go(c.path); }}>
            <div className="go">{zh ? "进入 →" : "Open →"}</div>
            {c.stat ? <div className="stat">{c.stat}</div> : null}
            <div className={`icon ${c.cls}`}>{c.icon}</div>
            <h3>{c.title}</h3>
            <p>{c.desc}</p>
            <div className="v2-chips">
              {c.chips.map((chip, i) => (
                <span key={chip} className={`v2-chip${(c as { hot?: number[] }).hot?.includes(i) ? " hot" : ""}`}>{chip}</span>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 15, maxWidth: 1200, margin: "16px auto 0", flexWrap: "wrap" }}>
        <div className="v2-panel" style={{ flex: "1.5", minWidth: 320, margin: 0 }}>
          <h4><span className="bar" />{zh ? "我的最近" : "Recent"}
            <span className="more" onClick={() => go("/agent?tab=tasks")}>{zh ? "全部 ›" : "All ›"}</span></h4>
          <table className="v2-table">
            <thead><tr>
              <th>{zh ? "类型" : "Type"}</th><th>{zh ? "名称" : "Name"}</th>
              <th>{zh ? "状态" : "Status"}</th><th>{zh ? "时间" : "Time"}</th>
            </tr></thead>
            <tbody>
              {recentItems.length === 0 ? (
                <tr><td colSpan={4} className="v2-empty">{zh ? "暂无近期任务 —— 从上方「新建智能体建模任务」开始" : "No recent jobs — start from the wizard above"}</td></tr>
              ) : recentItems.map((item) => (
                <tr key={item.key} style={{ cursor: "pointer" }} onClick={() => go(item.path)}>
                  <td><span className={`v2-badge ${item.type === "agent" ? "v2-bb" : "v2-bp"}`}>{item.type === "agent" ? (zh ? "智能体任务" : "Agent") : (zh ? "建模任务" : "AutoML")}</span></td>
                  <td className="tt">{item.name}</td>
                  <td><span className={`v2-badge ${statusBadge(item.status)}`}>{item.status}</span></td>
                  <td>{relativeTime(item.time ?? undefined, zh)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ flex: 1, minWidth: 280, display: "flex", flexDirection: "column", gap: 15 }}>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "平台公告" : "Notices"}</h4>
            <div style={{ fontSize: 12.5, lineHeight: 2 }}>
              {announcements.length === 0 ? (
                <div style={{ color: "var(--v2-dim)" }}>{zh ? "暂无公告" : "No notices"}</div>
              ) : announcements.map((item) => (
                <div key={item.id}>
                  {item.pinned ? <PushpinOutlined style={{ color: "var(--v2-gold)", fontSize: 12, marginRight: 6 }} /> : null}<b style={{ color: "var(--v2-txt)" }}>{item.title}</b>
                  {item.content ? <span style={{ color: "var(--v2-dim)" }}> —— {item.content}</span> : null}
                  <span style={{ color: "var(--v2-dim)", fontSize: 11, marginLeft: 6 }}>
                    {(() => { const d = parseBackendTime(item.created_at); return d ? d.toLocaleDateString(zh ? "zh-CN" : "en-US") : ""; })()}
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "平台健康度" : "Health"}</h4>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)", borderBottom: "1px dashed rgba(36,52,79,.6)" }}>
              <span>· {zh ? "后端 API" : "Backend API"}</span>
              <span style={{ color: health === (zh ? "正常" : "OK") ? "var(--v2-green)" : "var(--v2-red)" }}>{health}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)", borderBottom: "1px dashed rgba(36,52,79,.6)" }}>
              <span>· {zh ? "数据库 / 基础服务" : "DB / services"}</span>
              <span style={{ color: services === (zh ? "正常" : "OK") ? "var(--v2-green)" : "var(--v2-gold, #faad14)" }}>{services}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)", borderBottom: "1px dashed rgba(36,52,79,.6)" }}>
              <span>· {zh ? "大模型配置" : "LLM config"}</span>
              <span style={{ color: gateway.ok ? "var(--v2-green)" : "var(--v2-red)" }}>{gateway.label}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="v2-footer-note">灵工 Linkraft</div>
    </AppLayout>
  );
}
