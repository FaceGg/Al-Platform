import { Avatar, Dropdown, Modal, Descriptions, Tag } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  ProjectOutlined, LogoutOutlined, UserOutlined, TeamOutlined,
  DatabaseOutlined, AppstoreOutlined, CloudUploadOutlined, ThunderboltOutlined,
  ExperimentOutlined, ApiOutlined, CloudServerOutlined, RobotOutlined,
  MessageOutlined, MonitorOutlined, ClusterOutlined, DeploymentUnitOutlined,
  PlayCircleOutlined, BookOutlined, ControlOutlined, TagsOutlined, ApartmentOutlined,
  HomeOutlined, RocketOutlined, CopyOutlined, FileTextOutlined, SettingOutlined,
  NotificationOutlined,
} from "@ant-design/icons";
import { SunOutlined, MoonOutlined } from "@ant-design/icons";
import { useI18n } from "../i18n";
import { useTheme } from "../stores/themeContext";
import NotificationCenter from "./NotificationCenter";
import apiClient from "../api/client";
import "../styles/v2-shell.css";

type ViewId = "portal" | "algo" | "agent" | "infra" | "admin";

interface SideEntry { key: string; icon: React.ReactNode; label: string; query?: string; badge?: { count?: number; label?: string } }
interface SideGroup { label: string; items: SideEntry[] }

/** Route prefix -> owning view. Longest prefix wins when resolving. */
const VIEW_ROUTES: Record<ViewId, string[]> = {
  portal: ["/"],
  algo: ["/algo", "/projects", "/workspace", "/template", "/models", "/data", "/data-annotation", "/automl", "/training", "/orchestration", "/demo-loop", "/annotations", "/algorithms", "/api-marketplace"],
  agent: ["/agent", "/knowledge-center", "/prompt-templates", "/knowledge", "/knowledge-graph", "/chat"],
  infra: ["/infra", "/kubernetes", "/notebooks", "/images", "/cluster-governance", "/monitor", "/compute"],
  admin: ["/llm-gateway", "/admin/users", "/admin/announcements", "/admin/audit", "/admin/settings"],
};

