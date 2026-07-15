import { useCallback, useEffect, useState } from "react";
import { Button, Card, Descriptions, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from "antd";
import { EyeOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import apiClient, { formatApiError } from "../api/client";
import { createTrainingJob, getTrainingJob, listTrainingJobs, type TrainingJob } from "../api/training";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Title } = Typography;
const statusColors: Record<string, string> = {
  pending: "default", running: "processing", completed: "success", failed: "error",
};

function JsonValue({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return <>-</>;
  return <pre style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(value, null, 2)}</pre>;
}

export default function TrainingJobsPage() {
  const { t } = useI18n();
  const labels = t.training as typeof t.training & Record<string, string>;
  const [form] = Form.useForm();
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [projects, setProjects] = useState<any[]>([]);
  const [datasets, setDatasets] = useState<any[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [detail, setDetail] = useState<TrainingJob | null>(null);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    try { setJobs(await listTrainingJobs()); }
    catch (error) { message.error(formatApiError(error, t.common.error)); }
    finally { setLoading(false); }
  }, [t.common.error]);

  useEffect(() => { void loadJobs(); }, [loadJobs]);
  useEffect(() => {
    apiClient.get("/projects").then((response) => setProjects(response.data.items || response.data || []));
  }, []);

  const selectProject = async (projectId: string) => {
    form.setFieldsValue({ dataset_artifact_id: undefined, target_column: undefined });
    setColumns([]);
    const response = await apiClient.get(`/projects/${projectId}/datasets`);
    setDatasets(response.data.items || response.data || []);
  };

  const selectDataset = async (artifactId: string) => {
    form.setFieldValue("target_column", undefined);
    const response = await apiClient.get(`/datasets/${artifactId}/preview`);
    setColumns(response.data.columns || []);
  };

  const submit = async (values: any) => {
    setSubmitting(true);
    try {
      await createTrainingJob({
        project_id: values.project_id,
        dataset_artifact_id: values.dataset_artifact_id,
        name: values.name,
        operator_id: values.operator_id,
        params: { target_column: values.target_column },
      });
      message.success(t.common.success);
      setCreateOpen(false);
      form.resetFields();
      await loadJobs();
    } catch (error) { message.error(formatApiError(error, t.common.error)); }
    finally { setSubmitting(false); }
  };

  const showDetail = async (jobId: string) => {
    try { setDetail(await getTrainingJob(jobId)); }
    catch (error) { message.error(formatApiError(error, t.common.error)); }
  };

  const tableColumns = [
    { title: labels.name || "Name", dataIndex: "name", key: "name" },
    { title: labels.operator || "Operator", dataIndex: "operator_id", key: "operator_id", render: (value: string) => value ? <Tag>{value}</Tag> : "-" },
    { title: labels.status || "Status", dataIndex: "status", key: "status", render: (value: string) => <Tag color={statusColors[value]}>{value || "pending"}</Tag> },
    { title: labels.metrics || "Metrics", dataIndex: "metrics", key: "metrics", render: (value: unknown) => <JsonValue value={value} /> },
    { title: labels.started || "Started", dataIndex: "created_at", key: "created_at", render: (value: string) => value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "-" },
    { title: t.model.actions, key: "actions", render: (_: unknown, job: TrainingJob) => <Button icon={<EyeOutlined />} onClick={() => void showDetail(job.id)}>{labels.details || "Details"}</Button> },
  ];

  return <AppLayout>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
      <Title level={4} style={{ margin: 0 }}>{labels.title}</Title>
      <Space>
        <Button icon={<ReloadOutlined />} onClick={() => void loadJobs()}>{t.common.refresh}</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>{labels.new_job}</Button>
      </Space>
    </div>
    <Card><Table rowKey="id" dataSource={jobs} columns={tableColumns} loading={loading} locale={{ emptyText: t.common.no_data }} /></Card>

    <Modal title={labels.new_job} open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={submit} initialValues={{ operator_id: "random_forest" }}>
        <Form.Item name="name" label={labels.name} rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="project_id" label={labels.project} rules={[{ required: true }]}>
          <Select options={projects.map((item) => ({ value: item.id, label: item.name }))} onChange={(value) => void selectProject(value)} />
        </Form.Item>
        <Form.Item name="dataset_artifact_id" label={labels.dataset_artifact} rules={[{ required: true }]}>
          <Select options={datasets.map((item) => ({ value: item.artifact_id || item.id, label: item.name || item.filename }))} onChange={(value) => void selectDataset(value)} />
        </Form.Item>
        <Form.Item name="target_column" label={labels.target_column} rules={[{ required: true }]}>
          <Select options={columns.map((name) => ({ value: name, label: name }))} />
        </Form.Item>
        <Form.Item name="operator_id" label={labels.operator} rules={[{ required: true }]}>
          <Select options={[{ value: "random_forest", label: "Random Forest" }, { value: "random_forest_classifier", label: "Random Forest Classifier" }, { value: "random_forest_regressor", label: "Random Forest Regressor" }]} />
        </Form.Item>
      </Form>
    </Modal>

    <Modal title={labels.details || "Details"} open={Boolean(detail)} onCancel={() => setDetail(null)} footer={null} width={760}>
      {detail && <Descriptions bordered column={1} size="small">
        <Descriptions.Item label={labels.dataset_artifact}><span>{detail.dataset_artifact_id || "-"}</span></Descriptions.Item>
        <Descriptions.Item label={labels.model_artifact}><span>{detail.model_artifact_id || "-"}</span></Descriptions.Item>
        <Descriptions.Item label={labels.model_library}><span>{detail.model_library_id || "-"}</span></Descriptions.Item>
        <Descriptions.Item label={labels.feature_schema}><JsonValue value={detail.feature_schema} /></Descriptions.Item>
        <Descriptions.Item label={labels.target_schema}><JsonValue value={detail.target_schema} /></Descriptions.Item>
        <Descriptions.Item label={labels.preprocessing}><JsonValue value={detail.preprocessing} /></Descriptions.Item>
        <Descriptions.Item label={labels.metrics}><JsonValue value={detail.metrics} /></Descriptions.Item>
        <Descriptions.Item label={labels.logs}><JsonValue value={detail.logs} /></Descriptions.Item>
        <Descriptions.Item label={labels.error_code}><span>{detail.error_code || detail.error_message || "-"}</span></Descriptions.Item>
      </Descriptions>}
    </Modal>
  </AppLayout>;
}
