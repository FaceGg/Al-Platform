import { useEffect, useState } from "react";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

/** 系统管理→系统设置（预览稿 v-admin 侧栏项）：平台级配置。 */
export default function SystemSettingsPage() {
  const { t, lang, setLang } = useI18n();
  const zh = lang === "zh";
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    apiClient.get("/readiness").then((res) => setHealth(res.data)).catch(() => setHealth(null));
    apiClient.get("/config/public").then((res) => setConfig(res.data)).catch(() => setConfig(null));
  }, []);

  const settings = [
    { label: zh ? "平台语言" : "Language", value: zh ? "中文" : "English", action: (
      <button type="button" className="v2-btn sm" onClick={() => setLang(zh ? "en" : "zh")}>
        {zh ? "切换 English" : "切换中文"}
      </button>
    )},
    { label: zh ? "应用模式" : "App mode", value: String(health?.mode ?? config?.app_mode ?? "—") },
    { label: zh ? "数据库" : "Database", value: String(health?.database ?? "—") },
    { label: zh ? "迁移版本" : "Migration", value: String(health?.migration ?? config?.migration_head ?? "—") },
    { label: zh ? "LLM 已配置" : "LLM configured", value: String(config?.llm_api_key_configured ?? "—") },
    { label: zh ? "对象存储" : "Object storage", value: String(health?.minio ?? config?.minio_endpoint ?? "—") },
  ];

  return (
    <AppLayout>
      <div className="v2-pagehead">
        <div>
          <h2 className="v2-pt">{zh ? "系统设置" : "System Settings"}</h2>
          <p className="v2-pdesc">{zh ? "平台级配置与健康状态。" : "Platform configuration and health."}</p>
        </div>
      </div>
      <div className="v2-panel">
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
                <td>{item.action ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="v2-note">{zh
        ? "系统设置当前为只读展示；可修改项（语言/主题）在顶栏快捷切换。环境变量配置通过 .env 或部署环境管理。"
        : "Settings are read-only; language/theme toggle from the topbar. Environment config via .env."}</div>
    </AppLayout>
  );
}
