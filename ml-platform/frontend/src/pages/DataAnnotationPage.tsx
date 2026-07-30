import { useEffect, useState } from "react";
import { Empty, Select, Spin } from "antd";

import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

interface ProjectOption {
  id: string;
  name: string;
}

export default function DataAnnotationPage() {
  const { t } = useI18n();
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState<string>();
  const [loadingProjects, setLoadingProjects] = useState(true);

  useEffect(() => {
    let active = true;

    apiClient.get("/projects")
      .then((response) => {
        if (!active) return;
        const items = (response.data.items || response.data || []) as ProjectOption[];
        setProjects(items);
        setProjectId((current) => current || items[0]?.id);
      })
      .catch(() => {
        if (active) setProjects([]);
      })
      .finally(() => {
        if (active) setLoadingProjects(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const labels = t.spotWeld || {};

  return (
    <AppLayout>
      <div className="page-shell fade-in spot-weld-annotation">
        <div className="page-header">
          <div className="page-header-copy">
            <h2 className="page-title">{labels.title || "数据标注"}</h2>
          </div>
          <div className="spot-weld-annotation__project-control">
            <label className="spot-weld-annotation__sr-only" htmlFor="spot-weld-annotation-project">Project</label>
            <Select
              id="spot-weld-annotation-project"
              className="spot-weld-annotation__project"
              placeholder={labels.project || "项目"}
              value={projectId}
              loading={loadingProjects}
              onChange={setProjectId}
              options={projects.map((project) => ({ value: project.id, label: project.name }))}
              allowClear
            />
          </div>
        </div>

        <div className="spot-weld-annotation__workspace">
          <section className="spot-weld-annotation__region" aria-labelledby="spot-weld-queue-title">
            <h3 id="spot-weld-queue-title">{labels.queue || "样本队列"}</h3>
            {loadingProjects ? <Spin /> : <Empty description={labels.noRun || "暂无质量运行"} />}
          </section>

          <section className="spot-weld-annotation__region" aria-labelledby="spot-weld-waveform-title">
            <h3 id="spot-weld-waveform-title">{labels.waveforms || "四通道波形"}</h3>
            <Empty description={labels.noRun || "暂无质量运行"} />
          </section>

          <section className="spot-weld-annotation__region" aria-labelledby="spot-weld-review-title">
            <h3 id="spot-weld-review-title">{labels.review || "标注与审核"}</h3>
            <Empty description={labels.noRun || "暂无质量运行"} />
          </section>
        </div>
      </div>
    </AppLayout>
  );
}
