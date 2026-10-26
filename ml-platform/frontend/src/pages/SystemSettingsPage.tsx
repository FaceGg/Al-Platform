import { useEffect, useState } from "react";
import { ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
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
      <div className="v2-pagehead">
        <div>
          <h2 className="v2-pt">{zh ? "平台状态" : "Platform Status"}</h2>
          <p className="v2-pdesc">{zh ? "平台组件健康状态与运行配置。" : "Component health and runtime configuration."}</p>
        </div>
        <button type="button" className="v2-btn" onClick={load}>
          <ReloadOutlined spin={loading} /> {zh ? "刷新" : "Refresh"}
        </button>
      </div>
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
