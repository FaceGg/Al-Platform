import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
  type CheckboxProps,
} from "antd";
import {
  BarChartOutlined,
  EyeOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import ReactECharts from "echarts-for-react";
import dayjs from "dayjs";
import apiClient, { formatApiError } from "../api/client";
import {
  compareExperimentRuns,
  createExperiment,
  deleteExperiment,
  listExperimentRuns,
  listExperiments,
  type Experiment,
  type ExperimentRun,
  type RunComparison,
} from "../api/experiments";
import {
  createTensorBoardSession,
  createTrainingJob,
  deleteTrainingJob,
  getTrainingJob,
  listTrainingCheckpoints,
  listTrainingJobs,
  resumeTrainingJob,
  stopTrainingJob,
  type TrainingCheckpoint,
  type TrainingJob,
} from "../api/training";
import AppLayout from "../components/AppLayout";
import DeleteConfirmation from "../components/DeleteConfirmation";
import TableRowAction from "../components/TableRowAction";
import { useI18n } from "../i18n";
import { notifyDashboardStatsChanged } from "../events/dashboardStats";
import { taskStatusColor, taskStatusLabel } from "../utils/taskStatus";

const { Title, Text } = Typography;

const statusColors: Record<string, string> = {
  pending: "default",
  running: "#fa8c16",
  cancel_requested: "#1677ff",
  completed: "#389e0d",
  failed: "#cf1322",
  FINISHED: "#389e0d",
  FAILED: "#cf1322",
  RUNNING: "#fa8c16",
};
const TERMINAL_TRAINING_STATUSES = new Set(["completed", "failed", "cancelled"]);

interface ProjectOption {
  id: string;
  name: string;
}

interface DatasetOption {
  id?: string;
  artifact_id?: string;
  name?: string;
  filename?: string;
}

function JsonValue({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <>-</>;
  return <pre style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(value, null, 2)}</pre>;
}

export default function TrainingJobsPage() {
  const { t, lang } = useI18n();
  const labels = t.training;
  const [experimentForm] = Form.useForm();
  const [trainingForm] = Form.useForm();
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState<string>();
  const [jobProjectId, setJobProjectId] = useState<string>();
  const [experimentProjectId, setExperimentProjectId] = useState<string>();
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshingJobs, setRefreshingJobs] = useState(false);
  const [activeTab, setActiveTab] = useState("experiments");
  const [createExperimentOpen, setCreateExperimentOpen] = useState(false);
  const [createTrainingOpen, setCreateTrainingOpen] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);
  const [runsLoading, setRunsLoading] = useState(false);
  const [activeExperiment, setActiveExperiment] = useState<Experiment | null>(null);
  const [runs, setRuns] = useState<ExperimentRun[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<React.Key[]>([]);
  const [comparison, setComparison] = useState<RunComparison | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [detail, setDetail] = useState<TrainingJob | null>(null);
  const [resumeJob, setResumeJob] = useState<TrainingJob | null>(null);
  const [checkpoints, setCheckpoints] = useState<TrainingCheckpoint[]>([]);

  const loadExperiments = useCallback(async (selectedProjectId?: string) => {
    setLoading(true);
    try {
      setExperiments(await listExperiments(selectedProjectId));
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    } finally {
      setLoading(false);
    }
  }, [t.common.error]);

  const loadJobs = useCallback(async (selectedProjectId?: string) => {
    setRefreshingJobs(true);
    try {
      setJobs(await listTrainingJobs(selectedProjectId));
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    } finally {
      setRefreshingJobs(false);
    }
  }, [t.common.error]);

  useEffect(() => {
    apiClient.get("/projects").then((response) => {
      const items = (response.data.items || response.data || []) as ProjectOption[];
      setProjects(items);
      if (items[0]) setProjectId((current) => current || items[0].id);
    }).catch((error) => message.error(formatApiError(error, t.common.error)));
  }, [t.common.error]);

  useEffect(() => {
    void loadExperiments(experimentProjectId);
  }, [experimentProjectId, loadExperiments]);

  useEffect(() => {
    void loadJobs(jobProjectId);
  }, [jobProjectId, loadJobs]);

  useEffect(() => {
    if (!jobs.some((job) => !TERMINAL_TRAINING_STATUSES.has(job.status || ""))) return;
    const timer = window.setInterval(() => void loadJobs(jobProjectId), 1500);
    return () => window.clearInterval(timer);
  }, [jobProjectId, jobs, loadJobs]);

  const refresh = () => {
    if (activeTab === "experiments") void loadExperiments(experimentProjectId);
    else void loadJobs(jobProjectId);
  };

  const submitExperiment = async (values: { name: string; description?: string }) => {
    if (!projectId) return;
    try {
      await createExperiment({ project_id: projectId, name: values.name, description: values.description || "" });
      message.success(t.common.success);
      setCreateExperimentOpen(false);
      experimentForm.resetFields();
      await loadExperiments(projectId);
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    }
  };

  const removeExperiment = async (experiment: Experiment) => {
    try {
      await deleteExperiment(experiment.id);
      message.success(t.common.success);
      await loadExperiments(projectId);
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    }
  };

  const openRuns = async (experiment: Experiment) => {
    setActiveExperiment(experiment);
    setRunsOpen(true);
    setRunsLoading(true);
    setRuns([]);
    setSelectedRunIds([]);
    try {
      const result = await listExperimentRuns(experiment.id);
      setRuns(result.items);
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    } finally {
      setRunsLoading(false);
    }
  };

  const compareRuns = async () => {
    if (!activeExperiment || selectedRunIds.length < 2 || selectedRunIds.length > 10) return;
    setComparisonLoading(true);
    try {
      setComparison(await compareExperimentRuns(activeExperiment.id, selectedRunIds.map(String)));
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    } finally {
      setComparisonLoading(false);
    }
  };

  const selectProjectForTraining = async (selectedProjectId: string) => {
    trainingForm.setFieldsValue({ experiment_id: undefined, dataset_artifact_id: undefined, target_column: undefined });
    setColumns([]);
    const response = await apiClient.get(`/projects/${selectedProjectId}/datasets`);
    setDatasets(response.data.items || response.data || []);
  };

  const selectDataset = async (artifactId: string) => {
    trainingForm.setFieldValue("target_column", undefined);
    const response = await apiClient.get(`/datasets/${artifactId}/preview`);
    setColumns(response.data.columns || []);
  };

  const submitTraining = async (values: {
    project_id: string;
    experiment_id: string;
    dataset_artifact_id: string;
    name: string;
    target_column: string;
    task: "auto" | "classification" | "regression";
    total_epochs: number;
  }) => {
    try {
      await createTrainingJob({ ...values, monitor: "val_loss", mode: "min", patience: 5, restore_best: true, checkpoint_interval: 1 });
      notifyDashboardStatsChanged();
      message.success(t.common.success);
      setCreateTrainingOpen(false);
      trainingForm.resetFields();
      await loadJobs(jobProjectId);
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    }
  };

  const showDetail = async (jobId: string) => {
    try {
      setDetail(await getTrainingJob(jobId));
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    }
  };

  const stopJob = async (job: TrainingJob) => {
    try {
      await stopTrainingJob(job.id);
      notifyDashboardStatsChanged();
      await loadJobs(jobProjectId);
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    }
  };

  const removeTrainingJob = async (job: TrainingJob) => {
    try {
      const result = await deleteTrainingJob(job.id);
      if (result.deleted !== 1) message.error(t.common.error);
      else {
        notifyDashboardStatsChanged();
        message.success(t.common.success);
      }
      await loadJobs(jobProjectId);
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    }
  };

  const openResume = async (job: TrainingJob) => {
    try {
      setCheckpoints(await listTrainingCheckpoints(job.id));
      setResumeJob(job);
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    }
  };

  const resumeFrom = async (checkpoint: TrainingCheckpoint) => {
    if (!resumeJob) return;
    try {
      await resumeTrainingJob(resumeJob.id, checkpoint.path);
      notifyDashboardStatsChanged();
      setResumeJob(null);
      await loadJobs(jobProjectId);
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    }
  };

  const openTensorBoard = async (job: TrainingJob) => {
    try {
      const session = await createTensorBoardSession(job.id);
      window.open(session.url, "_blank", "noopener,noreferrer");
    } catch (error) {
      message.error(formatApiError(error, t.common.error));
    }
  };

  const comparisonChart = useMemo(() => {
    if (!comparison) return {};
    return {
      tooltip: { trigger: "axis" },
      legend: { data: comparison.runs.map((run) => run.run_id) },
      xAxis: { type: "value", name: labels.epoch },
      yAxis: { type: "value", scale: true },
      series: comparison.runs.flatMap((run) => comparison.metric_names.map((metric) => ({
        name: run.run_id,
        type: "line",
        showSymbol: false,
        data: (run.metric_history[metric] || []).map((point) => [point.step, point.value]),
      }))),
    };
  }, [comparison, labels.epoch]);

  const activeExperimentIds = useMemo(() => new Set(
    jobs.filter((job) => !TERMINAL_TRAINING_STATUSES.has(job.status || ""))
      .flatMap((job) => job.experiment_id ? [job.experiment_id] : []),
  ), [jobs]);

  const experimentColumns = [
    { title: labels.experiment_name, dataIndex: "name", key: "name" },
    { title: labels.project, dataIndex: "project_name", key: "project", render: (value: string, experiment: Experiment) => value || experiment.project_id || "-" },
    { title: labels.creator || "Creator", dataIndex: "created_by_name", key: "creator", render: (value: string, experiment: Experiment) => value || experiment.created_by || "-" },
    { title: labels.description, dataIndex: "description", key: "description", render: (value: string) => value || "-" },
    { title: labels.runs, dataIndex: "run_count", key: "run_count", width: 100 },
    { title: labels.started, dataIndex: "created_at", key: "created_at", width: 180, render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm") },
    {
      title: t.model.actions,
      key: "actions",
      width: 160,
      className: "training-operation-column",
      align: "right" as const,
      onHeaderCell: () => ({ style: { textAlign: "right" as const } }),
      onCell: () => ({ style: { textAlign: "right" as const } }),
      render: (_: unknown, experiment: Experiment) => <div className="table-row-actions">
        <TableRowAction label={`${labels.runs} ${experiment.name}`} icon={<BarChartOutlined />} onClick={() => void openRuns(experiment)} />
        {!activeExperimentIds.has(experiment.id) && <DeleteConfirmation
          label={`${t.common.delete} ${experiment.name}`}
          targetName={experiment.name}
          onConfirm={() => void removeExperiment(experiment)}
        />
        }
      </div>,
    },
  ];

  const jobColumns = [
    { title: labels.name, dataIndex: "name", key: "name", width: 180 },
    { title: labels.project, dataIndex: "project_name", key: "project", width: 160, render: (value: string, job: TrainingJob) => value || job.project_id || "-" },
    { title: labels.creator || "Creator", dataIndex: "created_by_name", key: "creator", width: 140, render: (value: string, job: TrainingJob) => value || job.created_by_id || job.user_id || "-" },
    {
      title: labels.status,
      dataIndex: "status",
      key: "status",
      width: 140,
      render: (value: string) => <Tag color={taskStatusColor(value)}>{taskStatusLabel(value, lang)}</Tag>,
    },
    {
      title: labels.progress,
      key: "progress",
      width: 240,
      render: (_: unknown, job: TrainingJob) => {
        const progress = job.metrics?.progress;
        const progressRecord = progress && typeof progress === "object" ? progress as Record<string, unknown> : undefined;
        const current = Number(progressRecord?.completed ?? job.current_epoch) || 0;
        const total = Number(progressRecord?.total ?? job.total_epochs) || 0;
        const percent = typeof progressRecord?.percent === "number"
          ? Math.min(100, Math.max(0, Math.round(progressRecord.percent)))
          : total ? Math.min(100, Math.round((current / total) * 100)) : 0;
        return <Space direction="vertical" size={2} style={{ width: "100%" }}>
          <Progress percent={percent} size="small" strokeColor={taskStatusColor(job.status)} />
          <Text type="secondary">{labels.epoch} {current}/{total || "-"}</Text>
        </Space>;
      },
    },
    { title: labels.started, dataIndex: "created_at", key: "created_at", width: 180, render: (value: string) => value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "-" },
    {
      title: t.model.actions,
      key: "actions",
      width: 260,
      className: "training-operation-column",
      align: "right" as const,
      onHeaderCell: () => ({ style: { textAlign: "right" as const } }),
      onCell: () => ({ style: { textAlign: "right" as const } }),
      render: (_: unknown, job: TrainingJob) => {
        const isAutoMLJob = job.operator_id === "automl";
        return <div className="table-row-actions">
        <TableRowAction label={labels.details} icon={<EyeOutlined />} onClick={() => void showDetail(job.id)} />
        {job.status === "running" && <Popconfirm title={`${labels.stop} ${job.name}?`} onConfirm={() => void stopJob(job)} okText={labels.confirm_stop}>
          <span><TableRowAction label={`${labels.stop} ${job.name}`} icon={<PauseCircleOutlined />} warning /></span>
        </Popconfirm>}
        {job.status !== "running" && <TableRowAction label={labels.resume} icon={<PlayCircleOutlined />} disabled={isAutoMLJob} onClick={() => void openResume(job)} />}
        {job.mlflow_run_id && <TableRowAction label={labels.tensorboard} icon={<BarChartOutlined />} disabled={isAutoMLJob} onClick={() => void openTensorBoard(job)} />}
        {TERMINAL_TRAINING_STATUSES.has(job.status || "") && <DeleteConfirmation
          label={`${t.common.delete} ${job.name}`}
          targetName={job.name}
          onConfirm={() => void removeTrainingJob(job)}
        />}
      </div>;
      },
    },
  ];

  return <AppLayout>
    <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
      <Title level={4} style={{ margin: 0 }}>{labels.title}</Title>
      <Space wrap>
        <Select
          aria-label={labels.project}
          value={activeTab === "jobs" ? jobProjectId || "" : experimentProjectId || ""}
          style={{ minWidth: 220 }}
          options={[
            { value: "", label: labels.all_projects || "All projects" },
            ...projects.map((project) => ({ value: project.id, label: project.name })),
          ]}
          onChange={(value) => activeTab === "jobs" ? setJobProjectId(value || undefined) : setExperimentProjectId(value || undefined)}
        />
        <Button icon={<ReloadOutlined />} loading={activeTab === "jobs" && refreshingJobs} onClick={refresh}>{t.common.refresh}</Button>
        {activeTab === "experiments"
          ? <Button aria-label={labels.new_experiment} type="primary" icon={<PlusOutlined />} disabled={!projectId} onClick={() => setCreateExperimentOpen(true)}>{labels.new_experiment}</Button>
          : <Button aria-label={labels.new_job} type="primary" icon={<PlusOutlined />} onClick={() => setCreateTrainingOpen(true)}>{labels.new_job}</Button>}
      </Space>
    </div>

    <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
      {
        key: "experiments",
        label: labels.experiments,
        children: <div className="table-surface training-experiments__table"><Table rowKey="id" size="small" scroll={{ x: 760 }} dataSource={experiments} columns={experimentColumns} loading={loading} locale={{ emptyText: t.common.no_data }} /></div>,
      },
      {
        key: "jobs",
        label: labels.jobs,
        children: <div className="table-surface training-jobs__table"><Table rowKey="id" size="small" scroll={{ x: 980 }} dataSource={jobs} columns={jobColumns} loading={loading} locale={{ emptyText: t.common.no_data }} /></div>,
      },
    ]} />

    <Modal title={labels.new_experiment} open={createExperimentOpen} onCancel={() => setCreateExperimentOpen(false)} onOk={() => experimentForm.submit()} okText={t.common.create} destroyOnHidden>
      <Form form={experimentForm} layout="vertical" onFinish={submitExperiment} initialValues={{ description: "" }}>
        <Form.Item name="name" label={labels.experiment_name} rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="description" label={labels.description}><Input.TextArea rows={3} /></Form.Item>
      </Form>
    </Modal>

    <Modal
      title={`${activeExperiment?.name || ""} · ${labels.runs}`}
      open={runsOpen}
      width="min(960px, calc(100vw - 32px))"
      onCancel={() => setRunsOpen(false)}
      footer={<Space><Text type="secondary">{selectedRunIds.length}/10</Text><Button type="primary" disabled={selectedRunIds.length < 2 || selectedRunIds.length > 10} loading={comparisonLoading} onClick={() => void compareRuns()}>{labels.compare}</Button></Space>}
    >
      <Table
        rowKey="run_id"
        size="small"
        loading={runsLoading}
        dataSource={runs}
        rowSelection={{
          selectedRowKeys: selectedRunIds,
          onChange: setSelectedRunIds,
          getCheckboxProps: (run) => ({ "aria-label": run.run_id } as unknown as CheckboxProps),
        }}
        columns={[
          { title: "Run ID", dataIndex: "run_id", key: "run_id" },
          { title: labels.name, dataIndex: "run_name", key: "run_name", render: (value: string) => value || "-" },
          { title: labels.status, dataIndex: "status", key: "status", render: (value: string) => <Tag color={statusColors[value]}>{value}</Tag> },
          { title: labels.metrics, dataIndex: "metrics", key: "metrics", render: (value: unknown) => <JsonValue value={value} /> },
        ]}
      />
    </Modal>

    <Modal title={labels.compare} open={Boolean(comparison)} width="min(1080px, calc(100vw - 32px))" footer={null} onCancel={() => setComparison(null)}>
      {comparison && <>
        <Table
          rowKey="name"
          size="small"
          pagination={false}
          scroll={{ x: 560 }}
          dataSource={comparison.metric_names.map((name) => ({ name }))}
          columns={[
            { title: labels.metrics, dataIndex: "name", key: "name" },
            ...comparison.runs.map((run) => ({ title: run.run_id, key: run.run_id, render: (_: unknown, row: { name: string }) => run.metrics[row.name] ?? "-" })),
          ]}
        />
        <ReactECharts option={comparisonChart} style={{ height: 320, marginTop: 16 }} />
      </>}
    </Modal>

    <Modal title={labels.new_job} open={createTrainingOpen} onCancel={() => setCreateTrainingOpen(false)} onOk={() => trainingForm.submit()} okText={t.common.create} destroyOnHidden>
      <Form form={trainingForm} layout="vertical" onFinish={submitTraining} initialValues={{ task: "auto", total_epochs: 20 }}>
        <Form.Item name="name" label={labels.name} rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="project_id" label={labels.project} rules={[{ required: true }]}><Select options={projects.map((item) => ({ value: item.id, label: item.name }))} onChange={(value) => void selectProjectForTraining(value)} /></Form.Item>
        <Form.Item name="experiment_id" label={labels.experiment_name} rules={[{ required: true }]}><Select options={experiments.map((item) => ({ value: item.id, label: item.name }))} /></Form.Item>
        <Form.Item name="dataset_artifact_id" label={labels.dataset_artifact} rules={[{ required: true }]}><Select options={datasets.map((item) => ({ value: item.artifact_id || item.id, label: item.name || item.filename }))} onChange={(value) => void selectDataset(value)} /></Form.Item>
        <Form.Item name="target_column" label={labels.target_column} rules={[{ required: true }]}><Select options={columns.map((name) => ({ value: name, label: name }))} /></Form.Item>
        <Form.Item name="task" label={labels.task} rules={[{ required: true }]}><Select options={["auto", "classification", "regression"].map((value) => ({ value, label: value }))} /></Form.Item>
        <Form.Item name="total_epochs" label={labels.total_epochs} rules={[{ required: true }]}><InputNumber min={1} max={10000} style={{ width: "100%" }} /></Form.Item>
      </Form>
    </Modal>

    <Modal title={labels.checkpoints} open={Boolean(resumeJob)} footer={null} onCancel={() => setResumeJob(null)}>
      <Table rowKey="path" size="small" pagination={false} dataSource={checkpoints} columns={[
        { title: labels.checkpoints, dataIndex: "path", key: "path" },
        { title: t.model.actions, key: "action", width: 80, render: (_: unknown, checkpoint: TrainingCheckpoint) => <Button aria-label={`${labels.resume} ${checkpoint.path}`} icon={<PlayCircleOutlined />} onClick={() => void resumeFrom(checkpoint)} /> },
      ]} />
    </Modal>

    <Drawer title={labels.details} open={Boolean(detail)} onClose={() => setDetail(null)} width="min(760px, 100vw)">
      {detail && <Descriptions bordered column={1} size="small">
        <Descriptions.Item label={labels.dataset_artifact}>{detail.dataset_artifact_id || "-"}</Descriptions.Item>
        <Descriptions.Item label={labels.model_artifact}>{detail.model_artifact_id || "-"}</Descriptions.Item>
        <Descriptions.Item label={labels.model_library}>{detail.model_library_id || "-"}</Descriptions.Item>
        <Descriptions.Item label={labels.feature_schema}><JsonValue value={detail.feature_schema} /></Descriptions.Item>
        <Descriptions.Item label={labels.target_schema}><JsonValue value={detail.target_schema} /></Descriptions.Item>
        <Descriptions.Item label={labels.preprocessing}><JsonValue value={detail.preprocessing} /></Descriptions.Item>
        <Descriptions.Item label={labels.metrics}><JsonValue value={detail.metrics} /></Descriptions.Item>
        <Descriptions.Item label={labels.logs}><JsonValue value={detail.logs} /></Descriptions.Item>
        <Descriptions.Item label={labels.error_code}>{detail.error_code || detail.error_message || "-"}</Descriptions.Item>
      </Descriptions>}
    </Drawer>
  </AppLayout>;
}
