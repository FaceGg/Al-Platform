import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

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

function greeting(zh: boolean): string {
  const hour = new Date().getHours();
  const word = hour < 6 ? (zh ? "凌晨好" : "Good early morning")
    : hour < 12 ? (zh ? "早上好" : "Good morning")
    : hour < 18 ? (zh ? "下午好" : "Good afternoon")
    : zh ? "晚上好" : "Good evening";
  return word;
}

function relativeTime(iso?: string, zh = true): string {
  if (!iso) return "-";
  const delta = Date.now() - new Date(iso).getTime();
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
  if (["completed", "succeeded", "done", "成功"].some((k) => s.includes(k))) return "v2-bg";
  if (["failed", "error", "cancelled"].some((k) => s.includes(k))) return "v2-br";
  if (["queued", "pending", "waiting"].some((k) => s.includes(k))) return "v2-bgo";
  return "v2-bgray";
};

export default function PortalPage() {
  const navigate = useNavigate();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const username = localStorage.getItem("username") || "admin";

  const [recentJobs, setRecentJobs] = useState<RecentJob[]>([]);
  const [projectCount, setProjectCount] = useState<number | null>(null);
  const [health, setHealth] = useState<string>("…");

  useEffect(() => {
    apiClient.get("/training/automl/jobs").then((res) => {
      const items = Array.isArray(res.data?.items) ? res.data.items : Array.isArray(res.data) ? res.data : [];
      setRecentJobs(items.slice(0, 4));
    }).catch(() => setRecentJobs([]));
    apiClient.get("/projects").then((res) => {
      const items = res.data?.items ?? res.data;
      setProjectCount(Array.isArray(items) ? items.length : null);
    }).catch(() => setProjectCount(null));
    apiClient.get("/health").then(() => setHealth(zh ? "正常" : "OK")).catch(() => setHealth(zh ? "不可用" : "down"));
  }, [zh]);

  const go = (path: string) => navigate(path);

  const quickButtons = [
    { icon: "🤖", cls: "v2-c-purple", title: zh ? "新建智能体建模任务" : "New agent modeling job", desc: zh ? "四步向导 · 全自动迭代" : "4-step wizard · auto iteration", path: "/automl" },
    { icon: "📤", cls: "v2-c-blue", title: zh ? "上传数据集" : "Upload dataset", desc: zh ? "CSV / Excel，自动画像" : "CSV / Excel, auto profile", path: "/data" },
    { icon: "🔄", cls: "v2-c-blue", title: zh ? "新建闭环任务" : "New closed-loop job", desc: zh ? "推理-回流-重训-换模" : "infer - retrain - rollout", path: "/demo-loop" },
    { icon: "🛒", cls: "v2-c-blue", title: zh ? "API 市场" : "API market", desc: zh ? "模型 / 编排服务调用" : "model / orchestration APIs", path: "/api-marketplace" },
    { icon: "☸", cls: "v2-c-green", title: zh ? "集群状态" : "Cluster status", desc: zh ? "K8s 节点与作业" : "K8s nodes and jobs", path: "/kubernetes" },
  ];

  const cards = [
    {
      icon: "🧪", cls: "v2-c-blue", title: zh ? "算法平台（建模中心）" : "Algorithm Platform",
      desc: zh ? "数据到模型的主链路：数据、标注、建模、编排与闭环服务化。" : "Data-to-model pipeline: datasets, labeling, modeling, orchestration and closed loops.",
      chips: zh ? ["数据管理", "数据标注", "自动建模", "模型训练", "模型库", "应用编排", "闭环自动化", "API 市场"] : ["Datasets", "Labeling", "AutoML", "Training", "Models", "Orchestration", "Closed loop", "API market"],
      stat: projectCount != null ? (zh ? `${projectCount} 项目` : `${projectCount} projects`) : "",
      path: "/automl",
    },
    {
      icon: "🤖", cls: "v2-c-purple", title: zh ? "智能体中心" : "Agent Center", badge: "NEW",
      desc: zh ? "大模型驱动的自动建模 Agent 与知识体系：四步向导引导、配方固化复用、经验越用越强。" : "LLM-driven modeling agent with recipes, experience and knowledge.",
      chips: zh ? ["建模智能体向导", "任务列表", "配方库", "知识中心", "AI 对话", "知识图谱"] : ["Wizard", "Jobs", "Recipes", "Knowledge", "Chat", "Graph"],
      hot: [0, 1, 2, 3],
      stat: recentJobs.length ? (zh ? `${recentJobs.filter((j) => statusBadge(String(j.status ?? j.state ?? "")) === "v2-bb").length || 0} 任务运行中` : "") : "",
      path: "/agent",
    },
    {
      icon: "☸", cls: "v2-c-green", title: zh ? "基础设施（运行时）" : "Infrastructure",
      desc: zh ? "算力与运行环境：K8s 集群、作业、Notebook、镜像与资源治理。" : "Compute and runtime: K8s, jobs, notebooks, images and governance.",
      chips: zh ? ["K8s 集群", "作业运行", "Notebook 会话", "镜像目录", "集群治理", "资源监控", "计算资源"] : ["K8s", "Jobs", "Notebooks", "Images", "Governance", "Monitor", "Compute"],
      path: "/kubernetes",
    },
    {
      icon: "⚙", cls: "v2-c-gold", title: zh ? "系统管理" : "Administration",
      desc: zh ? "平台级管理：用户、权限、大模型网关与审计。" : "Platform administration: users, roles, LLM gateway and audit.",
      chips: zh ? ["大模型网关", "用户管理"] : ["LLM gateway", "Users"],
      path: "/llm-gateway",
    },
  ];

  return (
    <AppLayout>
      <div className="v2-hero">
        <div>
          <h1>{greeting(zh)}，{username} —— {zh ? "一个平台，三大中心：" : "One platform, three centers: "}
            <em>{zh ? "算法 · 智能体 · 基础设施" : "Algorithms · Agents · Infra"}</em>
          </h1>
          <p>{zh
            ? "原左侧 25+ 项长菜单按职责拆分为五个工作区，各中心自带精简子菜单；新增「智能体中心」承载大模型驱动的自动建模 Agent。点击卡片进入对应中心。"
            : "The 25+ item menu is now five focused workspaces; the new Agent Center hosts the LLM-driven modeling agent."}</p>
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
            <h3>{c.title}{(c as { badge?: string }).badge ? <span className="v2-badge v2-bp">{zh ? "新" : "NEW"}</span> : null}</h3>
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
            <span className="more" onClick={() => go("/automl")}>{zh ? "全部 ›" : "All ›"}</span></h4>
          <table className="v2-table">
            <thead><tr>
              <th>{zh ? "类型" : "Type"}</th><th>{zh ? "名称" : "Name"}</th>
              <th>{zh ? "状态" : "Status"}</th><th>{zh ? "时间" : "Time"}</th>
            </tr></thead>
            <tbody>
              {recentJobs.length === 0 ? (
                <tr><td colSpan={4} className="v2-empty">{zh ? "暂无自动建模任务 —— 从上方「新建智能体建模任务」开始" : "No AutoML jobs yet — start from the wizard above"}</td></tr>
              ) : recentJobs.map((job) => (
                <tr key={String(job.id)}>
                  <td><span className="v2-badge v2-bp">{zh ? "建模任务" : "AutoML"}</span></td>
                  <td className="tt">{job.name ?? job.task_name ?? String(job.id)}</td>
                  <td><span className={`v2-badge ${statusBadge(String(job.status ?? job.state ?? ""))}`}>{job.status ?? job.state ?? "-"}</span></td>
                  <td>{relativeTime(job.updated_at ?? job.created_at, zh)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ flex: 1, minWidth: 280, display: "flex", flexDirection: "column", gap: 15 }}>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "平台公告" : "Notices"}</h4>
            <div style={{ fontSize: 12.5, lineHeight: 2 }}>
              <div>📌 <b style={{ color: "var(--v2-txt)" }}>{zh ? "智能体中心上线" : "Agent Center is live"}</b> —— {zh ? "建模智能体向导开放，欢迎试用" : "modeling agent wizard available"} <span style={{ color: "var(--v2-dim)", fontSize: 11 }}>2026-10</span></div>
              <div>{zh ? "大模型网关已切换 DeepSeek（deepseek-chat），连通验证通过" : "LLM gateway switched to DeepSeek, connectivity verified"} <span style={{ color: "var(--v2-dim)", fontSize: 11 }}>2026-10</span></div>
              <div>☸ {zh ? "五视图改版：门户 / 算法平台 / 智能体中心 / 基础设施 / 系统管理" : "Five-view redesign live"} <span style={{ color: "var(--v2-dim)", fontSize: 11 }}>2026-10</span></div>
            </div>
          </div>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "平台健康度" : "Health"}</h4>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)", borderBottom: "1px dashed rgba(36,52,79,.6)" }}>
              <span>● {zh ? "后端 API" : "Backend API"}</span>
              <span style={{ color: health === (zh ? "正常" : "OK") ? "var(--v2-green)" : "var(--v2-red)" }}>{health}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", fontSize: 12, color: "var(--v2-sub)", borderBottom: "1px dashed rgba(36,52,79,.6)" }}>
              <span>● {zh ? "大模型网关" : "LLM gateway"}</span><span style={{ color: "var(--v2-green)" }}>DeepSeek · {zh ? "已连通" : "connected"}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="v2-migrate">
        <h4>{zh ? "旧菜单 → 新中心 迁移映射（前端路由重组，功能不动）" : "Old menu → new centers mapping (routes only)"}</h4>
        <table className="v2-mtable"><tbody>
          <tr><td style={{ width: 130 }}><b>{zh ? "首页门户" : "Portal"}</b></td><td>{zh ? "工作台仪表板 · 项目管理（原首页收拢为门户，仪表板移入侧栏）" : "Dashboard · projects"}</td></tr>
          <tr><td><b>{zh ? "算法平台" : "Algorithms"}</b></td><td>{zh ? "数据管理 · 数据标注 · 自动建模 · 模型训练 · 模型库 · 算法目录 · 应用编排 · 闭环自动化 · API 市场" : "Data · labeling · AutoML · training · models · orchestration · closed loop · API market"}</td></tr>
          <tr><td><b>{zh ? "智能体中心" : "Agent Center"}</b></td><td>{zh ? "智能体中心（向导 / 任务 / 配方，新增）· AI 对话 · 知识中心 · 知识库 · 知识图谱（自原菜单迁入）" : "Agent center (new) · chat · knowledge"}</td></tr>
          <tr><td><b>{zh ? "基础设施" : "Infrastructure"}</b></td><td>{zh ? "K8s 集群 · 作业运行 · Notebook 会话 · 镜像目录 · 集群治理 · 资源监控 · 计算资源" : "K8s · jobs · notebooks · images · governance · monitor · compute"}</td></tr>
          <tr><td><b>{zh ? "系统管理" : "Administration"}</b></td><td>{zh ? "大模型网关 · 用户管理" : "LLM gateway · users"}</td></tr>
        </tbody></table>
      </div>
      <div className="v2-footer-note">灵工 Linkraft · {zh ? "平台改版 v2" : "Platform v2"} · 2026-10</div>
    </AppLayout>
  );
}
