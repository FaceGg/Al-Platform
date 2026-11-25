import { useCallback, useEffect, useState } from "react";
import { ReloadOutlined } from "@ant-design/icons";
import { App as AntApp, Button, Checkbox, Space, Tag } from "antd";
import AppLayout from "../components/AppLayout";
import PageHeading from "../components/PageHeading";
import apiClient, { formatApiError } from "../api/client";
import { useI18n } from "../i18n";

interface ComponentCheck { ready: boolean; code: string }
interface Readiness {
  ready?: boolean;
  database?: ComponentCheck;
  redis?: ComponentCheck;
  celery?: ComponentCheck;
  storage?: ComponentCheck;
  mlflow?: ComponentCheck;
  tensorboard?: ComponentCheck;
  inference_runtime?: ComponentCheck;
  notification_crypto_configured?: boolean;
  notification_worker_registered?: boolean;
  migration_head?: string | null;
}

/** 系统管理→平台状态：平台组件健康矩阵与只读运行配置。 */
export default function SystemSettingsPage() {
  const { lang, setLang } = useI18n();
  const zh = lang === "zh";
  const [health, setHealth] = useState<Readiness | null>(null);
  const [llm, setLlm] = useState<{ count: number; model: string } | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    apiClient.get("/ready").then((res) => setHealth(res.data)).catch(() => setHealth(null));
    apiClient.get("/llm-profiles").then((res) => {
      const items = Array.isArray(res.data) ? res.data : [];
      const fallback = items.find((p: { is_default?: boolean }) => p.is_default) ?? items[0];
      setLlm({ count: items.length, model: String(fallback?.model_id ?? "—") });
    }).catch(() => setLlm(null));
    setTimeout(() => setLoading(false), 400);
  };

  useEffect(load, []);

  const components: { key: keyof Readiness; label: string }[] = [
    { key: "database", label: zh ? "数据库" : "Database" },
    { key: "redis", label: "Redis" },
    { key: "celery", label: zh ? "任务队列 Celery" : "Celery workers" },
    { key: "storage", label: zh ? "对象存储 MinIO" : "Object storage" },
    { key: "mlflow", label: "MLflow" },
    { key: "tensorboard", label: "TensorBoard" },
    { key: "inference_runtime", label: zh ? "推理运行时" : "Inference runtime" },
  ];

  const settings = [
    { label: zh ? "平台语言" : "Language", value: zh ? "中文" : "English", control: (
      <button type="button" className="v2-btn sm" onClick={() => setLang(zh ? "en" : "zh")}>
        {zh ? "切换 English" : "切换中文"}
      </button>
    )},
    { label: zh ? "整体状态" : "Overall", value: health == null ? (zh ? "不可用" : "unknown") : health.ready ? (zh ? "就绪" : "ready") : zh ? "存在异常" : "degraded" },
    { label: zh ? "迁移版本" : "Migration head", value: String(health?.migration_head ?? "—") },
    { label: zh ? "大模型档案" : "LLM profiles", value: llm == null ? (zh ? "未配置" : "not configured") : `${llm.count} · ${llm.model}` },
    { label: zh ? "通知加密" : "Notification crypto", value: String(health?.notification_crypto_configured ?? "—") },
    { label: zh ? "通知 Worker" : "Notification worker", value: String(health?.notification_worker_registered ?? "—") },
  ];

  return (
    <AppLayout>
      <PageHeading
        section="admin"
        navKey="settings"
        actions={(
          <button type="button" className="v2-btn" onClick={load}>
            <ReloadOutlined spin={loading} /> {zh ? "刷新" : "Refresh"}
          </button>
        )}
      />
      <SectionVisibilityCard zh={zh} />
      <div className="v2-panel">
        <h4><span className="bar" />{zh ? "组件健康" : "Component health"}</h4>
        <table className="v2-table">
          <thead><tr>
            <th>{zh ? "组件" : "Component"}</th>
            <th>{zh ? "状态" : "Status"}</th>
            <th>{zh ? "详情" : "Detail"}</th>
          </tr></thead>
          <tbody>
            {components.map((item) => {
              const check = health?.[item.key] as ComponentCheck | undefined;
              return (
                <tr key={item.key}>
                  <td className="tt">{item.label}</td>
                  <td>
                    <span className={`v2-badge ${check == null ? "v2-bgray" : check.ready ? "v2-bg" : "v2-br"}`}>
                      {check == null ? "—" : check.ready ? (zh ? "正常" : "ready") : zh ? "异常" : "error"}
                    </span>
                  </td>
                  <td>{check?.code ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="v2-panel" style={{ marginTop: 15 }}>
        <h4><span className="bar" />{zh ? "平台配置" : "Platform configuration"}</h4>
        <table className="v2-table">
          <thead><tr>
            <th>{zh ? "配置项" : "Setting"}</th>
            <th>{zh ? "当前值" : "Value"}</th>
            <th>{zh ? "操作" : "Actions"}</th>
          </tr></thead>
          <tbody>
            {settings.map((item) => (
              <tr key={item.label}>
                <td className="tt">{item.label}</td>
                <td>{item.value}</td>
                <td>{item.control ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="v2-note">{zh
        ? "环境变量类配置通过 .env 或部署环境管理，页面只读展示运行状态；语言/主题在顶栏快捷切换。"
        : "Environment configuration is managed via .env; this page is a read-only runtime view. Language/theme toggle from the topbar."}</div>
    </AppLayout>
  );
}

/** 板块可见性配置卡（技术方案 §7.1，admin only）：
 * 按角色勾选可见板块；portal 恒可见；admin 永远全可见（不可配置）。 */
const VISIBILITY_ROLES: { key: string; zh: string; en: string }[] = [
  { key: "engineer", zh: "工程师", en: "Engineer" },
  { key: "operator", zh: "操作员", en: "Operator" },
  { key: "quality", zh: "质量工程师", en: "Quality Engineer" },
  { key: "viewer", zh: "只读用户", en: "Viewer" },
];
const VISIBILITY_VIEWS: { key: string; zh: string; en: string }[] = [
  { key: "algo", zh: "算法平台", en: "Algorithms" },
  { key: "agent", zh: "智能体中心", en: "Agent Center" },
  { key: "quality", zh: "质量管理", en: "Quality Management" },
  { key: "infra", zh: "基础设施", en: "Infrastructure" },
];

function SectionVisibilityCard({ zh }: { zh: boolean }) {
  const { message } = AntApp.useApp();
  const [config, setConfig] = useState<Record<string, string[]>>({});
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadConfig = useCallback(() => {
    apiClient.get("/admin/section-visibility").then((res) => {
      setConfig(res.data?.config || {});
      setLoaded(true);
    }).catch(() => setLoaded(true));
  }, []);

  useEffect(() => { loadConfig(); }, [loadConfig]);

  const toggle = (role: string, view: string, checked: boolean) => {
    setConfig((current) => {
      const allowed = new Set(current[role] || []);
      if (checked) allowed.add(view); else allowed.delete(view);
      return { ...current, [role]: [...allowed] };
    });
  };

  const save = async () => {
    setSaving(true);
    try {
      const res = await apiClient.put("/admin/section-visibility", { config });
      setConfig(res.data?.config || {});
      message.success(zh ? "板块可见性已保存，重新登录后生效" : "Section visibility saved");
    } catch (e) {
      message.error(formatApiError(e, zh ? "保存失败" : "Save failed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="v2-panel" style={{ marginTop: 15 }}>
      <h4><span className="bar" />{zh ? "板块可见性" : "Section visibility"}</h4>
      {!loaded ? (
        <p style={{ color: "var(--v2-dim)" }}>{zh ? "加载中…" : "Loading…"}</p>
      ) : (
        <>
          <table className="v2-table">
            <thead><tr>
              <th>{zh ? "角色" : "Role"}</th>
              <th>{zh ? "可见板块" : "Visible sections"}</th>
            </tr></thead>
            <tbody>
              {VISIBILITY_ROLES.map((role) => {
                const allowed = new Set(config[role.key] || []);
                const narrowed = config[role.key] !== undefined;
                return (
                  <tr key={role.key}>
                    <td className="tt">{zh ? role.zh : role.en}{narrowed ? "" : <Tag style={{ marginLeft: 8 }}>{zh ? "未配置（全可见）" : "default (all)"}</Tag>}</td>
                    <td>
                      <Space wrap>
                        {VISIBILITY_VIEWS.map((view) => (
                          <Checkbox
                            key={view.key}
                            aria-label={`${role.key}:${view.key}`}
                            checked={allowed.has(view.key)}
                            onChange={(event) => toggle(role.key, view.key, event.target.checked)}
                          >
                            {zh ? view.zh : view.en}
                          </Checkbox>
                        ))}
                      </Space>
                    </td>
                  </tr>
                );
              })}
              <tr>
                <td className="tt">{zh ? "管理员" : "Admin"}</td>
                <td><Tag>{zh ? "永远全可见" : "Always all"}</Tag></td>
              </tr>
            </tbody>
          </table>
          <Space style={{ marginTop: 12 }}>
            <Button type="primary" loading={saving} onClick={save}>{zh ? "保存" : "Save"}</Button>
            <span style={{ color: "var(--v2-dim)", fontSize: 12 }}>
              {zh ? "首页门户恒可见；未勾选的角色保持默认全可见；配置后按角色收敛。" : "Portal is always visible; unconfigured roles keep full visibility."}
            </span>
          </Space>
        </>
      )}
    </div>
  );
}