/** Landing route for each top-level view tab. */
const VIEW_HOME: Record<ViewId, string> = {
  portal: "/",
  algo: "/algo",
  agent: "/agent",
  infra: "/infra",
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

  // P4 侧栏计数徽标：一次轻量聚合（失败静默——徽标是增益不是依赖）。
  const [sideCounts, setSideCounts] = useState<Record<string, number>>({});
  useEffect(() => {
    if (!localStorage.getItem("token")) return;
    let active = true;
    const fetchCount = (key: string, url: string, extract: (data: unknown) => number) => {
      apiClient.get(url).then((response) => {
        const count = extract(response.data);
        if (active && Number.isFinite(count)) {
          setSideCounts((cur) => (cur[key] === count ? cur : { ...cur, [key]: count }));
        }
      }).catch(() => undefined);
    };
    fetchCount("/data", "/datasets", (data) => {
      const items = (data as { items?: unknown[] })?.items;
      return Array.isArray(items) ? items.length : 0;
    });
    fetchCount("/agent", "/agent/runs?limit=1", (data) => {
      const items = data as unknown[];
      return Array.isArray(items) ? items.length : 0;
    });
    fetchCount("/automl", "/training/jobs?limit=100", (data) => {
      const items = (data as { items?: unknown[] })?.items;
      return Array.isArray(items) ? items.filter(
        (job) => ["running", "pending", "queued"].includes(String((job as { status?: string })?.status ?? ""))
      ).length : 0;
    });
    return () => { active = false; };
  }, []);

  const activeView = resolveView(location.pathname);
  const isAdmin = userRole === "admin";

  const zh = lang === "zh";

  const viewTabs: { id: ViewId; label: string; tag?: string }[] = [
    { id: "portal", label: zh ? "首页门户" : "Portal" },
    { id: "algo", label: zh ? "算法平台" : "Algorithms" },
    { id: "agent", label: zh ? "智能体中心" : "Agent Center" },
    { id: "infra", label: zh ? "基础设施" : "Infrastructure" },
    ...(isAdmin ? [{ id: "admin" as ViewId, label: zh ? "系统管理" : "Administration" }] : []),
  ];

  const sideGroups: Record<ViewId, SideGroup[]> = {
    portal: [],
    algo: [
      { label: zh ? "概览" : "Overview", items: [
        { key: "/algo", icon: <AppstoreOutlined />, label: zh ? "工作台" : "Dashboard" },
        { key: "/projects", icon: <ProjectOutlined />, label: zh ? "项目管理" : "Projects" },
      ] },
      { label: zh ? "数据" : "Data", items: [
        { key: "/data", icon: <CloudUploadOutlined />, label: t.nav.data },
        { key: "/data-annotation", icon: <TagsOutlined />, label: t.nav.data_annotation, query: "view=tasks" },
      ] },
      { label: zh ? "建模与服务" : "Modeling & Serving", items: [
        { key: "/automl", icon: <ThunderboltOutlined />, label: t.nav.automl, badge: { count: sideCounts["/automl"] } },
        { key: "/training", icon: <ExperimentOutlined />, label: t.nav.training },
        { key: "/models", icon: <AppstoreOutlined />, label: t.nav.models },
        { key: "/orchestration", icon: <RobotOutlined />, label: t.nav.orchestration },
        { key: "/demo-loop", icon: <DeploymentUnitOutlined />, label: t.nav.demo_loop },
      ] },
    ],
    agent: [
      { label: zh ? "建模智能体" : "Modeling agent", items: [
        { key: "/agent", icon: <RocketOutlined />, label: zh ? "新建任务" : "New task" },
        { key: "/agent", query: "tab=tasks", icon: <PlayCircleOutlined />, label: zh ? "任务列表" : "Jobs", badge: { count: sideCounts["/agent"] } },
        { key: "/agent", query: "tab=recipes", icon: <DeploymentUnitOutlined />, label: zh ? "配方库" : "Recipes" },
        { key: "/agent", query: "tab=knowledge", icon: <BookOutlined />, label: zh ? "知识中心" : "Knowledge" },
      ] },
      { label: zh ? "知识与对话" : "Knowledge & chat", items: [
        { key: "/prompt-templates", icon: <CopyOutlined />, label: t.nav.prompt_templates },
        { key: "/chat", icon: <MessageOutlined />, label: t.nav.chat },
        { key: "/knowledge-graph", icon: <ApartmentOutlined />, label: t.knowledge?.graph || "Graph" },
      ] },
    ],
    infra: [
      { label: zh ? "集群" : "Cluster", items: [
        { key: "/kubernetes", icon: <ClusterOutlined />, label: t.nav.kubernetes },
        { key: "/cluster-governance", icon: <ControlOutlined />, label: t.nav.cluster_governance },
      ] },
      { label: zh ? "运行" : "Runtime", items: [
        { key: "/kubernetes/jobs", icon: <PlayCircleOutlined />, label: t.nav.job_runs },
        { key: "/notebooks", icon: <BookOutlined />, label: t.nav.notebooks },
        { key: "/images", icon: <DatabaseOutlined />, label: t.nav.images },
      ] },
      { label: zh ? "资源" : "Resources", items: [
        { key: "/monitor", icon: <MonitorOutlined />, label: t.nav.monitor },
        { key: "/compute", icon: <CloudServerOutlined />, label: t.nav.compute },
      ] },
    ],
    admin: [
      { label: zh ? "管理" : "Management", items: [
        { key: "/admin/users", icon: <TeamOutlined />, label: t.nav.users, badge: { count: sideCounts["/admin/users"] } },
        { key: "/admin/announcements", icon: <NotificationOutlined />, label: zh ? "公告管理" : "Notices" },
        { key: "/admin/audit", icon: <FileTextOutlined />, label: zh ? "审计日志" : "Audit log" },
      ] },
      { label: zh ? "平台" : "Platform", items: [
        { key: "/admin/settings", icon: <SettingOutlined />, label: zh ? "系统设置" : "Settings" },
        { key: "/llm-gateway", icon: <ApiOutlined />, label: t.nav.llm_gateway },
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
    const here = p + location.search;
    // Prefer the entry whose full target (path + query) matches exactly, so
    // /agent?tab=tasks selects the job-list entry rather than the wizard one.
    const exact = entries
      .map((item) => ({ full: item.query ? `${item.key}?${item.query}` : item.key, item }))
      .filter(({ full }) => here === full || here.startsWith(`${full}&`))
      .sort((left, right) => right.full.length - left.full.length)[0];
    if (exact) return exact.full;
    // Path-only fallback: longest matching route wins, so /data-annotation
    // beats /data even though the latter is a string prefix.
    return entries
      .filter((item) => item.key !== "/" && (p === item.key || p.startsWith(`${item.key}/`)))
      .map((item) => (item.query ? `${item.key}?${item.query}` : item.key))
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
            {t.app.title}
          </div>
          <div className="v2-gsearch">
            <input placeholder={zh ? "搜索数据集 / 模型 / 配方 / 任务…" : "Search datasets / models / recipes / jobs…"} aria-label={zh ? "全局搜索" : "Global search"} />
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
                    {item.badge && (item.badge.count !== undefined && item.badge.count > 0) ? (
                      <span className="v2-side-count" data-testid={`side-count-${item.key}`}>{item.badge.count}</span>
                    ) : null}
                    {item.badge && item.badge.label ? (
                      <span className="v2-side-badge">{item.badge.label}</span>
                    ) : null}
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

const onLangStyle: React.CSSProperties = { color: "#fff", background: "rgba(47,155,245,.22)", borderColor: "rgba(92,178,255,.45)" };

function tagLabel(tag: string, zh: boolean) {
  if (tag === "NEW") return zh ? "新" : "NEW";
  return tag;
}
