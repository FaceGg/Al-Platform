import { Avatar, Dropdown, Modal, Descriptions, Tag } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  ProjectOutlined, LogoutOutlined, UserOutlined, TeamOutlined,
  DatabaseOutlined, AppstoreOutlined, CloudUploadOutlined, ThunderboltOutlined,
  ExperimentOutlined, ApiOutlined, CloudServerOutlined, RobotOutlined,
  MessageOutlined, MonitorOutlined, ClusterOutlined, DeploymentUnitOutlined,
  PlayCircleOutlined, BookOutlined, ControlOutlined, TagsOutlined, ApartmentOutlined,
  HomeOutlined,
} from "@ant-design/icons";
import { SunOutlined, MoonOutlined } from "@ant-design/icons";
import { useI18n } from "../i18n";
import { useTheme } from "../stores/themeContext";
import NotificationCenter from "./NotificationCenter";
import apiClient from "../api/client";
import "../styles/v2-shell.css";

type ViewId = "portal" | "algo" | "agent" | "infra" | "admin";

interface SideEntry { key: string; icon: React.ReactNode; label: string; query?: string }
interface SideGroup { label: string; items: SideEntry[] }

/** Route prefix -> owning view. Longest prefix wins when resolving. */
const VIEW_ROUTES: Record<ViewId, string[]> = {
  portal: ["/", "/dashboard", "/projects", "/workspace", "/template"],
  algo: ["/models", "/data", "/data-annotation", "/automl", "/training", "/algorithms", "/api-marketplace", "/orchestration", "/demo-loop", "/annotations"],
  agent: ["/agent", "/knowledge-center", "/knowledge", "/knowledge-graph", "/chat"],
  infra: ["/kubernetes", "/notebooks", "/images", "/cluster-governance", "/monitor", "/compute"],
  admin: ["/llm-gateway", "/admin/users"],
};

