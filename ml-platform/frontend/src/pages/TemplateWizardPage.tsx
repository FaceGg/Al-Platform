import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { App as AntApp, Button, Descriptions, Empty, Form, Input, InputNumber, Select, Space, Tag, Typography } from "antd";
import { PlusOutlined, SwapOutlined } from "@ant-design/icons";
import apiClient, { formatApiError } from "../api/client";
import { getTemplate, instantiateTemplate, type IndustrialTemplateDetail } from "../api/templates";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Title, Paragraph, Text } = Typography;

interface ProjectOption {
  id: string;
  name: string;
}

interface DatasetOption {
  artifact_id?: string;
  id: string;
  name: string;
  row_count?: number;
}

export default function TemplateWizardPage() {
  const { message } = AntApp.useApp();
  const { templateId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { t } = useI18n();
  const labels = t.template as typeof t.template & Record<string, string>;
  const [form] = Form.useForm();
  const [projectForm] = Form.useForm();
  const [template, setTemplate] = useState<IndustrialTemplateDetail | null>(null);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [datasets, setDatasets] = useState<DatasetOption[]>([]);
  const [creatingProject, setCreatingProject] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const loadDatasets = async (projectId: string) => {
    form.setFieldsValue({ project_id: projectId, dataset_artifact_id: undefined });
    setDatasets([]);
    const response = await apiClient.get(`/projects/${projectId}/datasets`);
    setDatasets(response.data.items || response.data || []);
  };

  useEffect(() => {
    Promise.all([getTemplate(templateId), apiClient.get("/projects")])
      .then(([templateDetail, projectResponse]) => {
        setTemplate(templateDetail);
        setProjects(projectResponse.data.items || projectResponse.data || []);
        const defaults = Object.fromEntries(
          templateDetail.parameters.map((parameter) => [parameter.key, parameter.default]),
        );
        form.setFieldsValue({ parameters: defaults });
        const initialProject = searchParams.get("project");
        if (initialProject) void loadDatasets(initialProject);
      })
      .catch((error) => message.error(formatApiError(error, labels.load_failed)));
  }, [templateId]);

  const createProject = async (values: { name: string; description?: string }) => {
    try {
      const response = await apiClient.post("/projects", {
        name: values.name,
        description: values.description || "",
      });
      const project = response.data as ProjectOption;
      setProjects((current) => [...current, project]);
      setCreatingProject(false);
      projectForm.resetFields();
      await loadDatasets(project.id);
    } catch (error) {
      message.error(formatApiError(error, labels.create_failed));
    }
  };

  const submit = async (values: {
    project_id: string;
    dataset_artifact_id: string;
    parameters?: Record<string, number | string>;
  }) => {
    setSubmitting(true);
    try {
      const result = await instantiateTemplate(templateId, {
        project_id: values.project_id,
        dataset_artifact_id: values.dataset_artifact_id,
        parameters: values.parameters || {},
      });
      navigate(`/workspace/${result.workflow_id}`);
    } catch (error) {
      message.error(formatApiError(error, labels.create_failed));
    } finally {
      setSubmitting(false);
    }
  };

  if (!template) {
    return <AppLayout><div style={{ minHeight: 240 }} /></AppLayout>;
  }

  return <AppLayout>
    <div style={{ maxWidth: 920, margin: "0 auto" }}>
      <div style={{ borderBottom: "1px solid #d9dde3", paddingBottom: 20, marginBottom: 24 }}>
        <Text type="secondary">{labels.wizard_title}</Text>
        <Title level={3} style={{ margin: "4px 0 8px", letterSpacing: 0 }}>{template.name}</Title>
        <Paragraph style={{ maxWidth: 720, marginBottom: 16 }}>{template.description}</Paragraph>
        <Descriptions column={{ xs: 1, sm: 3 }} size="small">
          <Descriptions.Item label={labels.scenario}>{template.scenario}</Descriptions.Item>
          <Descriptions.Item label={labels.target}><Tag color="red">{template.target_column}</Tag></Descriptions.Item>
          <Descriptions.Item label={labels.required_columns}>
            <Space size={[4, 4]} wrap>{template.required_columns.map((column) => <Tag key={column}>{column}</Tag>)}</Space>
          </Descriptions.Item>
        </Descriptions>
      </div>

      <Form form={form} layout="vertical" onFinish={submit} requiredMark="optional">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 20 }}>
          <section>
            <Title level={5}>{labels.project}</Title>
            {!creatingProject ? <>
              <Form.Item name="project_id" label={labels.project} rules={[{ required: true }]}>
                <Select
                  options={projects.map((project) => ({ value: project.id, label: project.name }))}
                  onChange={(value) => void loadDatasets(value)}
                />
              </Form.Item>
              <Button icon={<PlusOutlined />} onClick={() => setCreatingProject(true)}>{labels.create_project}</Button>
            </> : <Form form={projectForm} component={false} onFinish={createProject}>
              <Form.Item name="name" label={labels.project_name} rules={[{ required: true }]}><Input /></Form.Item>
              <Form.Item name="description" label={labels.project_description}><Input.TextArea rows={2} /></Form.Item>
              <Space wrap>
                <Button type="primary" onClick={() => projectForm.submit()}>{labels.create_project}</Button>
                <Button icon={<SwapOutlined />} onClick={() => setCreatingProject(false)}>{labels.use_existing_project}</Button>
              </Space>
            </Form>}
          </section>

          <section>
            <Title level={5}>{labels.dataset_artifact}</Title>
            <Form.Item name="dataset_artifact_id" label={labels.dataset_artifact} rules={[{ required: true }]}>
              <Select
                notFoundContent={<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={labels.no_datasets} />}
                options={datasets.map((dataset) => ({
                  value: dataset.artifact_id || dataset.id,
                  label: dataset.row_count ? `${dataset.name} (${dataset.row_count})` : dataset.name,
                }))}
              />
            </Form.Item>
          </section>
        </div>

        <section style={{ borderTop: "1px solid #d9dde3", marginTop: 24, paddingTop: 20 }}>
          <Title level={5}>{labels.parameter_config}</Title>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0 20px" }}>
            {template.parameters.map((parameter) => <Form.Item
              key={parameter.key}
              name={["parameters", parameter.key]}
              label={parameter.label}
              rules={[{ required: parameter.required }]}
            >
              {parameter.type === "int" ? <InputNumber precision={0} style={{ width: "100%" }} />
                : parameter.type === "float" ? <InputNumber step={0.01} style={{ width: "100%" }} />
                  : <Input />}
            </Form.Item>)}
          </div>
        </section>

        <Button type="primary" htmlType="submit" loading={submitting} size="large">
          {labels.create_workflow}
        </Button>
      </Form>
    </div>
  </AppLayout>;
}
