import { useEffect, useMemo, useState } from "react";
import { App as AntApp, Empty, Spin, Tag } from "antd";
import { useSearchParams } from "react-router-dom";

import AppLayout from "../components/AppLayout";
import { formatApiError, default as apiClient } from "../api/client";
import {
  getQualitySample,
  listQualityRuns,
  listQualitySamples,
  reviewQualityLabel,
  submitQualityLabel,
  type QualityRun,
  type QualitySample,
  type QualitySampleDetail,
} from "../api/spotWeldQuality";
import WaveformPanel from "../components/spotWeld/WaveformPanel";
import { useI18n } from "../i18n";

interface ProjectOption { id: string; name: string; }

const LABEL_OPTIONS = [
  ["normal", "正常"],
  ["strong_splatter", "强飞溅缺陷"],
  ["weak_splatter", "弱飞溅缺陷"],
  ["power_fluctuation", "功率波动异常"],
  ["spot_too_small", "焊点过小/虚焊"],
  ["spot_too_large", "焊点过大/烧穿"],
  ["energy_anomaly", "能量异常"],
] as const;

const warningColor: Record<string, string> = {
  critical: "red", warning: "orange", notice: "gold", none: "green",
};

export default function DataAnnotationPage() {
  const { t } = useI18n();
  const { message } = AntApp.useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const labels = (t.spotWeld || {}) as Record<string, string>;
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState(searchParams.get("projectId") || "");
  const [runs, setRuns] = useState<QualityRun[]>([]);
  const [runId, setRunId] = useState(searchParams.get("runId") || "");
  const [samples, setSamples] = useState<QualitySample[]>([]);
  const [selected, setSelected] = useState<QualitySampleDetail | null>(null);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [loadingSamples, setLoadingSamples] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const canLabel = localStorage.getItem("role") !== "viewer";
  const canReview = ["admin", "editor"].includes(localStorage.getItem("role") || "");

  useEffect(() => {
    let active = true;
    apiClient.get("/projects")
      .then((response) => {
        if (!active) return;
        const items = (response.data.items || response.data || []) as ProjectOption[];
        setProjects(items);
        setProjectId((current) => current || items[0]?.id || "");
      })
      .catch(() => { if (active) setProjects([]); })
      .finally(() => { if (active) setLoadingProjects(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!projectId) { setRuns([]); setRunId(""); return; }
    let active = true;
    setLoadingRuns(true);
    listQualityRuns(projectId)
      .then((items) => {
        if (!active) return;
        setRuns(items);
        setRunId((current) => items.some((run) => run.id === current) ? current : items[0]?.id || "");
      })
      .catch((error) => { if (active) message.error(formatApiError(error, "质量运行加载失败")); })
      .finally(() => { if (active) setLoadingRuns(false); });
    return () => { active = false; };
  }, [projectId, message]);

  useEffect(() => {
    setSearchParams((current) => {
      if (projectId) current.set("projectId", projectId); else current.delete("projectId");
      if (runId) current.set("runId", runId); else current.delete("runId");
      return current;
    }, { replace: true });
  }, [projectId, runId, setSearchParams]);

  useEffect(() => {
    if (!projectId || !runId) { setSamples([]); setSelected(null); return; }
    let active = true;
    setLoadingSamples(true);
    setSelected(null);
    listQualitySamples(projectId, runId)
      .then((items) => { if (active) setSamples(items); })
      .catch((error) => { if (active) message.error(formatApiError(error, "样本队列加载失败")); })
      .finally(() => { if (active) setLoadingSamples(false); });
    return () => { active = false; };
  }, [projectId, runId, message]);

  const selectSample = async (sample: QualitySample) => {
    if (!projectId || !runId) return;
    setLoadingDetail(true);
    try {
      const detail = await getQualitySample(projectId, runId, sample.id);
      setSelected(detail);
      setLabel(detail.current_label || detail.automatic_label || "");
      setNote(detail.current_note || "");
    } catch (error) {
      message.error(formatApiError(error, "样本详情加载失败"));
    } finally { setLoadingDetail(false); }
  };

  const refreshSamples = async (sampleId: string) => {
    if (!projectId || !runId) return;
    const items = await listQualitySamples(projectId, runId);
    setSamples(items);
    const refreshed = items.find((item) => item.id === sampleId);
    if (refreshed) await selectSample(refreshed);
  };

  const submitLabel = async () => {
    if (!projectId || !runId || !selected || !label) return;
    try {
      await submitQualityLabel(projectId, runId, selected.id, { label, note });
      message.success("标签已提交，等待审核");
      await refreshSamples(selected.id);
    } catch (error) { message.error(formatApiError(error, "标签提交失败")); }
  };

  const review = async (decision: "approved" | "returned") => {
    if (!projectId || !runId || !selected) return;
    try {
      await reviewQualityLabel(projectId, runId, selected.id, { decision, comment: reviewComment });
      message.success(decision === "approved" ? "审核已通过" : "已退回复核");
      await refreshSamples(selected.id);
    } catch (error) { message.error(formatApiError(error, "审核失败")); }
  };

  const selectedProject = useMemo(() => projects.find((item) => item.id === projectId), [projects, projectId]);
  const selectedRun = runs.find((item) => item.id === runId);

  return (
    <AppLayout>
      <div className="page-shell fade-in spot-weld-annotation">
        <div className="page-header">
          <div className="page-header-copy">
            <p className="page-kicker">QUALITY / LABELING</p>
            <h2 className="page-title">{labels.title || "数据标注"}</h2>
            <p className="page-subtitle">{selectedProject?.name || "选择项目后开始审核点焊波形"}</p>
          </div>
          <div className="spot-weld-annotation__controls">
            <label htmlFor="spot-weld-annotation-project">Project</label>
            <select id="spot-weld-annotation-project" className="spot-weld-annotation__project" aria-label="Project" value={projectId} onChange={(event) => { setProjectId(event.target.value); setRunId(""); }} disabled={loadingProjects}>
              <option value="">选择项目</option>
              {projects.map((project) => <option value={project.id} key={project.id}>{project.name}</option>)}
            </select>
            <label htmlFor="spot-weld-quality-run">质量运行</label>
            <select id="spot-weld-quality-run" className="spot-weld-annotation__run" aria-label="质量运行" value={runId} onChange={(event) => setRunId(event.target.value)} disabled={!projectId || loadingRuns}>
              <option value="">选择运行</option>
              {runs.map((run) => <option value={run.id} key={run.id}>{run.id.slice(0, 8)} · {run.status}</option>)}
            </select>
          </div>
        </div>

        <div className="spot-weld-annotation__workspace">
          <section className="spot-weld-annotation__region spot-weld-annotation__queue" aria-labelledby="spot-weld-queue-title">
            <div className="spot-weld-annotation__region-head"><h3 id="spot-weld-queue-title">{labels.queue || "样本队列"}</h3><Tag>{samples.length} samples</Tag></div>
            {loadingRuns || loadingSamples ? <Spin /> : samples.length === 0 ? <Empty description={runId ? "暂无样本" : (labels.noRun || "暂无质量运行")} /> : (
              <div className="spot-weld-annotation__sample-list">
                {samples.map((sample) => <button type="button" className={`spot-weld-annotation__sample ${selected?.id === sample.id ? "is-selected" : ""}`} key={sample.id} onClick={() => selectSample(sample)} aria-label={sample.display_id}>
                  <span><strong>{sample.display_id}</strong><small>row {sample.source_row_index ?? "-"}</small></span>
                  <Tag color={warningColor[sample.warning_level || "none"]}>{sample.warning_level || "none"}</Tag>
                </button>)}
              </div>
            )}
          </section>

          <section className="spot-weld-annotation__region spot-weld-annotation__waveforms" aria-labelledby="spot-weld-waveform-title">
            <div className="spot-weld-annotation__region-head"><h3 id="spot-weld-waveform-title">{labels.waveforms || "四通道波形"}</h3>{selectedRun && <Tag color={selectedRun.status === "completed" ? "green" : "blue"}>{selectedRun.status}</Tag>}</div>
            {loadingDetail ? <Spin /> : selected ? <WaveformPanel waveforms={selected.waveforms} /> : <Empty description="选择样本查看波形" />}
          </section>

          <section className="spot-weld-annotation__region spot-weld-annotation__review" aria-labelledby="spot-weld-review-title">
            <h3 id="spot-weld-review-title">{labels.review || "标注与审核"}</h3>
            {selected ? <>
              <div className="spot-weld-annotation__sample-meta"><strong>{selected.display_id}</strong><Tag color={warningColor[selected.warning_level || "none"]}>{selected.warning_level || "none"}</Tag><span>{selected.defect_probability == null ? "-" : `${(selected.defect_probability * 100).toFixed(1)}% defect`}</span></div>
              <label htmlFor="quality-label">人工标签</label>
              <select id="quality-label" aria-label="人工标签" value={label} onChange={(event) => setLabel(event.target.value)} disabled={!canLabel}>
                <option value="">请选择</option>
                {LABEL_OPTIONS.map(([value, text]) => <option value={value} key={value}>{text}</option>)}
              </select>
              <label htmlFor="quality-note">备注</label>
              <textarea id="quality-note" value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录工艺判断" disabled={!canLabel} />
              <button type="button" className="ant-btn ant-btn-primary" onClick={submitLabel} disabled={!canLabel || !label}>提交复核</button>
              <div className="spot-weld-annotation__review-divider" />
              <label htmlFor="quality-review-comment">审核意见</label>
              <textarea id="quality-review-comment" value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} placeholder="审核说明" disabled={!canReview} />
              <div className="spot-weld-annotation__review-actions"><button type="button" className="ant-btn ant-btn-primary" onClick={() => review("approved")} disabled={!canReview}>通过审核</button><button type="button" className="ant-btn" onClick={() => review("returned")} disabled={!canReview}>退回</button></div>
              <small className="spot-weld-annotation__status">状态：{selected.review_status}</small>
            </> : <Empty description="选择样本进行标注" />}
          </section>
        </div>
      </div>
    </AppLayout>
  );
}
