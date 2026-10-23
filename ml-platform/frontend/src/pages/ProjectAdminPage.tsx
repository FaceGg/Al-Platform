import { useEffect, useState } from "react";
import { ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient from "../api/client";
import { useI18n } from "../i18n";

/** 系统管理→项目管理（预览稿 v-admin 侧栏项）：管理全平台项目。 */
export default function ProjectAdminPage() {
  const { t, lang } = useI18n();
  const zh = lang === "zh";
  const [projects, setProjects] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    apiClient.get("/projects").then((res) => {
      const items = Array.isArray(res.data) ? res.data : res.data?.items || [];
      setProjects(items);
    }).catch(() => setProjects([])).finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <AppLayout>
      <div className="v2-pagehead">
        <div>
          <h2 className="v2-pt">{zh ? "项目管理" : "Project Management"}</h2>
          <p className="v2-pdesc">{zh ? "全平台项目管理：查看、搜索、管理所有项目。" : "Manage all platform projects."}</p>
        </div>
        <button type="button" className="v2-btn" onClick={load}>
          <ReloadOutlined spin={loading} /> {zh ? "刷新" : "Refresh"}
        </button>
      </div>
      <div className="v2-panel">
        {projects.length === 0 ? (
          <div className="v2-empty">{zh ? "暂无项目" : "No projects"}</div>
        ) : (
          <table className="v2-table">
            <thead><tr>
              <th>{zh ? "项目名称" : "Name"}</th>
              <th>{zh ? "描述" : "Description"}</th>
              <th>{zh ? "创建时间" : "Created"}</th>
            </tr></thead>
            <tbody>
              {projects.map((project) => (
                <tr key={String(project.id)}>
                  <td className="tt">{String(project.name ?? "—")}</td>
                  <td>{String(project.description ?? "—").slice(0, 60)}</td>
                  <td>{project.created_at ? new Date(String(project.created_at)).toLocaleDateString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </AppLayout>
  );
}
