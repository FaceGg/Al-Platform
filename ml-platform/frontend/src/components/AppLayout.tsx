import { Avatar, Badge, Dropdown, Modal, Descriptions, Tag } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  ProjectOutlined, LogoutOutlined, UserOutlined, TeamOutlined,
  DatabaseOutlined, AppstoreOutlined, CloudUploadOutlined, ThunderboltOutlined,
  ExperimentOutlined, ApiOutlined, CloudServerOutlined, RobotOutlined,
  MessageOutlined, MonitorOutlined, ClusterOutlined, DeploymentUnitOutlined,
  PlayCircleOutlined, BookOutlined, ControlOutlined, TagsOutlined, ApartmentOutlined,
  RocketOutlined, CopyOutlined, FileTextOutlined, SettingOutlined,
  NotificationOutlined, BarChartOutlined, SafetyCertificateOutlined, QuestionCircleOutlined,
  AlertOutlined, ToolOutlined, DashboardOutlined, AuditOutlined,
  FileProtectOutlined, ProfileOutlined, FolderOpenOutlined, FileDoneOutlined,
  SlidersOutlined, WarningOutlined, ShoppingOutlined,
} from "@ant-design/icons";
import { SunOutlined, MoonOutlined } from "@ant-design/icons";
import { useI18n } from "../i18n";
import { useTheme } from "../stores/themeContext";
import NotificationCenter from "./NotificationCenter";
import { navTitle, sectionName } from "./PageHeading";
import apiClient from "../api/client";
import "../styles/v2-shell.css";

type ViewId = "portal" | "algo" | "agent" | "quality" | "infra" | "admin";

interface SideEntry { key: string; icon: React.ReactNode; label: string; query?: string }
interface SideGroup { label: string; items: SideEntry[] }

/** Route prefix -> owning view. Longest prefix wins when resolving. */
const VIEW_ROUTES: Record<ViewId, string[]> = {
  portal: ["/"],
  algo: ["/algo", "/projects", "/workspace", "/template", "/models", "/data", "/data-annotation", "/automl", "/training", "/orchestration", "/demo-loop", "/annotations", "/algorithms", "/api-marketplace", "/algo/drift"],
  agent: ["/agent", "/knowledge-center", "/prompt-templates", "/knowledge", "/knowledge-graph", "/chat"],
  quality: ["/quality"],
  infra: ["/infra", "/kubernetes", "/notebooks", "/images", "/cluster-governance", "/monitor", "/compute"],
  admin: ["/llm-gateway", "/admin/llm-usage", "/admin/users", "/admin/announcements", "/admin/audit", "/admin/settings"],
};

/** Landing route for each top-level view tab (admin: first sidebar entry). */
const VIEW_HOME: Record<ViewId, string> = {
  portal: "/",
  algo: "/algo",
  agent: "/agent",
  quality: "/quality/scenes",
  infra: "/infra",
  admin: "/admin/users",
};

