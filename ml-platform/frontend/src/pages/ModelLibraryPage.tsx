import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert, Button, Descriptions, Drawer, Empty, Form, Input, Modal, Progress,
  Select, Space, Table, Tabs, Tag, Tooltip, Typography, Upload, message,
} from "antd";
import {
  CheckOutlined, CloudServerOutlined, DeleteOutlined, EyeOutlined, PlayCircleOutlined,
  PlusOutlined, ReloadOutlined, StopOutlined,
} from "@ant-design/icons";
import apiClient, { formatApiError } from "../api/client";
import {
  approveModelVersion, createDeployment, createRegisteredModel, deleteDeployment, deleteRegisteredModel,
  type InferenceDeployment, type InferenceRecord, listDeployments,
  listModelVersions, listRegisteredModels, type ModelVersion,
  predictDeployment, type PredictionResult, type ProjectOption,
  type RegisteredModel, registerOnnxVersion, registerPlatformVersion, rejectModelVersion,
  startDeployment, stopDeployment, uploadOnnxArtifact,
} from "../api/modelRegistry";
import { listQualityModels, type QualityModel } from "../api/spotWeldQuality";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";
import { useSearchParams } from "react-router-dom";

const { Text, Title } = Typography;

export default function ModelLibraryPage() {
  const { t } = useI18n();
  const copy = t.modelRegistry;
  const [searchParams] = useSearchParams();
  const requestedProjectId = searchParams.get("projectId") || undefined;
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState<string | undefined>(requestedProjectId);
  const [tab, setTab] = useState("models");
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [deployments, setDeployments] = useState<InferenceDeployment[]>([]);
  const [versions, setVersions] = useState<Record<string, ModelVersion[]>>({});
  const [qualityModels, setQualityModels] = useState<QualityModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [registerModel, setRegisterModel] = useState<RegisteredModel>();
  const [modelOpen, setModelOpen] = useState(false);
  const [versionModel, setVersionModel] = useState<RegisteredModel>();
  const [deploymentOpen, setDeploymentOpen] = useState(false);
  const [testDeployment, setTestDeployment] = useState<InferenceDeployment>();
  const [prediction, setPrediction] = useState<PredictionResult>();
  const [busyId, setBusyId] = useState<string>();
  const [registerSource, setRegisterSource] = useState<"platform_joblib" | "onnx_artifact">("platform_joblib");
  const [registerForm] = Form.useForm();
  const [modelForm] = Form.useForm();
  const [deploymentForm] = Form.useForm();
  const [predictionForm] = Form.useForm();

  const selectedProject = projects.find((item) => item.id === projectId);
  const role = selectedProject?.project_role;
  const canRegister = role === "owner" || role === "editor";
  const canOperate = canRegister || role === "operator";

  useEffect(() => {
    apiClient.get("/projects").then((response) => {
      const items = Array.isArray(response.data) ? response.data : response.data?.items;
      setProjects(Array.isArray(items) ? items : []);
    }).catch((cause) => setError(formatApiError(cause, copy.loadFailed)));
  }, [copy.loadFailed]);

  useEffect(() => {
    if (requestedProjectId && requestedProjectId !== projectId) setProjectId(requestedProjectId);
  }, [projectId, requestedProjectId]);

  const loadProject = useCallback(async (selected: string) => {
    setLoading(true);
    setError(undefined);
    try {
      const [modelItems, deploymentItems, qualityModelItems] = await Promise.all([
        listRegisteredModels(selected), listDeployments(selected), listQualityModels(selected),
      ]);
      setModels(modelItems);
      setDeployments(deploymentItems);
      setQualityModels(qualityModelItems);
      const entries = await Promise.all(modelItems.map(async (model) => [
        model.id, await listModelVersions(model.id),
      ] as const));
      setVersions(Object.fromEntries(entries));
    } catch (cause) {
      setError(formatApiError(cause, copy.loadFailed));
      setModels([]);
      setDeployments([]);
      setQualityModels([]);
    } finally {
      setLoading(false);
    }
  }, [copy.loadFailed]);

  useEffect(() => {
    if (projectId) void loadProject(projectId);
  }, [loadProject, projectId]);

  const statusLabel = (status: string) => {
    const labels = copy as Record<string, string>;
    return labels[status] || status;
  };
  const statusColor = (status: string) => {
    if (status === "approved" || status === "running" || status === "completed") return "success";
    if (status === "pending" || status === "starting" || status === "stopping") return "processing";
    if (status === "rejected" || status === "failed") return "error";
    return "default";
  };

  const approvedVersions = useMemo(() => models.flatMap((model) =>
    (versions[model.id] || []).filter((version) => version.approval_status === "approved")
      .map((version) => ({ model, version }))), [models, versions]);

  const submitVersion = async () => {
    if (!registerModel) return;
    try {
      const values = await registerForm.validateFields();
      let created: ModelVersion;
      if (registerSource === "platform_joblib") {
        created = await registerPlatformVersion(registerModel.id, values.source_model_library_id.trim());
      } else {
        const uploaded = await uploadOnnxArtifact(projectId!, values.onnx_file[0].originFileObj);
        created = await registerOnnxVersion(registerModel.id, {
          source_artifact_id: uploaded.id,
          feature_schema: JSON.parse(values.feature_schema),
          output_schema: JSON.parse(values.output_schema),
        });
      }
      setVersions((current) => ({
        ...current,
        [registerModel.id]: [created, ...(current[registerModel.id] || [])],
      }));
      setModels((current) => current.map((item) => item.id === registerModel.id ? {
        ...item, latest_version: created.version_number,
        latest_approval_status: created.approval_status,
      } : item));
      setRegisterModel(undefined);
      registerForm.resetFields();
    } catch (cause) {
      if (!(cause as { errorFields?: unknown }).errorFields) message.error(formatApiError(cause, copy.commandFailed));
    }
  };

  const submitModel = async () => {
    if (!projectId) return;
    try {
      const values = await modelForm.validateFields();
      const created = await createRegisteredModel(projectId, {
        name: values.name.trim(), description: values.description?.trim() || "",
      });
      setModels((current) => [created, ...current]);
      setVersions((current) => ({ ...current, [created.id]: [] }));
      setModelOpen(false);
      modelForm.resetFields();
    } catch (cause) {
      if (!(cause as { errorFields?: unknown }).errorFields) message.error(formatApiError(cause, copy.commandFailed));
    }
  };

  const approve = async (model: RegisteredModel, version: ModelVersion) => {
    try {
      const updated = await approveModelVersion(version.id, "");
      setVersions((current) => ({
        ...current,
        [model.id]: (current[model.id] || []).map((item) => item.id === updated.id ? updated : item),
      }));
      setModels((current) => current.map((item) => item.id === model.id ? {
        ...item, latest_approval_status: updated.approval_status,
      } : item));
    } catch (cause) {
      message.error(formatApiError(cause, copy.commandFailed));
    }
  };

  const reject = (model: RegisteredModel, version: ModelVersion) => {
    let rejectionComment = "";
    Modal.confirm({
      title: copy.reject,
      content: <Input.TextArea aria-label={copy.comment} onChange={(event) => { rejectionComment = event.target.value; }} />,
      onOk: async () => {
      const comment = rejectionComment.trim();
      if (!comment) throw new Error(copy.commentRequired);
      const updated = await rejectModelVersion(version.id, comment);
      setVersions((current) => ({ ...current, [model.id]: (current[model.id] || []).map((item) => item.id === updated.id ? updated : item) }));
      },
    });
  };

  const submitDeployment = async () => {
    if (!projectId) return;
    try {
      const values = await deploymentForm.validateFields();
      const created = await createDeployment(projectId, {
        name: values.name.trim(), model_version_id: values.model_version_id,
      });
      setDeployments((current) => [created, ...current]);
      setDeploymentOpen(false);
      deploymentForm.resetFields();
    } catch (cause) {
      if (!(cause as { errorFields?: unknown }).errorFields) message.error(formatApiError(cause, copy.commandFailed));
    }
  };

  const operate = async (deployment: InferenceDeployment, action: "start" | "stop") => {
    setBusyId(deployment.id);
    try {
      const updated = action === "start"
        ? await startDeployment(deployment.id)
        : await stopDeployment(deployment.id);
      setDeployments((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (cause) {
      message.error(formatApiError(cause, copy.runtimeFailed));
    } finally {
      setBusyId(undefined);
    }
  };

  const confirmDeleteModel = (model: RegisteredModel) => {
    const label = copy.deleteRegisteredModel || `${t.common.delete} registered model`;
    Modal.confirm({
      title: `${label} ${model.name}?`,
      okText: t.common.delete,
      okType: "danger",
      cancelText: t.common.cancel,
      onOk: async () => {
        setBusyId(model.id);
        try {
          await deleteRegisteredModel(model.id);
          setModels((current) => current.filter((item) => item.id !== model.id));
          setVersions((current) => {
            const next = { ...current };
            delete next[model.id];
            return next;
          });
          setVersionModel((current) => current?.id === model.id ? undefined : current);
          message.success(t.common.success);
        } catch (cause) {
          message.error(formatApiError(cause, copy.commandFailed));
        } finally {
          setBusyId(undefined);
        }
      },
    });
  };

  const confirmDeleteDeployment = (deployment: InferenceDeployment) => {
    const label = copy.deleteDeployment || `${t.common.delete} deployment`;
    Modal.confirm({
      title: `${label} ${deployment.name}?`,
      okText: t.common.delete,
      okType: "danger",
      cancelText: t.common.cancel,
      onOk: async () => {
        setBusyId(deployment.id);
        try {
          await deleteDeployment(deployment.id);
          setDeployments((current) => current.filter((item) => item.id !== deployment.id));
          setTestDeployment((current) => current?.id === deployment.id ? undefined : current);
          message.success(t.common.success);
        } catch (cause) {
          message.error(formatApiError(cause, copy.commandFailed));
        } finally {
          setBusyId(undefined);
        }
      },
    });
  };

  const submitPrediction = async () => {
    if (!testDeployment) return;
    try {
      const values = await predictionForm.validateFields();
      const parsed = JSON.parse(values.records) as unknown;
      if (!Array.isArray(parsed) || parsed.length === 0 || parsed.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
        throw new Error(copy.invalidRecords);
      }
      setPrediction(await predictDeployment(testDeployment.id, parsed as InferenceRecord[]));
    } catch (cause) {
      message.error(formatApiError(cause, copy.runtimeFailed));
    }
  };

  const modelColumns = [
    { title: copy.name, dataIndex: "name", key: "name", render: (value: string, row: RegisteredModel) => <Space direction="vertical" size={0}><Text strong>{value}</Text><Text type="secondary">{row.description}</Text></Space> },
    { title: copy.latestVersion, dataIndex: "latest_version", key: "latest_version", width: 140, render: (value: number | null) => value ? `v${value}` : "-" },
    { title: copy.status, dataIndex: "latest_approval_status", key: "status", width: 140, render: (value: string | null) => value ? <Tag color={statusColor(value)}>{statusLabel(value)}</Tag> : "-" },
    { title: t.model.actions, key: "actions", width: 300, render: (_: unknown, row: RegisteredModel) => <Space wrap>
      <Button icon={<EyeOutlined />} aria-label={`${copy.versions} ${row.name}`} onClick={() => setVersionModel(row)}>{copy.versions}</Button>
      {canRegister && <Button icon={<PlusOutlined />} aria-label={`${copy.registerVersion} ${row.name}`} onClick={() => setRegisterModel(row)}>{copy.registerVersion}</Button>}
      {canRegister && <Tooltip title={`${copy.deleteRegisteredModel || `${t.common.delete} registered model`} ${row.name}`}><Button danger type="text" icon={<DeleteOutlined />} loading={busyId === row.id} aria-label={`${copy.deleteRegisteredModel || `${t.common.delete} registered model`} ${row.name}`} onClick={() => confirmDeleteModel(row)} /></Tooltip>}
    </Space> },
  ];

  const deploymentColumns = [
    { title: copy.name, dataIndex: "name", key: "name", render: (value: string, row: InferenceDeployment) => <Space direction="vertical" size={0}><Text strong>{value}</Text>{row.last_error_code && <Text type="danger">{row.last_error_code}</Text>}</Space> },
    { title: copy.desiredState, dataIndex: "desired_state", key: "desired", width: 120, render: (value: string) => <Tag>{statusLabel(value)}</Tag> },
    { title: copy.observedState, dataIndex: "observed_state", key: "observed", width: 150, render: (value: string) => <Space direction="vertical" size={2}><Tag color={statusColor(value)}>{statusLabel(value)}</Tag>{["starting", "stopping"].includes(value) && <Progress percent={50} showInfo={false} size="small" />}</Space> },
    { title: t.model.actions, key: "actions", width: 300, render: (_: unknown, row: InferenceDeployment) => <Space wrap>
      {canOperate && row.desired_state === "stopped" && <Button icon={<PlayCircleOutlined />} loading={busyId === row.id} aria-label={`${copy.start} ${row.name}`} onClick={() => void operate(row, "start")}>{copy.start}</Button>}
      {canOperate && row.desired_state === "running" && <Button icon={<StopOutlined />} loading={busyId === row.id} aria-label={`${copy.stop} ${row.name}`} onClick={() => void operate(row, "stop")}>{copy.stop}</Button>}
      {canOperate && <Button icon={<CloudServerOutlined />} aria-label={`${copy.onlineTest} ${row.name}`} disabled={row.observed_state !== "running"} onClick={() => {
        const version = Object.values(versions).flat().find((item) => item.id === row.model_version_id);
        const record = Object.fromEntries((version?.feature_schema || []).map((field) => [field.name, 0]));
        setTestDeployment(row);
        setPrediction(undefined);
        predictionForm.setFieldValue("records", JSON.stringify([record], null, 2));
      }}>{copy.onlineTest}</Button>}
      {canRegister && <Tooltip title={`${copy.deleteDeployment || `${t.common.delete} deployment`} ${row.name}`}><Button danger type="text" icon={<DeleteOutlined />} loading={busyId === row.id} disabled={row.desired_state !== "stopped" || row.observed_state !== "stopped"} aria-label={`${copy.deleteDeployment || `${t.common.delete} deployment`} ${row.name}`} onClick={() => confirmDeleteDeployment(row)} /></Tooltip>}
    </Space> },
  ];

  const qualityModelColumns = [
    { title: "模型", dataIndex: "name", key: "name", render: (value: string, row: QualityModel) => <Space direction="vertical" size={0}><Text strong>{value}</Text><Text type="secondary">{row.backbone || row.framework || "spot_weld_quality"}</Text></Space> },
    { title: "状态", dataIndex: "status", key: "status", width: 120, render: (value: string | undefined) => value ? <Tag color={statusColor(value)}>{statusLabel(value)}</Tag> : "-" },
    { title: "指标", key: "metrics", width: 180, render: (_: unknown, row: QualityModel) => <Text type="secondary">{Object.entries(row.metrics || {}).map(([name, value]) => `${name}: ${value == null ? "-" : Number(value).toFixed(4)}`).join(" · ") || "-"}</Text> },
    { title: "训练血缘", key: "lineage", render: (_: unknown, row: QualityModel) => <Space size={[4, 4]} wrap>{["quality_run_id", "label_snapshot_id", "feature_version", "rule_set_version"].map((key) => row.params?.[key] ? <Tag key={key}>{key}: {row.params[key]}</Tag> : null)}</Space> },
  ];

  return <AppLayout>
    <section className="page-shell model-library-page fade-in">
      <Space direction="vertical" size={20} style={{ width: "100%" }}>
        <div className="page-header page-header--stacked">
          <div className="page-header-copy">
            <Title level={3} className="page-title">{copy.title}</Title>
          </div>
          <Select aria-label={copy.project} placeholder={copy.selectProject} value={projectId} onChange={setProjectId} style={{ width: "min(420px, 100%)" }} options={projects.map((item) => ({ value: item.id, label: `${item.name} (${statusLabel(item.project_role)})` }))} />
        </div>
        {!projectId ? <Empty description={copy.selectHint} /> : <>
          {error && <Alert type="error" showIcon message={error} action={<Button icon={<ReloadOutlined />} onClick={() => void loadProject(projectId)}>{t.common.refresh}</Button>} />}
          <Tabs className="model-library-tabs" activeKey={tab} onChange={setTab} items={[
            { key: "models", label: copy.models, children: <div className="table-surface table-surface--padded"><Space direction="vertical" size={12} style={{ width: "100%" }}>
              {canRegister && <Button type="primary" icon={<PlusOutlined />} aria-label={copy.register} onClick={() => setModelOpen(true)}>{copy.register}</Button>}
              <Table rowKey="id" loading={loading} dataSource={models} columns={modelColumns} locale={{ emptyText: <Empty description={copy.emptyModels} /> }} scroll={{ x: 760 }} pagination={false} />
            </Space></div> },
            { key: "deployments", label: copy.deployments, children: <div className="table-surface table-surface--padded"><Space direction="vertical" size={12} style={{ width: "100%" }}>
              {canRegister && <Button type="primary" icon={<PlusOutlined />} aria-label={copy.createDeployment} onClick={() => setDeploymentOpen(true)}>{copy.createDeployment}</Button>}
              <Table rowKey="id" loading={loading} dataSource={deployments} columns={deploymentColumns} locale={{ emptyText: <Empty description={copy.emptyDeployments} /> }} scroll={{ x: 800 }} pagination={false} />
            </Space></div> },
            { key: "quality-models", label: "质量模型", children: <div className="table-surface table-surface--padded"><Table rowKey="id" loading={loading} dataSource={qualityModels} columns={qualityModelColumns} locale={{ emptyText: <Empty description="暂无质量模型" /> }} scroll={{ x: 860 }} pagination={false} /></div> },
          ]} />
        </>}
      </Space>
    </section>

    <Modal title={copy.registerVersion} open={Boolean(registerModel)} onCancel={() => setRegisterModel(undefined)} onOk={() => void submitVersion()} okText={copy.registerVersion} okButtonProps={{ "aria-label": copy.registerVersion }}>
      <Select aria-label={copy.sourceKind} value={registerSource} onChange={setRegisterSource} style={{ width: "100%", marginBottom: 16 }} options={[{ value: "platform_joblib", label: copy.platformSource }, { value: "onnx_artifact", label: copy.onnxSource }]} />
      <Form form={registerForm} layout="vertical">
        {registerSource === "platform_joblib" ? <Form.Item name="source_model_library_id" label={copy.sourceLibraryId} rules={[{ required: true }]}><Input /></Form.Item> : <>
          <Form.Item name="onnx_file" label={copy.onnxFile} valuePropName="fileList" getValueFromEvent={(event) => event?.fileList} rules={[{ required: true }]}><Upload beforeUpload={() => false} maxCount={1} accept=".onnx"><Button>{copy.selectOnnxFile}</Button></Upload></Form.Item>
          <Form.Item name="feature_schema" label={copy.featureSchema} rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="output_schema" label={copy.outputSchema} rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
        </>}
      </Form>
    </Modal>
    <Modal title={copy.register} open={modelOpen} onCancel={() => setModelOpen(false)} onOk={() => void submitModel()} okText={t.common.create} okButtonProps={{ "aria-label": t.common.create }}>
      <Form form={modelForm} layout="vertical">
        <Form.Item name="name" label={copy.name} rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="description" label={copy.description}><Input.TextArea rows={3} /></Form.Item>
      </Form>
    </Modal>
    <Drawer title={versionModel ? `${versionModel.name} ${copy.versions}` : copy.versions} open={Boolean(versionModel)} onClose={() => setVersionModel(undefined)} width={680}>
      <Table rowKey="id" pagination={false} dataSource={versionModel ? versions[versionModel.id] || [] : []} columns={[
        { title: copy.version, dataIndex: "version_number", render: (value: number) => `v${value}` },
        { title: copy.status, dataIndex: "approval_status", render: (value: string) => <Tag color={statusColor(value)}>{statusLabel(value)}</Tag> },
        { title: copy.framework, dataIndex: "framework" },
        { title: t.model.actions, render: (_: unknown, row: ModelVersion) => versionModel && canRegister && row.approval_status === "pending" ? <Space><Button icon={<CheckOutlined />} aria-label={`${copy.approve} ${copy.version.toLowerCase()} ${row.version_number}`} onClick={() => void approve(versionModel, row)}>{copy.approve}</Button><Button danger aria-label={`${copy.reject} ${copy.version.toLowerCase()} ${row.version_number}`} onClick={() => reject(versionModel, row)}>{copy.reject}</Button></Space> : null },
      ]} />
    </Drawer>
    <Modal title={copy.createDeployment} open={deploymentOpen} onCancel={() => setDeploymentOpen(false)} onOk={() => void submitDeployment()} okText={t.common.create} okButtonProps={{ "aria-label": t.common.create }}>
      <Form form={deploymentForm} layout="vertical"><Form.Item name="name" label={copy.name} rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="model_version_id" label={copy.version} rules={[{ required: true }]}><Select options={approvedVersions.map(({ model, version }) => ({ value: version.id, label: `${model.name} v${version.version_number}` }))} /></Form.Item></Form>
    </Modal>
    <Drawer title={testDeployment ? `${copy.onlineTest}: ${testDeployment.name}` : copy.onlineTest} open={Boolean(testDeployment)} onClose={() => setTestDeployment(undefined)} width={620} extra={<Button type="primary" aria-label={copy.predict} onClick={() => void submitPrediction()}>{copy.predict}</Button>}>
      <Form form={predictionForm} layout="vertical"><Form.Item name="records" label={copy.recordsJson} rules={[{ required: true }]}><Input.TextArea rows={8} /></Form.Item></Form>
      {prediction && <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label={copy.version}>v{prediction.version_number}</Descriptions.Item>
        <Descriptions.Item label={copy.predictions}><pre>{JSON.stringify(prediction.predictions, null, 2)}</pre></Descriptions.Item>
        {prediction.probabilities && <Descriptions.Item label={copy.probabilities}><pre>{JSON.stringify(prediction.probabilities, null, 2)}</pre></Descriptions.Item>}
        <Descriptions.Item label={copy.duration}>{prediction.duration_ms} ms</Descriptions.Item>
      </Descriptions>}
    </Drawer>
  </AppLayout>;
}
