import { Avatar, Dropdown, Modal, Descriptions, Tag } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  ProjectOutlined, LogoutOutlined, UserOutlined, TeamOutlined,
  DatabaseOutlined, AppstoreOutlined, CloudUploadOutlined, ThunderboltOutlined,
  ExperimentOutlined, ApiOutlined, CloudServerOutlined, RobotOutlined,
  MessageOutlined, MonitorOutlined, ClusterOutlined, DeploymentUnitOutlined,
  PlayCircleOutlined, BookOutlined, ControlOutlined, TagsOutlined, ApartmentOutlined,
  RocketOutlined, CopyOutlined, FileTextOutlined, SettingOutlined,
  NotificationOutlined, BarChartOutlined,
} from "@ant-design/icons";
import { SunOutlined, MoonOutlined } from "@ant-design/icons";
import { useI18n } from "../i18n";
import { useTheme } from "../stores/themeContext";
import NotificationCenter from "./NotificationCenter";
import { navTitle, sectionName } from "./PageHeading";
import apiClient from "../api/client";
import "../styles/v2-shell.css";

type ViewId = "portal" | "algo" | "agent" | "infra" | "admin";

interface SideEntry { key: string; icon: React.ReactNode; label: string; query?: string }
interface SideGroup { label: string; items: SideEntry[] }

/** Route prefix -> owning view. Longest prefix wins when resolving. */
const VIEW_ROUTES: Record<ViewId, string[]> = {
  portal: ["/"],
  algo: ["/algo", "/projects", "/workspace", "/template", "/models", "/data", "/data-annotation", "/automl", "/training", "/orchestration", "/demo-loop", "/annotations", "/algorithms", "/api-marketplace"],
  agent: ["/agent", "/knowledge-center", "/prompt-templates", "/knowledge", "/knowledge-graph", "/chat"],
  infra: ["/infra", "/kubernetes", "/notebooks", "/images", "/cluster-governance", "/monitor", "/compute"],
  admin: ["/llm-gateway", "/admin/llm-usage", "/admin/users", "/admin/announcements", "/admin/audit", "/admin/settings"],
};

/** Landing route for each top-level view tab (admin: first sidebar entry). */
const VIEW_HOME: Record<ViewId, string> = {
  portal: "/",
  algo: "/algo",
  agent: "/agent",
  infra: "/infra",
  admin: "/admin/users",
};

function resolveView(pathname: string): ViewId {
  const order: ViewId[] = ["algo", "agent", "infra", "admin", "portal"];
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

  const viewTabs: { id: ViewId; label: string; tag?: string }[] = [
    { id: "portal", label: sectionName("portal", zh) },
    { id: "algo", label: sectionName("algo", zh) },
    { id: "agent", label: sectionName("agent", zh) },
    { id: "infra", label: sectionName("infra", zh) },
    ...(isAdmin ? [{ id: "admin" as ViewId, label: sectionName("admin", zh) }] : []),
  ];

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
      ] },
      { label: zh ? "平台" : "Platform", items: [
        { key: "/admin/settings", icon: <SettingOutlined />, label: nav("settings") },
        { key: "/llm-gateway", icon: <ApiOutlined />, label: nav("llm_gateway") },
        { key: "/admin/llm-usage", icon: <BarChartOutlined />, label: nav("llm_usage") },
      ] },
    ],
  };

  const userMenuItems = [
    { key: "profile", icon: <UserOutlined />, label: userRole === "admin" ? t.profile.admin : userRole === "engineer" ? t.profile.engineer : t.profile.user, onClick: () => setProfileOpen(true) },
    ...(isAdmin ? [{ key: "admin", icon: <TeamOutlined />, label: t.nav.users, onClick: () => navigate("/admin/users") }] : []),
    { type: "divider" as const },
    { key: "logout", icon: <LogoutOutlined />, label: t.app.logout, onClick: () => { localStorage.clear(); navigate("/login"); } },
  ];

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

  const [username, setUsername] = useState(() => localStorage.getItem("username") || "");

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
  const displayUsername = username || "-";
  const roleLabel = userRole === "admin" ? t.profile.admin : userRole === "engineer" ? t.profile.engineer : t.profile.user;

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