function resolveView(pathname: string): ViewId {
  const order: ViewId[] = ["algo", "agent", "quality", "infra", "admin", "portal"];
  let best: { view: ViewId; len: number } = { view: "portal", len: 0 };
  for (const view of order) {
    for (const prefix of VIEW_ROUTES[view]) {
      const match = prefix === "/" ? pathname === "/" : pathname === prefix || pathname.startsWith(`${prefix}/`);
      if (match && prefix.length > best.len) best = { view, len: prefix.length };
    }
  }
  return best.view;
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { lang, t, setLang } = useI18n();
  const { theme, toggleTheme } = useTheme();
  const [profileOpen, setProfileOpen] = useState(false);
  const storedRole = localStorage.getItem("role");
  const [userRole, setUserRole] = useState(storedRole || "user");

  const activeView = resolveView(location.pathname);
  const isAdmin = userRole === "admin";

  const zh = lang === "zh";
  // 菜单名与页面标题同源：一律经 navTitle 取 t.nav（缺键回退 PageHeading 内置表）；
  // 板块名一律取 PageHeading 的 SECTIONS。
  const nav = (key: string) => navTitle(t, key, zh);

  // 板块可见性（技术方案 §7.1）：服务端按角色解析（visible_views），
  // 缺省六视图全量；未加载完成前按全量渲染（避免闪没）。
  const [visibleViews, setVisibleViews] = useState<string[] | null>(null);
  useEffect(() => {
    if (!localStorage.getItem("token")) return;
    let active = true;
    apiClient.get("/auth/me").then((response) => {
      if (!active) return;
      const views = response.data?.visible_views;
      if (Array.isArray(views) && views.length > 0) setVisibleViews(views.map(String));
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);
  const viewVisible = (view: ViewId) =>
    isAdmin || visibleViews === null || visibleViews.includes(view);

  // 演示态标识（诚实设计⑥ / 技术方案 D33）：可访问的项目里有演示循环配置时提示
  // 「含演示数据」（演示样本与预警不计入真实 KPI）。
  // 〔修订 2026-11-27 用户指示〕该标识面向客户演示时起反作用（暴露演示性质）——
  // 默认不渲染，仅内部验收需要时打开隐藏开关（localStorage.showDemoBadge=1 或
  // URL ?demoBadge=1）。数据隔离口径不变（后端 is_demo 过滤照旧）。
  const [demoProjects, setDemoProjects] = useState<string[]>([]);
  useEffect(() => {
    if (!localStorage.getItem("token")) return;
    let active = true;
    apiClient.get("/demo-loop/presence").then((response) => {
      if (!active) return;
      const projects = response.data?.projects;
      if (Array.isArray(projects)) setDemoProjects(projects.map((item: { name?: string }) => String(item?.name ?? "")).filter(Boolean));
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);

  const allViewTabs: { id: ViewId; label: string; tag?: string }[] = [
    { id: "portal", label: sectionName("portal", zh) },
    { id: "algo", label: sectionName("algo", zh) },
    { id: "agent", label: sectionName("agent", zh) },
    { id: "quality", label: sectionName("quality", zh) },
    { id: "infra", label: sectionName("infra", zh) },
    ...(isAdmin ? [{ id: "admin" as ViewId, label: sectionName("admin", zh) }] : []),
  ];
  const viewTabs = allViewTabs.filter((tab) => viewVisible(tab.id));

  const sideGroups: Record<ViewId, SideGroup[]> = {
    portal: [],
    algo: [
      { label: zh ? "概览" : "Overview", items: [
        { key: "/algo", icon: <AppstoreOutlined />, label: nav("dashboard") },
        { key: "/projects", icon: <ProjectOutlined />, label: nav("projects") },
      ] },
      { label: zh ? "数据" : "Data", items: [
        { key: "/data", icon: <CloudUploadOutlined />, label: nav("data") },
        { key: "/data-annotation", icon: <TagsOutlined />, label: nav("data_annotation"), query: "view=tasks" },
      ] },
      { label: zh ? "建模" : "Modeling", items: [
        { key: "/automl", icon: <ThunderboltOutlined />, label: nav("automl") },
        { key: "/training", icon: <ExperimentOutlined />, label: nav("training") },
        { key: "/models", icon: <AppstoreOutlined />, label: nav("models") },
      ] },
      { label: zh ? "服务" : "Serving", items: [
        { key: "/demo-loop", icon: <DeploymentUnitOutlined />, label: nav("demo_loop") },
        { key: "/orchestration", icon: <RobotOutlined />, label: nav("orchestration") },
        { key: "/api-marketplace", icon: <ApiOutlined />, label: nav("api_market") },
      ] },
      { label: zh ? "模型运营" : "Model operations", items: [
        { key: "/algo/drift", icon: <CloudServerOutlined />, label: nav("drift_monitor") },
      ] },
    ],
    quality: [
      { label: zh ? "监控" : "Monitoring", items: [
        { key: "/quality/dashboard", icon: <DashboardOutlined />, label: nav("quality_dashboard") },
        { key: "/quality/monitor", icon: <MonitorOutlined />, label: nav("quality_monitor") },
        { key: "/quality/alerts", icon: <AlertOutlined />, label: nav("quality_alerts") },
        { key: "/quality/disposition", icon: <ToolOutlined />, label: nav("quality_disposition") },
        { key: "/quality/production-records", icon: <DatabaseOutlined />, label: nav("quality_production_records") },
      ] },
      { label: zh ? "分析" : "Analysis", items: [
        { key: "/quality/trends", icon: <BarChartOutlined />, label: nav("quality_trends") },
        { key: "/quality/spc", icon: <ControlOutlined />, label: nav("quality_spc") },
      ] },
      { label: zh ? "配置" : "Configuration", items: [
        { key: "/quality/scenes", icon: <AppstoreOutlined />, label: nav("quality_scenes") },
        { key: "/quality/stations", icon: <ClusterOutlined />, label: nav("quality_stations") },
        { key: "/quality/sops", icon: <FileTextOutlined />, label: nav("quality_sops") },
      ] },
      { label: zh ? "质量体系" : "Quality system", items: [
        { key: "/quality/ncr", icon: <FileProtectOutlined />, label: nav("quality_ncr") },
        { key: "/quality/d8", icon: <ProfileOutlined />, label: nav("quality_d8") },
        { key: "/quality/cases", icon: <FolderOpenOutlined />, label: nav("quality_cases") },
        { key: "/quality/knowledge", icon: <BookOutlined />, label: nav("quality_knowledge") },
        { key: "/quality/trace", icon: <ApartmentOutlined />, label: nav("quality_trace") },
        { key: "/quality/reports", icon: <FileDoneOutlined />, label: nav("quality_reports") },
        { key: "/quality/control-plans", icon: <SlidersOutlined />, label: nav("quality_control_plans") },
        { key: "/quality/msa", icon: <ExperimentOutlined />, label: nav("quality_msa") },
        { key: "/quality/fmea", icon: <WarningOutlined />, label: nav("quality_fmea") },
        { key: "/quality/iqc", icon: <ShoppingOutlined />, label: nav("quality_iqc") },
      ] },
    ],
    agent: [
      { label: zh ? "建模智能体" : "Modeling agent", items: [
        { key: "/agent", icon: <RocketOutlined />, label: nav("agent_new") },
        { key: "/agent", query: "tab=tasks", icon: <PlayCircleOutlined />, label: nav("agent_tasks") },
        { key: "/agent", query: "tab=recipes", icon: <DeploymentUnitOutlined />, label: nav("agent_recipes") },
        { key: "/agent", query: "tab=knowledge", icon: <BookOutlined />, label: nav("knowledge_center") },
      ] },
      { label: zh ? "知识与对话" : "Knowledge & chat", items: [
        { key: "/prompt-templates", icon: <CopyOutlined />, label: nav("prompt_templates") },
        { key: "/chat", icon: <MessageOutlined />, label: nav("chat") },
        { key: "/knowledge-graph", icon: <ApartmentOutlined />, label: t.knowledge?.graph || "Graph" },
      ] },
    ],
    infra: [
      { label: zh ? "集群" : "Cluster", items: [
        { key: "/infra", icon: <AppstoreOutlined />, label: nav("infra_overview") },
        { key: "/kubernetes", icon: <ClusterOutlined />, label: nav("kubernetes") },
        { key: "/cluster-governance", icon: <ControlOutlined />, label: nav("cluster_governance") },
      ] },
      { label: zh ? "运行" : "Runtime", items: [
        { key: "/kubernetes/jobs", icon: <PlayCircleOutlined />, label: nav("job_runs") },
        { key: "/notebooks", icon: <BookOutlined />, label: nav("notebooks") },
        { key: "/images", icon: <DatabaseOutlined />, label: nav("images") },
      ] },
      { label: zh ? "资源" : "Resources", items: [
        { key: "/monitor", icon: <MonitorOutlined />, label: nav("monitor") },
        { key: "/compute", icon: <CloudServerOutlined />, label: nav("compute") },
      ] },
    ],
    admin: [
      { label: zh ? "管理" : "Management", items: [
        { key: "/admin/users", icon: <TeamOutlined />, label: nav("users") },
        { key: "/admin/announcements", icon: <NotificationOutlined />, label: nav("announcements") },
        { key: "/admin/audit", icon: <FileTextOutlined />, label: nav("audit") },
        { key: "/admin/agent-audit", icon: <SafetyCertificateOutlined />, label: nav("agent_audit") },
      ] },
      { label: zh ? "平台" : "Platform", items: [
        { key: "/admin/settings", icon: <SettingOutlined />, label: nav("settings") },
        { key: "/llm-gateway", icon: <ApiOutlined />, label: nav("llm_gateway") },
        { key: "/admin/llm-usage", icon: <BarChartOutlined />, label: nav("llm_usage") },
      ] },
    ],
  };

  const [username, setUsername] = useState(() => localStorage.getItem("username") || "");
  const displayUsername = username || "-";
  const roleLabel = (() => {
    const profiles = (t as { profile?: Record<string, string> }).profile || {};
    // 优先取 i18n 的角色键（admin/engineer/quality/viewer/operator），缺省回退普通用户
    return profiles[userRole] || (userRole === "admin" ? t.profile.admin : userRole === "engineer" ? t.profile.engineer : t.profile.user);
  })();

  const userMenuItems = [
    { key: "profile", icon: <UserOutlined />, label: roleLabel, onClick: () => setProfileOpen(true) },
    ...(isAdmin ? [{ key: "admin", icon: <TeamOutlined />, label: t.nav.users, onClick: () => navigate("/admin/users") }] : []),
    { type: "divider" as const },
    { key: "logout", icon: <LogoutOutlined />, label: t.app.logout, onClick: () => { localStorage.clear(); navigate("/login"); } },
  ];

  // 审批中心待办角标（第二批 S1/D16）：30s 轮询 pending-count，失败静默
  const [approvalPending, setApprovalPending] = useState(0);
  useEffect(() => {
    let alive = true;
    const tick = () => {
      import("../api/approvals")
        .then((mod) => mod.fetchPendingApprovalCount())
        .then((count) => { if (alive) setApprovalPending(count); })
        .catch(() => undefined);
    };
    tick();
    const timer = window.setInterval(tick, 30000);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  const selectedKey = (() => {
    const p = location.pathname;
    if (p === "/") return "/";
    if (p.startsWith("/workspace") || p.startsWith("/template")) return "/projects";
    // 详情子路由显式归属其列表 tab：/agent/task/:id 属于「任务列表」而非
    // 落入下面的前缀兜底（兜底对同路由多 query 项会退化成 query 最长者
    // 胜，曾导致详情页光标停在「知识中心」）。
    if (p.startsWith("/agent/task/")) return "/agent?tab=tasks";
    // 知识库详情/知识中心页归属「知识中心」菜单项（入口在知识库管理卡）。
    if (p === "/knowledge" || p === "/knowledge-center" || p.startsWith("/knowledge/")) {
      return "/agent?tab=knowledge";
    }
    const entries = (sideGroups[activeView] || []).flatMap((group) => group.items);
    const here = p + location.search;
    // Prefer the entry whose full target (path + query) matches exactly, so
    // /agent?tab=tasks selects the job-list entry rather than the wizard one.
    const exact = entries
      .map((item) => ({ full: item.query ? `${item.key}?${item.query}` : item.key, item }))
      .filter(({ full }) => here === full || here.startsWith(`${full}&`))
      .sort((left, right) => right.full.length - left.full.length)[0];
    if (exact) return exact.full;
    // Path-only fallback: longest matching ROUTE wins (so /data-annotation
    // beats /data). Entries sharing one route key are collapsed to their
    // query-less base item first — subroutes never arbitrate by query length.
    const fallbackByKey = new Map<string, string>();
    for (const item of entries) {
      if (item.key === "/" || !(p === item.key || p.startsWith(`${item.key}/`))) continue;
      if (!fallbackByKey.has(item.key) || !item.query) {
        fallbackByKey.set(item.key, item.query ? `${item.key}?${item.query}` : item.key);
      }
    }
    return (
      [...fallbackByKey.values()]
        .sort((left, right) => right.length - left.length)[0] || VIEW_HOME[activeView]
    );
  })();

  const handleMenuNavigate = (item: SideEntry) => {
    navigate(item.query ? `${item.key}?${item.query}` : item.key);
  };

  useEffect(() => {
    if (username || !localStorage.getItem("token")) return;
    let active = true;
    apiClient.get("/auth/me").then((response) => {
      const value = String(response.data?.username || "").trim();
      if (active && value) {
        localStorage.setItem("username", value);
        setUsername(value);
      }
      if (active && response.data?.role) {
        localStorage.setItem("role", String(response.data.role));
        setUserRole(String(response.data.role));
      }
    }).catch(() => undefined);
    return () => { active = false; };
  }, [username]);

  return (
    <>
      <div className="v2-shell" data-theme={theme}>
        {/* 顶部全局导航 */}
        <header className="v2-topnav app-header">
          <div className="v2-brand" onClick={() => navigate("/")} role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter") navigate("/"); }}>
            {t.app.title}
          </div>
          <nav className="v2-navtabs" aria-label={zh ? "主导航" : "Primary"}>
            {viewTabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={`v2-navtab${activeView === tab.id ? " on" : ""}`}
                onClick={() => navigate(VIEW_HOME[tab.id])}
              >
                {tab.label}{tab.tag ? <span className="tag">{tagLabel(tab.tag, zh)}</span> : null}
              </button>
            ))}
          </nav>
          <div className="v2-topright">
            <span className="v2-env-chip" style={{ display: "none" }} />
            {demoProjects.length > 0
              && (localStorage.getItem("showDemoBadge") === "1"
                || new URLSearchParams(window.location.search).has("demoBadge")) && (
              <Tag data-testid="demo-presence" color="purple" title={demoProjects.join("、")}>
                {zh ? "含演示数据" : "Demo data"}
              </Tag>
            )}
            <button
              type="button"
              className="v2-seg-btn"
              aria-label={zh ? "帮助中心" : "Help center"}
              title={zh ? "帮助中心" : "Help center"}
              onClick={() => navigate(`/help?page=${encodeURIComponent(location.pathname)}`)}
              style={{ display: "inline-flex", alignItems: "center" }}
            >
              <QuestionCircleOutlined />
            </button>
            {/* 审批中心（第二批 S1/D16）：顶栏全局入口 + 待办角标 */}
            <button
              type="button"
              className="v2-seg-btn"
              aria-label={zh ? "审批中心" : "Approval center"}
              title={zh ? "审批中心" : "Approval center"}
              data-testid="topbar-approvals"
              onClick={() => navigate("/approvals")}
              style={{ display: "inline-flex", alignItems: "center" }}
            >
              <Badge count={approvalPending} size="small" offset={[-2, 2]}>
                <AuditOutlined />
              </Badge>
            </button>
            <NotificationCenter />
            <div className="v2-seg" role="group" aria-label={zh ? "语言与主题" : "Language & theme"}>
              <button type="button" className={`v2-seg-btn${lang === "zh" ? " on" : ""}`}
                onClick={() => setLang("zh")} title="中文">中</button>
              <button type="button" className={`v2-seg-btn${lang === "en" ? " on" : ""}`}
                onClick={() => setLang("en")} title="English">EN</button>
              <button type="button" className="v2-seg-btn"
                onClick={toggleTheme}
                aria-label={theme === "dark" ? (zh ? "切换到明亮模式" : "Switch to light mode") : (zh ? "切换到暗黑模式" : "Switch to dark mode")}
                title={theme === "dark" ? (zh ? "切换到明亮模式" : "Switch to light mode") : (zh ? "切换到暗黑模式" : "Switch to dark mode")}
              >
                {theme === "dark" ? <SunOutlined /> : <MoonOutlined />}
              </button>
            </div>
            <Dropdown menu={{ items: userMenuItems }}>
              <span className="user-identity" style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                <span style={{ fontSize: 12 }}>{displayUsername.slice(0, 12)}</span>
                <span style={{ fontSize: 11, color: "var(--v2-dim)" }}>· {roleLabel}</span>
                <Avatar icon={<UserOutlined />} size={28} className="v2-avatar" style={{ backgroundColor: "#1b2a47" }} />
              </span>
            </Dropdown>
          </div>
        </header>

        {/* 中心布局：视图专属侧栏 + 主区（门户无侧栏，全宽） */}
        <div className="v2-center">
          {activeView !== "portal" && (
          <aside className="v2-sidebar" data-testid="v2-sidebar">
            {(sideGroups[activeView] || []).map((group) => (
              <div key={group.label}>
                <div className="v2-side-group">{group.label}</div>
                {group.items.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    className={`v2-side-item${selectedKey === (item.query ? `${item.key}?${item.query}` : item.key) ? " on" : ""}`}
                    onClick={() => handleMenuNavigate(item)}
                  >
                    {item.icon}<span>{item.label}</span>
                  </button>
                ))}
              </div>
            ))}
          </aside>
          )}
          <main className="v2-main">
            <div className="fade-in">{children}</div>
          </main>
        </div>
        <IngestStatusFooter />
      </div>

      {/* Profile Modal */}
      <Modal title={zh ? "用户信息" : "User profile"} open={profileOpen} onCancel={() => setProfileOpen(false)} footer={null}>
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label={zh ? "用户名" : "Username"}>{displayUsername}</Descriptions.Item>
          <Descriptions.Item label={zh ? "角色" : "Role"}><Tag>{roleLabel}</Tag></Descriptions.Item>
          <Descriptions.Item label={zh ? "语言" : "Language"}>{zh ? "中文" : "English"}</Descriptions.Item>
        </Descriptions>
      </Modal>
    </>
  );
}


function tagLabel(tag: string, zh: boolean) {
  if (tag === "NEW") return zh ? "新" : "NEW";
  return tag;
}

/** 全站页脚的实时链路状态（B1-07，诚实设计⑤变体，D52）：
 * 状态由消费心跳驱动——未启用如实说「未启用」，不宣称链路生效。 */
function IngestStatusFooter() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [status, setStatus] = useState<{ state: string; detail: string } | null>(null);
  useEffect(() => {
    if (!localStorage.getItem("token")) return;
    let active = true;
    const load = () => {
      apiClient.get("/platform/ingest-status").then((response) => {
        if (active) setStatus(response.data ?? null);
      }).catch(() => undefined);
    };
    load();
    const timer = window.setInterval(load, 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  if (!status || status.state === "disabled") return null;
  const color = status.state === "ok" ? "#3f8600" : "#cf1322";
  const label = status.state === "ok" ? (zh ? "实时链路正常" : "Live ingest: OK") : (zh ? "实时链路告警" : "Live ingest: alarm");
  return (
    <div
      data-testid="ingest-status-footer"
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "4px 16px", fontSize: 12, color: "var(--ant-color-text-tertiary, #999)",
        borderTop: "1px solid var(--ant-color-border-secondary, #333)",
      }}
    >
      <Tag color={status.state === "ok" ? "green" : "red"} style={{ margin: 0 }}>{label}</Tag>
      <span>{status.detail}</span>
    </div>
  );
}
