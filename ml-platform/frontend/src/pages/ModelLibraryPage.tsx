import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Descriptions, Drawer, Empty, Form, Input, Modal, Progress,
  Select, Space, Table, Tabs, Tag, Typography, Upload, message,
} from "antd";
import {
  CheckOutlined, CloudServerOutlined, DownloadOutlined, EyeOutlined, KeyOutlined,
  PauseCircleOutlined, PlayCircleOutlined, PlusOutlined, ReloadOutlined,
  RollbackOutlined, StopOutlined, SyncOutlined, DeleteOutlined,
} from "@ant-design/icons";
import apiClient, { formatApiError } from "../api/client";
import {
  approveModelVersion, createDeployment, createRegisteredModel, deleteRegisteredModel, deleteDeployment,
  createInferenceApiKey, createRollout, type CreatedInferenceApiKey,
  type DeploymentRollout, type InferenceApiKey, type InferenceDeployment,
  type InferenceMetricPage, type InferenceRecord, type InferenceRequestLogPage,
  listDeployments, listInferenceApiKeys, listInferenceMetricWindow, listInferenceRequestLogs,
  getModelCard, listModelVersions, listRegisteredModels, listRollouts, type ModelCard, type ModelVersion,
  predictDeployment, type PredictionResult, type ProjectOption,
  type RegisteredModel, registerOnnxVersion, registerPlatformVersion, rejectModelVersion,
  rollbackRollout, rotateInferenceApiKey, startDeployment, stopDeployment,
  pauseRollout, resumeRollout, revokeInferenceApiKey, updateModelCardGuidance,
  exportModelCard, uploadOnnxArtifact,
} from "../api/modelRegistry";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text, Title } = Typography;

