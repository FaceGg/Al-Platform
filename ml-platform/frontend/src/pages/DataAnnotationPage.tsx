import { useEffect, useMemo, useRef, useState } from "react";
import { App as AntApp, Empty, Spin, Tag, Tooltip } from "antd";
import { DownloadOutlined, ExperimentOutlined, ReloadOutlined, UploadOutlined } from "@ant-design/icons";
import { useNavigate, useSearchParams } from "react-router-dom";

import AppLayout from "../components/AppLayout";
import { formatApiError, default as apiClient } from "../api/client";
import {
  createQualityDemoDataset,
  createQualityLabelSnapshot,
  createQualityRun,
  downloadQualityArtifact,
  getQualityModel,
  getQualityRun,
  getQualitySample,
  listQualityLabelSnapshots,
  listQualityRuns,
  listQualitySamples,
  reviewQualityLabel,
  submitQualityLabel,
  type QualityRun,
  type QualityLabelSnapshot,
  type QualityModel,
  type QualitySample,
  type QualitySampleDetail,
  trainQualityLabelSnapshot,
  uploadQualityDataset,
  validateQualityDataset,
} from "../api/spotWeldQuality";
import WaveformPanel from "../components/spotWeld/WaveformPanel";
import { useI18n } from "../i18n";

interface ProjectOption { id: string; name: string; project_role?: string; }

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
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const labels = (t.spotWeld || {}) as Record<string, string>;
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState(searchParams.get("projectId") || "");
  const [datasetArtifactId, setDatasetArtifactId] = useState(searchParams.get("datasetId") || "");
  const [runs, setRuns] = useState<QualityRun[]>([]);
  const [runId, setRunId] = useState(searchParams.get("runId") || "");
  const [samples, setSamples] = useState<QualitySample[]>([]);
  const [selected, setSelected] = useState<QualitySampleDetail | null>(null);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [loadingSamples, setLoadingSamples] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [snapshots, setSnapshots] = useState<QualityLabelSnapshot[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [snapshotName, setSnapshotName] = useState("approved-labels");
  const [qualityModel, setQualityModel] = useState<QualityModel | null>(null);
  const [qualityArtifacts, setQualityArtifacts] = useState<Record<string, string>>({});
  const [trainingSnapshot, setTrainingSnapshot] = useState(false);
  const [downloadingReport, setDownloadingReport] = useState(false);
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [preparingRun, setPreparingRun] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const activeContextRef = useRef({ projectId, runId });
  const detailRequestId = useRef(0);
  const runsRequestId = useRef(0);
  activeContextRef.current = { projectId, runId };

  const isCurrentContext = (expectedProjectId: string, expectedRunId: string) => (
    activeContextRef.current.projectId === expectedProjectId
    && activeContextRef.current.runId === expectedRunId
  );

  const selectedProject = useMemo(() => projects.find((item) => item.id === projectId), [projects, projectId]);
  const selectedRun = runs.find((item) => item.id === runId);
  const projectRole = selectedProject?.project_role || "";
  const canCreate = ["owner", "editor"].includes(projectRole);
  const canLabel = ["owner", "editor", "operator"].includes(projectRole);
  const canReview = ["owner", "editor"].includes(projectRole);

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
    if (!projectId) { runsRequestId.current += 1; setRuns([]); setRunId(""); return; }
    let active = true;
    const expectedProjectId = projectId;
    const requestId = ++runsRequestId.current;
    setLoadingRuns(true);
    listQualityRuns(projectId)
      .then((items) => {
        if (!active || runsRequestId.current !== requestId || activeContextRef.current.projectId !== expectedProjectId) return;
        setRuns(items);
        setRunId((current) => items.some((run) => run.id === current) ? current : items[0]?.id || "");
      })
      .catch((error) => {
        if (active && runsRequestId.current === requestId && activeContextRef.current.projectId === expectedProjectId) {
          message.error(formatApiError(error, "质量运行加载失败"));
        }
      })
      .finally(() => {
        if (active && runsRequestId.current === requestId && activeContextRef.current.projectId === expectedProjectId) {
          setLoadingRuns(false);
        }
      });
    return () => { active = false; };
  }, [projectId, message]);

  useEffect(() => {
    setSearchParams((current) => {
      if (projectId) current.set("projectId", projectId); else current.delete("projectId");
      if (datasetArtifactId) current.set("datasetId", datasetArtifactId); else current.delete("datasetId");
      if (runId) current.set("runId", runId); else current.delete("runId");
      return current;
    }, { replace: true });
  }, [projectId, datasetArtifactId, runId, setSearchParams]);

  useEffect(() => {
    detailRequestId.current += 1;
    if (!projectId || !runId) { setSamples([]); setSelected(null); setLoadingDetail(false); return; }
    let active = true;
    setLoadingSamples(true);
    setSelected(null);
    listQualitySamples(projectId, runId)
      .then((items) => { if (active) setSamples(items); })
      .catch((error) => { if (active) message.error(formatApiError(error, "样本队列加载失败")); })
      .finally(() => { if (active) setLoadingSamples(false); });
    return () => { active = false; };
  }, [projectId, runId, selectedRun?.status, message]);

  useEffect(() => {
    if (!projectId || !runId || selectedRun?.status !== "completed") {
      setSnapshots([]);
      setSnapshotId("");
      setQualityModel(null);
      setQualityArtifacts({});
      return;
    }
    let active = true;
    Promise.all([
      listQualityLabelSnapshots(projectId, runId),
      getQualityRun(projectId, runId),
      getQualityModel(projectId, runId).catch(() => null),
    ]).then(([nextSnapshots, run, model]) => {
      if (!active) return;
      setSnapshots(nextSnapshots);
      setSnapshotId((current) => nextSnapshots.some((item) => item.id === current) ? current : nextSnapshots[0]?.id || "");
      setQualityArtifacts(run.output_artifacts || {});
      setQualityModel(model);
    }).catch(() => {
      if (!active) return;
      setSnapshots([]);
      setQualityModel(null);
      setQualityArtifacts({});
    });
    return () => { active = false; };
  }, [projectId, runId, selectedRun?.status]);

  const selectSample = async (sample: QualitySample) => {
    if (!projectId || !runId) return;
    const expectedProjectId = projectId;
    const expectedRunId = runId;
    const requestId = ++detailRequestId.current;
    setLoadingDetail(true);
    try {
      const detail = await getQualitySample(projectId, runId, sample.id);
      if (detailRequestId.current !== requestId || !isCurrentContext(expectedProjectId, expectedRunId)) return;
      setSelected(detail);
      setLabel(detail.current_label || detail.automatic_label || "");
      setNote(detail.current_note || "");
    } catch (error) {
      if (detailRequestId.current === requestId && isCurrentContext(expectedProjectId, expectedRunId)) {
        message.error(formatApiError(error, "样本详情加载失败"));
      }
    } finally {
      if (detailRequestId.current === requestId && isCurrentContext(expectedProjectId, expectedRunId)) {
        setLoadingDetail(false);
      }
    }
  };

  useEffect(() => {
    const requestedSampleId = searchParams.get("sampleId");
    if (!requestedSampleId || selected?.id === requestedSampleId) return;
    const requestedSample = samples.find((sample) => sample.id === requestedSampleId);
    if (requestedSample) void selectSample(requestedSample);
  }, [samples, selected?.id, searchParams]);

  const refreshSamples = async (sampleId: string) => {
    if (!projectId || !runId) return;
    const expectedProjectId = projectId;
    const expectedRunId = runId;
    const items = await listQualitySamples(expectedProjectId, expectedRunId);
    if (!isCurrentContext(expectedProjectId, expectedRunId)) return;
    setSamples(items);
    const refreshed = items.find((item) => item.id === sampleId);
    if (refreshed) await selectSample(refreshed);
  };

  const startQualityRun = async (datasetArtifactId: string) => {
    if (!projectId) return;
    const validation = await validateQualityDataset(projectId, datasetArtifactId);
    if (!validation.valid_rows || validation.errors.length) {
      const firstError = validation.errors[0];
      message.error(firstError?.code || "报告字段或波形校验失败");
      return;
    }
    const run = await createQualityRun(projectId, {
      dataset_artifact_id: datasetArtifactId,
      field_mapping: {},
    });
    setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
    setRunId(run.id);
    setDatasetArtifactId(datasetArtifactId);
    setSamples([]);
    setSelected(null);
    message.success(`已创建 ${validation.valid_rows} 条记录的质量运行`);
  };

  const handleReportUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !projectId || !canCreate) return;
    const extension = file.name.split(".").pop()?.toLowerCase();
    if (!extension || !["csv", "xls", "xlsx"].includes(extension)) {
      message.error("仅支持 CSV、XLS 或 XLSX 报告");
      return;
    }
    setPreparingRun(true);
    try {
      const artifact = await uploadQualityDataset(projectId, file);
      await startQualityRun(artifact.artifact_id);
    } catch (error) {
      message.error(formatApiError(error, "报告上传或质量运行创建失败"));
    } finally {
      setPreparingRun(false);
    }
  };

  const handleCreateDemo = async () => {
    if (!projectId || !canCreate) return;
    setPreparingRun(true);
    try {
      const artifact = await createQualityDemoDataset(projectId);
      await startQualityRun(artifact.artifact_id);
    } catch (error) {
      message.error(formatApiError(error, "模拟数据创建或质量运行启动失败"));
    } finally {
      setPreparingRun(false);
    }
  };

  const handleSelectedDataset = async () => {
    if (!datasetArtifactId || !canCreate) return;
    setPreparingRun(true);
    try {
      await startQualityRun(datasetArtifactId);
    } catch (error) {
      message.error(formatApiError(error, "质量运行创建失败"));
    } finally {
      setPreparingRun(false);
    }
  };

  const refreshRuns = async () => {
    if (!projectId) return;
    const expectedProjectId = projectId;
    const requestId = ++runsRequestId.current;
    setLoadingRuns(true);
    try {
      const items = await listQualityRuns(expectedProjectId);
      if (runsRequestId.current !== requestId || activeContextRef.current.projectId !== expectedProjectId) return;
      setRuns(items);
    } catch (error) {
      if (runsRequestId.current === requestId && activeContextRef.current.projectId === expectedProjectId) {
        message.error(formatApiError(error, "质量运行加载失败"));
      }
    } finally {
      if (runsRequestId.current === requestId && activeContextRef.current.projectId === expectedProjectId) {
        setLoadingRuns(false);
      }
    }
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

  const createSnapshot = async () => {
    if (!projectId || !runId || !canReview) return;
    try {
      const snapshot = await createQualityLabelSnapshot(projectId, runId, snapshotName.trim() || "approved-labels");
      setSnapshots((current) => [snapshot, ...current.filter((item) => item.id !== snapshot.id)]);
      setSnapshotId(snapshot.id);
      message.success("已冻结审核标签快照");
    } catch (error) {
      message.error(formatApiError(error, "创建标签快照失败"));
    }
  };

  const trainSnapshot = async () => {
    if (!projectId || !runId || !snapshotId || !canReview) return;
    setTrainingSnapshot(true);
    try {
      const result = await trainQualityLabelSnapshot(projectId, runId, snapshotId);
      setQualityModel(result.model);
      setQualityArtifacts(result.output_artifacts);
      setRuns((current) => current.map((run) => run.id === runId ? {
        ...run,
        output_artifacts: result.output_artifacts,
      } : run));
      message.success("质量模型与报告已生成");
    } catch (error) {
      message.error(formatApiError(error, "标签快照训练失败"));
    } finally {
      setTrainingSnapshot(false);
    }
  };

  const downloadReport = async () => {
    if (!projectId || !runId || !qualityArtifacts.report) return;
    setDownloadingReport(true);
    try {
      const blob = await downloadQualityArtifact(projectId, runId, "report");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "spot-weld-quality-report.xlsx";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      message.error(formatApiError(error, "质量报告下载失败"));
    } finally {
      setDownloadingReport(false);
    }
  };

  useEffect(() => {
    if (!projectId || !runId || !["queued", "validating", "running"].includes(String(selectedRun?.status || ""))) return;
    const timer = window.setInterval(() => { void refreshRuns(); }, 1500);
    return () => window.clearInterval(timer);
  }, [projectId, runId, selectedRun?.status]);

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
          <div className="spot-weld-annotation__actions">
            <input
              ref={uploadInputRef}
              className="spot-weld-annotation__sr-only"
              type="file"
              accept=".csv,.xls,.xlsx"
              aria-label="上传点焊报告"
              onChange={handleReportUpload}
            />
            <Tooltip title="上传报告并启动质量运行">
              <button type="button" className="ant-btn" onClick={() => uploadInputRef.current?.click()} disabled={!canCreate || preparingRun}>
                <UploadOutlined />上传报告
              </button>
            </Tooltip>
            <Tooltip title="创建报告结构的模拟数据并启动质量运行">
              <button type="button" className="ant-btn" onClick={handleCreateDemo} disabled={!canCreate || preparingRun}>
                <ExperimentOutlined />模拟数据
              </button>
            </Tooltip>
            {datasetArtifactId && <Tooltip title="使用数据管理中选择的报告启动质量运行">
              <button type="button" className="ant-btn ant-btn-primary" onClick={handleSelectedDataset} disabled={!canCreate || preparingRun}>
                运行已选数据
              </button>
            </Tooltip>}
            <Tooltip title="刷新质量运行">
              <button type="button" className="ant-btn ant-btn-icon-only" aria-label="刷新质量运行" onClick={() => { void refreshRuns(); }} disabled={!projectId || loadingRuns}>
                <ReloadOutlined />
              </button>
            </Tooltip>
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
              <div className="spot-weld-annotation__evidence">
                <span>自动标签 <strong>{selected.automatic_label || "-"}</strong></span>
                <span>聚类 <strong>{selected.cluster_id == null ? "-" : selected.cluster_id}</strong></span>
                <span>特征 <strong>{Object.keys(selected.feature_values || {}).length || "-"}</strong></span>
              </div>
              <div className="spot-weld-annotation__rules" aria-label="规则命中">
                {(selected.rule_hits || []).length ? selected.rule_hits?.map((rule) => <Tag key={rule.code} color="blue">{rule.label}</Tag>) : <small>无规则命中</small>}
              </div>
              <details className="spot-weld-annotation__details">
                <summary>工艺参数</summary>
                <div>{Object.entries(selected.table_values || {}).map(([name, value]) => <span key={name}><small>{name}</small><strong>{typeof value === "number" ? value.toFixed(3) : String(value)}</strong></span>)}</div>
              </details>
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
            {runId && selectedRun?.status === "completed" && <section className="spot-weld-annotation__training" aria-label="审核标签训练">
              <div className="spot-weld-annotation__training-head">
                <h4>审核标签训练</h4>
                <Tag>{snapshots.length} 快照</Tag>
              </div>
              <label htmlFor="quality-snapshot-name">快照名称</label>
              <input id="quality-snapshot-name" aria-label="快照名称" value={snapshotName} onChange={(event) => setSnapshotName(event.target.value)} disabled={!canReview} />
              <button type="button" className="ant-btn" onClick={createSnapshot} disabled={!canReview}>创建训练快照</button>
              <label htmlFor="quality-training-snapshot">训练标签快照</label>
              <select id="quality-training-snapshot" aria-label="训练标签快照" value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)} disabled={!canReview || snapshots.length === 0}>
                <option value="">选择已冻结快照</option>
                {snapshots.map((snapshot) => <option value={snapshot.id} key={snapshot.id}>{snapshot.name} · {snapshot.sample_count} 条</option>)}
              </select>
              <button type="button" className="ant-btn ant-btn-primary" onClick={trainSnapshot} disabled={!canReview || !snapshotId || trainingSnapshot}>{trainingSnapshot ? "训练中..." : "训练快照"}</button>
              {qualityModel && <div className="spot-weld-annotation__training-result">
                <div><strong>{qualityModel.name}</strong><small>{qualityModel.backbone || qualityModel.framework || "质量模型"}</small></div>
                <div className="spot-weld-annotation__training-actions">
                  {qualityArtifacts.report && <button type="button" className="ant-btn" aria-label="下载质量报告" onClick={downloadReport} disabled={downloadingReport}><DownloadOutlined />下载质量报告</button>}
                  <button type="button" className="ant-btn" onClick={() => navigate(`/models?projectId=${encodeURIComponent(projectId)}`)}>查看模型库</button>
                </div>
              </div>}
            </section>}
          </section>
        </div>
      </div>
    </AppLayout>
  );
}