/** Landing route for each top-level view tab. */
const VIEW_HOME: Record<ViewId, string> = {
  portal: "/",
  algo: "/automl",
  agent: "/agent",
  infra: "/kubernetes",
  admin: "/llm-gateway",
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

  const viewTabs: { id: ViewId; label: string; tag?: string }[] = [
    { id: "portal", label: zh ? "首页门户" : "Portal" },
    { id: "algo", label: zh ? "算法平台" : "Algorithms" },
    { id: "agent", label: zh ? "智能体中心" : "Agent Center", tag: "NEW" },
    { id: "infra", label: zh ? "基础设施" : "Infrastructure" },
    ...(isAdmin ? [{ id: "admin" as ViewId, label: zh ? "系统管理" : "Administration" }] : []),
  ];

  const sideGroups: Record<ViewId, SideGroup[]> = {
    portal: [
      { label: t.nav.portalGroup, items: [
        { key: "/", icon: <HomeOutlined />, label: zh ? "首页门户" : "Portal Home" },
        { key: "/dashboard", icon: <AppstoreOutlined />, label: t.nav.dashboard },
        { key: "/projects", icon: <ProjectOutlined />, label: t.nav.projects },
      ] },
    ],
    algo: [
      { label: zh ? "数据" : "Data", items: [
        { key: "/data", icon: <CloudUploadOutlined />, label: t.nav.data },
        { key: "/data-annotation", icon: <TagsOutlined />, label: t.nav.data_annotation, query: "view=tasks" },
      ] },
      { label: zh ? "建模" : "Modeling", items: [
        { key: "/automl", icon: <ThunderboltOutlined />, label: t.nav.automl },
        { key: "/training", icon: <ExperimentOutlined />, label: t.nav.training },
        { key: "/models", icon: <AppstoreOutlined />, label: t.nav.models },
        { key: "/algorithms", icon: <DatabaseOutlined />, label: t.nav.algorithms },
      ] },
      { label: zh ? "交付" : "Delivery", items: [
        { key: "/orchestration", icon: <RobotOutlined />, label: t.nav.orchestration },
        { key: "/demo-loop", icon: <DeploymentUnitOutlined />, label: t.nav.demo_loop },
        { key: "/api-marketplace", icon: <ApiOutlined />, label: t.nav.api_market },
      ] },
    ],
    agent: [
      { label: t.nav.agentGroup, items: [
        { key: "/agent", icon: <RobotOutlined />, label: zh ? "智能体中心" : "Agent Center" },
        { key: "/chat", icon: <MessageOutlined />, label: t.nav.chat },
      ] },
      { label: zh ? "知识" : "Knowledge", items: [
        { key: "/knowledge-center", icon: <BookOutlined />, label: t.nav.knowledge_center },
        { key: "/knowledge", icon: <DatabaseOutlined />, label: t.nav.knowledge },
        { key: "/knowledge-graph", icon: <ApartmentOutlined />, label: t.knowledge?.graph || "Graph" },
      ] },
    ],
    infra: [
      { label: t.nav.infraGroup, items: [
        { key: "/kubernetes", icon: <ClusterOutlined />, label: t.nav.kubernetes },
        { key: "/kubernetes/jobs", icon: <PlayCircleOutlined />, label: t.nav.job_runs },
        { key: "/notebooks", icon: <BookOutlined />, label: t.nav.notebooks },
        { key: "/images", icon: <DatabaseOutlined />, label: t.nav.images },
        { key: "/cluster-governance", icon: <ControlOutlined />, label: t.nav.cluster_governance },
        { key: "/monitor", icon: <MonitorOutlined />, label: t.nav.monitor },
        { key: "/compute", icon: <CloudServerOutlined />, label: t.nav.compute },
      ] },
    ],
    admin: [
      { label: t.nav.adminGroup, items: [
        { key: "/llm-gateway", icon: <ApiOutlined />, label: t.nav.llm_gateway },
        { key: "/admin/users", icon: <TeamOutlined />, label: t.nav.users },
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
    const entries = (sideGroups[activeView] || []).flatMap((group) => group.items);
    return entries
      .map((item) => item.key)
      .filter((key) => key !== "/" && (p === key || p.startsWith(`${key}/`)))
      .sort((left, right) => right.length - left.length)[0] || VIEW_HOME[activeView];
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
            <span className="bolt">⚡</span>{t.app.title}
          </div>
          <div className="v2-gsearch">
            🔍 <input placeholder={zh ? "搜索数据集 / 模型 / 配方 / 任务…" : "Search datasets / models / recipes / jobs…"} aria-label={zh ? "全局搜索" : "Global search"} />
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
            <span className="v2-env-chip">● {zh ? "生产环境 v2.0" : "Production v2.0"}</span>
            <NotificationCenter />
            <button
              type="button"
              className="v2-lang"
              onClick={() => setLang("zh")}
              style={{ ...(lang === "zh" ? onLangStyle : {}) }}
            >中</button>
            <button
              type="button"
              className="v2-lang"
              onClick={() => setLang("en")}
              style={{ ...(lang === "en" ? onLangStyle : {}) }}
            >EN</button>
            <button
              type="button"
              className="v2-iconbtn"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? (zh ? "切换到明亮模式" : "Switch to light mode") : (zh ? "切换到暗黑模式" : "Switch to dark mode")}
              title={theme === "dark" ? (zh ? "切换到明亮模式" : "Switch to light mode") : (zh ? "切换到暗黑模式" : "Switch to dark mode")}
            >
              {theme === "dark" ? <SunOutlined /> : <MoonOutlined />}
            </button>
            <Dropdown menu={{ items: userMenuItems }}>
              <span className="user-identity" style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                <span style={{ fontSize: 12 }}>{displayUsername.slice(0, 12)}</span>
                <span style={{ fontSize: 11, color: "var(--v2-dim)" }}>· {roleLabel}</span>
                <Avatar icon={<UserOutlined />} size={28} className="v2-avatar" style={{ backgroundColor: "#1b2a47" }} />
              </span>
            </Dropdown>
          </div>
        </header>

        {/* 中心布局：视图专属侧栏 + 主区 */}
        <div className="v2-center">
          <aside className="v2-sidebar" data-testid="v2-sidebar">
            {(sideGroups[activeView] || []).map((group) => (
              <div key={group.label}>
                <div className="v2-side-group">{group.label}</div>
                {group.items.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    className={`v2-side-item${selectedKey === item.key ? " on" : ""}`}
                    onClick={() => handleMenuNavigate(item)}
                  >
                    {item.icon}<span>{item.label}</span>
                  </button>
                ))}
              </div>
            ))}
          </aside>
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

const onLangStyle: React.CSSProperties = { color: "#fff", background: "rgba(47,155,245,.22)", borderColor: "rgba(92,178,255,.45)" };

function tagLabel(tag: string, zh: boolean) {
  if (tag === "NEW") return zh ? "新" : "NEW";
  return tag;
}
