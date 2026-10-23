import { useEffect, useState } from "react";
import { ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

/** 系统管理→审计日志（预览稿 v-admin 侧栏项）：平台审计事件流。 */
export default function AuditLogPage() {
  const { t, lang } = useI18n();
  const zh = lang === "zh";
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    apiClient.get("/platform-audit").then((res) => {
      const items = Array.isArray(res.data) ? res.data : res.data?.items || [];
      setEvents(items);
    }).catch(() => {
      // 审计端点可能不存在，降级为空
      setEvents([]);
    }).finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <AppLayout>
      <div className="v2-pagehead">
        <div>
          <h2 className="v2-pt">{zh ? "审计日志" : "Audit Log"}</h2>
          <p className="v2-pdesc">{zh ? "平台全部操作审计记录：谁在何时对什么做了什么。" : "Platform-wide audit trail."}</p>
        </div>
        <button type="button" className="v2-btn" onClick={load}>
          <ReloadOutlined spin={loading} /> {zh ? "刷新" : "Refresh"}
        </button>
      </div>
      <div className="v2-panel">
        {events.length === 0 ? (
          <div className="v2-empty">{zh ? "暂无审计记录" : "No audit events"}</div>
        ) : (
          <table className="v2-table">
            <thead><tr>
              <th>{zh ? "操作" : "Action"}</th>
              <th>{zh ? "资源" : "Resource"}</th>
              <th>{zh ? "操作者" : "Actor"}</th>
              <th>{zh ? "结果" : "Result"}</th>
              <th>{zh ? "时间" : "Time"}</th>
            </tr></thead>
            <tbody>
              {events.slice(0, 100).map((event) => (
                <tr key={String(event.id ?? event.request_id ?? Math.random())}>
                  <td className="tt">{String(event.action ?? "—")}</td>
                  <td>{String(event.resource_type ?? "—")}</td>
                  <td>{String(event.actor_username ?? "—")}</td>
                  <td>
                    <span className={`v2-badge ${event.result === "success" ? "v2-bgo" : "v2-br"}`}>
                      {String(event.result ?? "—")}
                    </span>
                  </td>
                  <td>{event.created_at ? new Date(String(event.created_at)).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </AppLayout>
  );
}
