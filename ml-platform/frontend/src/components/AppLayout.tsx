import { Layout, Menu, Avatar, Dropdown, Space, Button, Modal, Descriptions, Tag, Badge, Tooltip } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  DashboardOutlined, ProjectOutlined, LogoutOutlined, UserOutlined,
  DatabaseOutlined, AppstoreOutlined, TeamOutlined, ApartmentOutlined,
  CloudUploadOutlined, ThunderboltOutlined, ExperimentOutlined, ApiOutlined,
  CloudServerOutlined, RobotOutlined, MessageOutlined, MenuFoldOutlined,
  MenuUnfoldOutlined, MonitorOutlined, SafetyOutlined, ToolOutlined,
} from "@ant-design/icons";
import { useI18n } from "../i18n";
import { useTheme } from "../stores/themeContext";
import { SunOutlined, MoonOutlined } from "@ant-design/icons";
import NotificationCenter from "./NotificationCenter";
import apiClient from "../api/client";

const { Header, Sider, Content } = Layout;

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { lang, t, setLang } = useI18n();
  const { theme, toggleTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const role = localStorage.getItem("role");

  const menuItems = [
    { key: "/", icon: <DashboardOutlined />, label: t.nav.dashboard },
    { key: "/projects", icon: <ProjectOutlined />, label: t.nav.projects },
    { key: "/models", icon: <AppstoreOutlined />, label: t.nav.models },
    { key: "/data", icon: <CloudUploadOutlined />, label: t.nav.data },
    { type: "divider" as const },
    { key: "/automl", icon: <ThunderboltOutlined />, label: t.nav.automl },
    { key: "/training", icon: <ExperimentOutlined />, label: t.nav.training },
    { key: "/orchestration", icon: <RobotOutlined />, label: t.nav.orchestration },
    { type: "divider" as const },
    { key: "/knowledge", icon: <DatabaseOutlined />, label: t.nav.knowledge },
    { key: "/knowledge-graph", icon: <ApartmentOutlined />, label: t.knowledge?.graph || "Graph" },
    { key: "/chat", icon: <MessageOutlined />, label: t.nav.chat },
    { type: "divider" as const },
    { key: "/monitor", icon: <MonitorOutlined />, label: t.nav.monitor },
    { key: "/compute", icon: <CloudServerOutlined />, label: "Compute" },
    ...(role === "admin" ? [{ key: "/admin/users", icon: <TeamOutlined />, label: t.nav.users }] : []),
  ];

  const userMenuItems = [
    { key: "profile", icon: <UserOutlined />, label: role === "admin" ? t.profile.admin : role === "engineer" ? t.profile.engineer : t.profile.user, onClick: () => setProfileOpen(true) },
    ...(role === "admin" ? [{ key: "admin", icon: <TeamOutlined />, label: t.nav.users, onClick: () => navigate("/admin/users") }] : []),
    { type: "divider" as const },
    { key: "logout", icon: <LogoutOutlined />, label: t.app.logout, onClick: () => { localStorage.clear(); navigate("/login"); } },
  ];

  const selectedKey = (() => {
    const p = location.pathname;
    if (p === "/") return "/";
    if (p.startsWith("/workspace") || p.startsWith("/template")) return "/projects";
    for (const item of menuItems) {
      if (typeof item.key === "string" && p.startsWith(item.key) && item.key !== "/") return item.key;
    }
    return "/";
  })();

  const [username, setUsername] = useState(() => localStorage.getItem("username") || "");
  useEffect(() => {
    if (username || !localStorage.getItem("token")) return;
    let active = true;
    apiClient.get("/me").then((response) => {
      const value = String(response.data?.username || "").trim();
      if (active && value) {
        localStorage.setItem("username", value);
        setUsername(value);
      }
    }).catch(() => undefined);
    return () => { active = false; };
  }, [username]);
  const displayUsername = username || localStorage.getItem("userId") || "-";
  const roleLabel = role === "admin" ? t.profile.admin : role === "engineer" ? t.profile.engineer : t.profile.user;
  const roleColor = role === "admin" ? "red" : role === "engineer" ? "blue" : "green";

  return (
    <>
      <Layout style={{ minHeight: "100vh" }} data-theme={theme}>
        {/* Sidebar */}
        <Sider
          collapsible
          collapsed={collapsed}
          onCollapse={setCollapsed}
          trigger={null}
          width={220}
          style={{
            background: "linear-gradient(180deg, #0D1117 0%, #161B22 100%)",
            borderRight: "1px solid var(--border-default)",
            overflow: "auto",
          }}
        >
          {/* Logo */}
          <div
            style={{
              padding: collapsed ? "16px 0" : "16px 20px",
              borderBottom: "1px solid var(--border-subtle)",
              display: "flex",
              alignItems: "center",
              gap: 10,
              cursor: "pointer",
            }}
            onClick={() => navigate("/")}
          >
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: "linear-gradient(135deg, #F0883E, #F5A623)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <ToolOutlined style={{ color: "#fff", fontSize: 16 }} />
            </div>
            {!collapsed && (
              <div>
                <div style={{ color: "#E6EDF3", fontWeight: 700, fontSize: 14, lineHeight: 1.3 }}>Precision Forge</div>
                <div style={{ color: "#8B949E", fontSize: 10 }}>AI Training Platform</div>
              </div>
            )}
          </div>

          {/* Menu */}
          <Menu
            mode="inline"
            selectedKeys={[selectedKey]}
            items={menuItems.map((item: any) =>
              item.type === "divider"
                ? item
                : { ...item, onClick: () => navigate(item.key) }
            )}
            style={{ background: "transparent", border: "none", padding: "8px 0" }}
          />
        </Sider>

        <Layout>
          {/* Header */}
          <Header
            style={{
              background: "rgba(22, 27, 34, 0.95)",
              backdropFilter: "blur(12px)",
              borderBottom: "1px solid var(--border-default)",
              padding: "0 24px",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              height: 52,
              position: "sticky",
              top: 0,
              zIndex: 100,
            }}
          >
            <Space>
              <Button
                type="text"
                icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                onClick={() => setCollapsed(!collapsed)}
                style={{ color: "var(--text-secondary)", fontSize: 16 }}
              />
              <span style={{ color: "var(--text-primary)", fontWeight: 600, fontSize: 15 }}>
                {t.app.title}
              </span>
            </Space>

            <Space size={12}>
              <NotificationCenter />
              <Tooltip title="AI智能对话">
                <Button
                  type="text"
                  icon={<MessageOutlined />}
                  onClick={() => navigate("/chat")}
                  style={{ color: "var(--text-secondary)" }}
                />
              </Tooltip>
              <Button
                size="small"
                type={lang === "zh" ? "primary" : "default"}
                onClick={() => setLang("zh")}
                style={{
                  fontWeight: 600,
                  borderRadius: 4,
                  minWidth: 32,
                  height: 28,
                  padding: "0 8px",
                }}
              >
                中
              </Button>
              <Button
                size="small"
                type={lang === "en" ? "primary" : "default"}
                onClick={() => setLang("en")}
                style={{fontWeight: 600, borderRadius: 4, minWidth: 32, height: 28, padding: "0 8px"}}
              >
                EN
              </Button>
              <Button
                size="small"
                onClick={toggleTheme}
                icon={theme === "dark" ? <SunOutlined /> : <MoonOutlined />}
                style={{borderRadius: 4, minWidth: 32, height: 28, padding: "0 8px"}}
              />
              <Dropdown menu={{ items: userMenuItems }}>
                <Space style={{ cursor: "pointer" }}>
                  <Avatar
                    icon={<UserOutlined />}
                    style={{ backgroundColor: "var(--accent-primary)", flexShrink: 0 }}
                    size={30}
                  />
                  <div>
                    <div style={{ color: "var(--text-primary)", fontSize: 13, fontWeight: 500, lineHeight: 1.2 }}>
                      {displayUsername.slice(0, 12)}
                    </div>
                    <Tag
                      color={roleColor}
                      style={{ fontSize: 10, lineHeight: "16px", padding: "0 4px", margin: 0 }}
                    >
                      {roleLabel}
                    </Tag>
                  </div>
                </Space>
              </Dropdown>
            </Space>
          </Header>

          {/* Content */}
          <Content
            style={{
              padding: 24,
              minHeight: "calc(100vh - 52px)",
            }}
          >
            <div className="fade-in">{children}</div>
          </Content>
        </Layout>
      </Layout>

      {/* Profile Modal */}
      <Modal title="用户信息" open={profileOpen} onCancel={() => setProfileOpen(false)} footer={null}>
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="用户名">{displayUsername}</Descriptions.Item>
          <Descriptions.Item label="角色">
            <Tag color={roleColor}>{roleLabel}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="语言">{lang === "zh" ? "中文" : "English"}</Descriptions.Item>
        </Descriptions>
      </Modal>
    </>
  );
}