export default function ModelLibraryPage() {
  const { t } = useI18n();
  const copy = t.modelRegistry;
  const production = copy.production;
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState<string>();
  const [tab, setTab] = useState("models");
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [deployments, setDeployments] = useState<InferenceDeployment[]>([]);
  const [versions, setVersions] = useState<Record<string, ModelVersion[]>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [registerModel, setRegisterModel] = useState<RegisteredModel>();
  const [modelOpen, setModelOpen] = useState(false);
  const [versionModel, setVersionModel] = useState<RegisteredModel>();
  const [deploymentOpen, setDeploymentOpen] = useState(false);
  const [testDeployment, setTestDeployment] = useState<InferenceDeployment>();
  const [prediction, setPrediction] = useState<PredictionResult>();
  const [busyId, setBusyId] = useState<string>();
  const [operationsDeployment, setOperationsDeployment] = useState<InferenceDeployment>();
  const [rollouts, setRollouts] = useState<DeploymentRollout[]>([]);
  const [apiKeys, setApiKeys] = useState<InferenceApiKey[]>([]);
  const [metrics, setMetrics] = useState<InferenceMetricPage>();
  const [requestLogs, setRequestLogs] = useState<InferenceRequestLogPage>();
  const [modelCard, setModelCard] = useState<ModelCard>();
  const [modelCardOpen, setModelCardOpen] = useState(false);
  const [operationsLoading, setOperationsLoading] = useState(false);
  const [operationsError, setOperationsError] = useState<string>();
  const [createdKey, setCreatedKey] = useState<CreatedInferenceApiKey>();
  const [guidance, setGuidance] = useState("");
  const [rolloutBusyId, setRolloutBusyId] = useState<string>();
  const [rolloutOpen, setRolloutOpen] = useState(false);
  const [lastLogPage, setLastLogPage] = useState<number>();
  const operationsRequestRef = useRef(0);
  const [registerSource, setRegisterSource] = useState<"platform_joblib" | "onnx_artifact">("platform_joblib");
  const [registerForm] = Form.useForm();
  const [modelForm] = Form.useForm();
  const [deploymentForm] = Form.useForm();
  const [predictionForm] = Form.useForm();
  const [rolloutForm] = Form.useForm();

  const selectedProject = projects.find((item) => item.id === projectId);
  const role = selectedProject?.project_role;
  const canRegister = role === "owner" || role === "editor";
  const canOperate = canRegister || role === "operator";

  const metricWindow = useMemo(() => {
    const until = new Date();
    const since = new Date(until.getTime() - 24 * 60 * 60 * 1000);
    return { since: since.toISOString(), until: until.toISOString() };
  }, [operationsDeployment?.id]);
  const logQuery = useMemo(() => ({ ...metricWindow, page: 1, page_size: 100 }), [metricWindow]);

  useEffect(() => {
    apiClient.get("/projects").then((response) => {
      const items = Array.isArray(response.data) ? response.data : response.data?.items;
      setProjects(Array.isArray(items) ? items : []);
    }).catch((cause) => setError(formatApiError(cause, copy.loadFailed)));
  }, [copy.loadFailed]);

  const loadProject = useCallback(async (selected: string) => {
    setLoading(true);
    setError(undefined);
    try {
      const [modelItems, deploymentItems] = await Promise.all([
        listRegisteredModels(selected), listDeployments(selected),
      ]);
      setModels(modelItems);
      setDeployments(deploymentItems);
      const entries = await Promise.all(modelItems.map(async (model) => [
        model.id, await listModelVersions(model.id),
      ] as const));
      setVersions(Object.fromEntries(entries));
    } catch (cause) {
      setError(formatApiError(cause, copy.loadFailed));
      setModels([]);
      setDeployments([]);
    } finally {
      setLoading(false);
    }
  }, [copy.loadFailed]);

  useEffect(() => {
    if (projectId) void loadProject(projectId);
  }, [loadProject, projectId]);

  const statusLabel = (status: string) => {
    const label = copy[status as keyof typeof copy];
    return typeof label === "string" ? label : status;
  };
  const productionStatusLabel = (status: string) =>
    production.statusLabels[status as keyof typeof production.statusLabels] || statusLabel(status);
  const statusColor = (status: string) => {
    if (["approved", "running", "completed", "stable", "active"].includes(status)) return "success";
    if (["pending", "preloading", "progressing", "paused", "starting", "stopping"].includes(status)) return "processing";
    if (["rejected", "failed", "rolled_back", "revoked"].includes(status)) return "error";
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

  const openOperations = async (deployment: InferenceDeployment) => {
    const requestId = operationsRequestRef.current + 1;
    operationsRequestRef.current = requestId;
    setOperationsDeployment(deployment);
    setOperationsLoading(true);
    setOperationsError(undefined);
    setRollouts([]);
    setApiKeys([]);
    setMetrics(undefined);
    setRequestLogs(undefined);
    setModelCard(undefined);
    setModelCardOpen(false);
    setGuidance("");
    setLastLogPage(undefined);
    const results = await Promise.allSettled([
      listRollouts(deployment.id),
      canRegister ? listInferenceApiKeys(deployment.id) : Promise.resolve({ items: [], total: 0 }),
      listInferenceMetricWindow(deployment.id, metricWindow),
      listInferenceRequestLogs(deployment.id, logQuery),
      getModelCard(deployment.model_version_id),
    ]);
    if (requestId !== operationsRequestRef.current) return;
    const [rolloutResult, keyResult, metricResult, logResult, cardResult] = results;
    if (rolloutResult.status === "fulfilled") setRollouts(rolloutResult.value.items);
    if (keyResult.status === "fulfilled") setApiKeys(keyResult.value.items);
    if (metricResult.status === "fulfilled") setMetrics(metricResult.value);
    if (logResult.status === "fulfilled") {
      setRequestLogs(logResult.value);
      setLastLogPage(logResult.value.items.length < logResult.value.page_size ? logResult.value.page : undefined);
    }
    if (cardResult.status === "fulfilled") {
      setModelCard(cardResult.value);
      setGuidance(cardResult.value.operational_guidance || "");
    }
    const failed = results.find((result) => result.status === "rejected");
    if (failed && failed.status === "rejected") setOperationsError(formatApiError(failed.reason, copy.commandFailed));
    setOperationsLoading(false);
  };

  const loadRequestLogPage = async (page: number) => {
    if (!operationsDeployment) return;
    const requestId = operationsRequestRef.current;
    try {
      const next = await listInferenceRequestLogs(operationsDeployment.id, { ...logQuery, page });
      if (requestId !== operationsRequestRef.current) return;
      if (page > 1 && next.items.length === 0) {
        setLastLogPage(page - 1);
        return;
      }
      setRequestLogs(next);
      setLastLogPage(next.items.length < next.page_size ? next.page : undefined);
    } catch (cause) {
      if (requestId === operationsRequestRef.current) message.error(formatApiError(cause, copy.commandFailed));
    }
  };

  const operateRollout = async (rollout: DeploymentRollout, action: "pause" | "resume" | "rollback") => {
    if (!operationsDeployment) return;
    setRolloutBusyId(rollout.id);
    try {
      const updated = action === "pause"
        ? await pauseRollout(operationsDeployment.id, rollout.id, rollout.lock_version)
        : action === "resume"
          ? await resumeRollout(operationsDeployment.id, rollout.id, rollout.lock_version)
          : await rollbackRollout(operationsDeployment.id, rollout.id, rollout.lock_version);
      setRollouts((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (cause) {
      message.error(formatApiError(cause, copy.commandFailed));
    } finally {
      setRolloutBusyId(undefined);
    }
  };

  const confirmRollback = (rollout: DeploymentRollout) => {
    Modal.confirm({
      title: production.rollbackConfirmation,
      content: rollout.last_error_code || production.releaseState,
      okText: production.confirmRollback,
      cancelText: t.common.cancel,
      okButtonProps: { "aria-label": production.confirmRollback },
      onOk: () => operateRollout(rollout, "rollback"),
    });
  };

  const confirmRolloutCommand = (rollout: DeploymentRollout, action: "pause" | "resume") => {
    const isPause = action === "pause";
    Modal.confirm({
      title: isPause ? production.pauseConfirmation : production.resumeConfirmation,
      okText: isPause ? production.confirmPause : production.confirmResume,
      cancelText: t.common.cancel,
      okButtonProps: { "aria-label": isPause ? production.confirmPause : production.confirmResume },
      onOk: () => operateRollout(rollout, action),
    });
  };

  const handleCreateApiKey = async () => {
    if (!operationsDeployment) return;
    const requestId = operationsRequestRef.current;
    try {
      const created = await createInferenceApiKey(operationsDeployment.id, { scopes: ["inference.predict"] });
      if (requestId !== operationsRequestRef.current) return;
      const { plaintext: _plaintext, ...metadata } = created;
      setApiKeys((current) => [metadata, ...current]);
      setCreatedKey(created);
    } catch (cause) {
      message.error(formatApiError(cause, copy.commandFailed));
    }
  };

  const handleRotateApiKey = async (key: InferenceApiKey) => {
    if (!operationsDeployment) return;
    const requestId = operationsRequestRef.current;
    try {
      const created = await rotateInferenceApiKey(key.id);
      const { plaintext: _plaintext, ...metadata } = created;
      if (requestId !== operationsRequestRef.current) return;
      setCreatedKey(created);
      setApiKeys((current) => [
        metadata,
        ...current.map((item) => item.id === key.id ? { ...item, revoked_at: new Date().toISOString() } : item),
      ]);
      const refreshed = await listInferenceApiKeys(operationsDeployment.id);
      if (requestId !== operationsRequestRef.current) return;
      setApiKeys(refreshed.items);
    } catch (cause) {
      if (requestId === operationsRequestRef.current) {
        message.error(formatApiError(cause, copy.commandFailed));
      }
    }
  };

  const handleRevokeApiKey = async (key: InferenceApiKey) => {
    try {
      const updated = await revokeInferenceApiKey(key.id);
      setApiKeys((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (cause) {
      message.error(formatApiError(cause, copy.commandFailed));
    }
  };

  const submitRollout = async () => {
    if (!operationsDeployment) return;
    try {
      const values = await rolloutForm.validateFields();
      const created = await createRollout(operationsDeployment.id, {
        strategy: values.strategy,
        targets: [{ model_version_id: values.target_version_id, weight_bps: Number(values.target_weight) }],
      });
      setRollouts((current) => [created, ...current]);
      setRolloutOpen(false);
      rolloutForm.resetFields();
    } catch (cause) {
      if (!(cause as { errorFields?: unknown }).errorFields) message.error(formatApiError(cause, copy.commandFailed));
    }
  };

  const saveGuidance = async () => {
    if (!modelCard || !canRegister) return;
    try {
      const updated = await updateModelCardGuidance(modelCard.id, guidance);
      setModelCard(updated);
      setGuidance(updated.operational_guidance || "");
      message.success(production.guidanceUpdated);
    } catch (cause) {
      message.error(formatApiError(cause, copy.commandFailed));
    }
  };

  const downloadCard = async () => {
    if (!modelCard) return;
    try {
      const exported = await exportModelCard(modelCard.id);
      const content = typeof exported.content === "string" ? exported.content : JSON.stringify(exported, null, 2);
      if (typeof URL.createObjectURL === "function") {
        const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `model-card-${modelCard.model_version_id}.json`;
        link.click();
        URL.revokeObjectURL(url);
      }
      message.success(production.cardExported);
    } catch (cause) {
      message.error(formatApiError(cause, copy.commandFailed));
    }
  };

  const confirmDeleteModel = (model: RegisteredModel) => {
    Modal.confirm({
      title: "删除注册模型",
      content: `确认删除注册模型“${model.name}”？该操作不可撤销。`,
      okText: "删除", okButtonProps: { danger: true, "aria-label": `删除注册模型 ${model.name}` },
      cancelText: t.common.cancel,
      onOk: async () => {
        try {
          await deleteRegisteredModel(model.id);
          setModels((current) => current.filter((item) => item.id !== model.id));
          setVersions((current) => { const next = { ...current }; delete next[model.id]; return next; });
          message.success("注册模型已删除");
        } catch (cause) { message.error(formatApiError(cause, copy.commandFailed)); }
      },
    });
  };

  const confirmDeleteDeployment = (deployment: InferenceDeployment) => {
    Modal.confirm({
      title: "删除推理部署",
      content: `确认删除推理部署“${deployment.name}”？该操作不可撤销。`,
      okText: "删除", okButtonProps: { danger: true, "aria-label": `删除推理部署 ${deployment.name}` },
      cancelText: t.common.cancel,
      onOk: async () => {
        try {
          await deleteDeployment(deployment.id);
          setDeployments((current) => current.filter((item) => item.id !== deployment.id));
          if (operationsDeployment?.id === deployment.id) setOperationsDeployment(undefined);
          message.success("推理部署已删除");
        } catch (cause) { message.error(formatApiError(cause, copy.commandFailed)); }
      },
    });
  };

  const modelColumns = [
    { title: copy.name, dataIndex: "name", key: "name", render: (value: string, row: RegisteredModel) => <Space direction="vertical" size={0}><Text strong>{value}</Text><Text type="secondary">{row.description}</Text></Space> },
    { title: copy.latestVersion, dataIndex: "latest_version", key: "latest_version", width: 140, render: (value: number | null) => value ? `v${value}` : "-" },
    { title: copy.status, dataIndex: "latest_approval_status", key: "status", width: 140, render: (value: string | null) => value ? <Tag color={statusColor(value)}>{statusLabel(value)}</Tag> : "-" },
    { title: t.model.actions, key: "actions", width: 340, render: (_: unknown, row: RegisteredModel) => <Space wrap>
      <Button icon={<EyeOutlined />} aria-label={`${copy.versions} ${row.name}`} onClick={() => setVersionModel(row)}>{copy.versions}</Button>
      {canRegister && <Button icon={<PlusOutlined />} aria-label={`${copy.registerVersion} ${row.name}`} onClick={() => setRegisterModel(row)}>{copy.registerVersion}</Button>}
      {canRegister && <Button danger icon={<DeleteOutlined />} aria-label={`删除注册模型 ${row.name}`} onClick={() => confirmDeleteModel(row)}>删除</Button>}
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
      <Button icon={<EyeOutlined />} aria-label={`${production.releaseOperations} ${row.name}`} onClick={() => void openOperations(row)}>{production.releaseOperations}</Button>
      {canRegister && <Button danger icon={<DeleteOutlined />} aria-label={`删除推理部署 ${row.name}`} onClick={() => confirmDeleteDeployment(row)}>删除</Button>}
    </Space> },
  ];

  const isApiKeyExpired = (key: InferenceApiKey) => {
    if (!key.expires_at) return false;
    const expiresAt = new Date(key.expires_at).getTime();
    return Number.isFinite(expiresAt) && expiresAt <= Date.now();
  };

  const rolloutColumns = [
    { title: production.releaseState, dataIndex: "state", key: "state", width: 170, render: (value: string, row: DeploymentRollout) => <Space direction="vertical" size={0}><Tag color={statusColor(value)}>{productionStatusLabel(value)}</Tag>{["pending", "preloading", "progressing", "paused"].includes(value) && <Progress percent={Math.min(100, Math.max(0, row.current_step / 100))} size="small" showInfo />}{row.last_error_code && <Text type="danger">{row.last_error_code}</Text>}</Space> },
    { title: production.targetWeights, key: "targets", render: (_: unknown, row: DeploymentRollout) => row.targets?.map((target) => `${target.model_version_id}: ${target.weight_bps / 100}%`).join(", ") || "-" },
    { title: t.model.actions, key: "actions", width: 300, render: (_: unknown, row: DeploymentRollout) => <Space wrap>
      {canOperate && ["pending", "preloading", "progressing"].includes(row.state) && <Button icon={<PauseCircleOutlined />} loading={rolloutBusyId === row.id} aria-label={`${production.pause} ${production.release} ${row.id}`} onClick={() => confirmRolloutCommand(row, "pause")}>{production.pause}</Button>}
      {canOperate && row.state === "paused" && <Button icon={<PlayCircleOutlined />} loading={rolloutBusyId === row.id} aria-label={`${production.resume} ${production.release} ${row.id}`} onClick={() => confirmRolloutCommand(row, "resume")}>{production.resume}</Button>}
      {canOperate && ["pending", "preloading", "progressing", "paused", "completed", "failed"].includes(row.state) && <Button danger icon={<RollbackOutlined />} loading={rolloutBusyId === row.id} aria-label={`${production.rollback} ${production.release} ${row.id}`} onClick={() => confirmRollback(row)}>{production.rollback}</Button>}
    </Space> },
  ];

  const keyColumns = [
    { title: production.keyPrefix, dataIndex: "prefix", key: "prefix" },
    { title: production.keyStatus, key: "status", render: (_: unknown, row: InferenceApiKey) => row.revoked_at ? <Tag color="error">{production.revoked}</Tag> : isApiKeyExpired(row) ? <Tag color="warning">{production.expired}</Tag> : <Tag color="success">{production.active}</Tag> },
    { title: t.model.actions, key: "actions", width: 250, render: (_: unknown, row: InferenceApiKey) => canRegister && !row.revoked_at ? <Space wrap><Button icon={<SyncOutlined />} disabled={isApiKeyExpired(row)} aria-label={`${production.rotateApiKey} ${row.prefix}`} onClick={() => void handleRotateApiKey(row)}>{production.rotateApiKey}</Button><Button danger icon={<StopOutlined />} aria-label={`${production.revokeApiKey} ${row.prefix}`} onClick={() => void handleRevokeApiKey(row)}>{production.revokeApiKey}</Button></Space> : null },
  ];

  const logColumns = [
    { title: production.logStatus, dataIndex: "status", key: "status", render: (value: string) => <Tag color={statusColor(value)}>{productionStatusLabel(value)}</Tag> },
    { title: production.logDuration, dataIndex: "duration_ms", key: "duration" },
    { title: production.logBatch, dataIndex: "batch_size", key: "batch" },
    { title: production.logError, dataIndex: "error_code", key: "error", render: (value: string | null) => value || "-" },
    { title: production.logOccurred, dataIndex: "occurred_at", key: "occurred" },
  ];

  return <AppLayout>
    <section style={{ maxWidth: 1440, margin: "0 auto" }}>
      <Space direction="vertical" size={20} style={{ width: "100%" }}>
        <div>
          <Title level={3} style={{ marginBottom: 12 }}>{copy.title}</Title>
          <Select aria-label={copy.project} placeholder={copy.selectProject} value={projectId} onChange={setProjectId} style={{ width: "min(420px, 100%)" }} options={projects.map((item) => ({ value: item.id, label: `${item.name} (${statusLabel(item.project_role)})` }))} />
        </div>
        {!projectId ? <Empty description={copy.selectHint} /> : <>
          {error && <Alert type="error" showIcon message={error} action={<Button icon={<ReloadOutlined />} onClick={() => void loadProject(projectId)}>{t.common.refresh}</Button>} />}
          <Tabs activeKey={tab} onChange={setTab} items={[
            { key: "models", label: copy.models, children: <Space direction="vertical" size={12} style={{ width: "100%" }}>
              {canRegister && <Button type="primary" icon={<PlusOutlined />} aria-label={copy.register} onClick={() => setModelOpen(true)}>{copy.register}</Button>}
              <Table rowKey="id" loading={loading} dataSource={models} columns={modelColumns} locale={{ emptyText: <Empty description={copy.emptyModels} /> }} scroll={{ x: 760 }} pagination={false} />
            </Space> },
            { key: "deployments", label: copy.deployments, children: <Space direction="vertical" size={12} style={{ width: "100%" }}>
              {canRegister && <Button type="primary" icon={<PlusOutlined />} aria-label={copy.createDeployment} onClick={() => setDeploymentOpen(true)}>{copy.createDeployment}</Button>}
              <Table rowKey="id" loading={loading} dataSource={deployments} columns={deploymentColumns} locale={{ emptyText: <Empty description={copy.emptyDeployments} /> }} scroll={{ x: 800 }} pagination={false} />
            </Space> },
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
    <Drawer
      title={operationsDeployment ? `${production.releaseOperations}: ${operationsDeployment.name}` : production.releaseOperations}
      open={Boolean(operationsDeployment)}
      onClose={() => {
        operationsRequestRef.current += 1;
        setOperationsDeployment(undefined);
        setModelCardOpen(false);
        setCreatedKey(undefined);
      }}
      width="min(960px, 100%)"
    >
      {operationsError && <Alert type="error" showIcon message={operationsError} style={{ marginBottom: 16 }} />}
      {!canRegister && <Alert type="info" showIcon message={copy.permissionDenied} style={{ marginBottom: 16 }} />}
      <Space direction="vertical" size={20} style={{ width: "100%" }}>
        <section aria-labelledby="release-operations-heading">
          <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
            <Title id="release-operations-heading" level={5} style={{ margin: 0 }}>{production.releases}</Title>
            {canRegister && <Button type="primary" icon={<PlusOutlined />} aria-label={production.createRollout} onClick={() => setRolloutOpen(true)}>{production.createRollout}</Button>}
          </Space>
          <div style={{ overflowX: "auto" }}>
            <Table
              rowKey="id"
              loading={operationsLoading}
              dataSource={rollouts}
              columns={rolloutColumns}
              pagination={false}
              scroll={{ x: 700 }}
              locale={{ emptyText: <Empty description={production.emptyRollouts} /> }}
            />
          </div>
        </section>

        <section aria-labelledby="api-keys-heading">
          <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
            <Title id="api-keys-heading" level={5} style={{ margin: 0 }}><KeyOutlined /> {production.apiKeys}</Title>
            {canRegister && <Button icon={<KeyOutlined />} aria-label={production.createApiKey} onClick={() => void handleCreateApiKey()}>{production.createApiKey}</Button>}
          </Space>
          <div style={{ overflowX: "auto" }}>
            <Table
              rowKey="id"
              loading={operationsLoading}
              dataSource={apiKeys}
              columns={keyColumns}
              pagination={false}
              scroll={{ x: 600 }}
              locale={{ emptyText: <Empty description={canRegister ? production.emptyApiKeys : copy.permissionDenied} /> }}
            />
          </div>
        </section>

        <section aria-labelledby="metrics-heading">
          <Title id="metrics-heading" level={5}>{production.metrics} <Text type="secondary">{production.last24Hours}</Text></Title>
          {!metrics ? <Table loading={operationsLoading} dataSource={[]} columns={[]} pagination={false} /> : metrics.items.length === 0 ? <Empty description={production.emptyMetrics} /> : <Descriptions bordered size="small" column={{ xs: 1, sm: 3 }}>
            <Descriptions.Item label={production.throughput}>{metrics.summary.request_count}</Descriptions.Item>
            <Descriptions.Item label={production.errorRate}>{metrics.summary.request_count ? `${((metrics.summary.error_count / metrics.summary.request_count) * 100).toFixed(2)}%` : "0%"}</Descriptions.Item>
            <Descriptions.Item label={production.latency}>{metrics.summary.p95_latency_ms ?? metrics.summary.average_latency_ms ?? 0} ms</Descriptions.Item>
          </Descriptions>}
        </section>

        <section aria-labelledby="request-logs-heading">
          <Title id="request-logs-heading" level={5}>{production.requestLogs}</Title>
          <div style={{ overflowX: "auto" }}>
            <Table
              rowKey="id"
              loading={operationsLoading}
              dataSource={requestLogs?.items || []}
              columns={logColumns}
              pagination={requestLogs ? {
                current: requestLogs.page,
                pageSize: requestLogs.page_size,
                pageSizeOptions: ["25", "50", "100"],
                showSizeChanger: false,
                total: (lastLogPage ?? requestLogs.page + 1) * requestLogs.page_size,
                onChange: (page) => {
                  void loadRequestLogPage(page);
                },
              } : false}
              scroll={{ x: 700 }}
              locale={{ emptyText: <Empty description={production.emptyRequestLogs} /> }}
            />
          </div>
        </section>

        <section aria-labelledby="model-card-heading">
          <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
            <Title id="model-card-heading" level={5}>{production.modelCard}</Title>
            <Button icon={<EyeOutlined />} aria-label={production.openModelCard} disabled={!modelCard} onClick={() => setModelCardOpen(true)}>{production.modelCard}</Button>
          </Space>
          {!modelCard && <Empty description={operationsLoading ? t.common.loading : production.emptyModelCard} />}
        </section>
      </Space>
    </Drawer>
    <Drawer
      title={production.modelCard}
      aria-label={production.modelCard}
      open={modelCardOpen}
      onClose={() => setModelCardOpen(false)}
      width="min(680px, 100%)"
    >
      {!modelCard ? <Empty description={production.emptyModelCard} /> : <Space direction="vertical" style={{ width: "100%" }}>
        <Button icon={<DownloadOutlined />} aria-label={production.exportModelCard} onClick={() => void downloadCard()}>{production.exportModelCard}</Button>
        <Input.TextArea aria-label={production.operationalGuidance} value={guidance} onChange={(event) => setGuidance(event.target.value)} rows={5} disabled={!canRegister} />
        {canRegister && <Button type="primary" aria-label={production.saveGuidance} onClick={() => void saveGuidance()}>{production.saveGuidance}</Button>}
      </Space>}
    </Drawer>
    {createdKey && <Modal
      title={production.keyCreated}
      open
      destroyOnHidden
      onCancel={() => setCreatedKey(undefined)}
      footer={<Button icon={<KeyOutlined />} aria-label={production.closeCreatedKey} onClick={() => setCreatedKey(undefined)}>{t.common.close}</Button>}
    >
      <Input.Password aria-label={production.keyPlaintext} readOnly value={createdKey.plaintext} />
    </Modal>}
    <Modal title={production.createRollout} open={rolloutOpen} onCancel={() => setRolloutOpen(false)} onOk={() => void submitRollout()} okText={t.common.create} okButtonProps={{ "aria-label": t.common.create }}>
      <Form form={rolloutForm} layout="vertical">
        <Form.Item name="strategy" label={production.strategy} initialValue="canary" rules={[{ required: true }]}><Select options={[{ value: "immediate", label: production.immediate }, { value: "canary", label: production.canary }, { value: "rolling", label: production.rolling }]} /></Form.Item>
        <Form.Item name="target_version_id" label={production.targetVersion} rules={[{ required: true }]}><Select options={approvedVersions.map(({ model, version }) => ({ value: version.id, label: `${model.name} v${version.version_number}` }))} /></Form.Item>
        <Form.Item name="target_weight" label={production.targetWeight} initialValue={10000} rules={[{ required: true }]}><Input type="number" min={0} max={10000} /></Form.Item>
      </Form>
    </Modal>
  </AppLayout>;
}
