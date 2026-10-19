import { useEffect, useCallback, useState, useRef } from "react";
import { useParams } from "react-router-dom";
import { App as AntApp, Button, Dropdown, Form, Layout, Radio, Space, Divider, Input, Modal, Drawer, List, Tag, Tooltip, Typography } from "antd";
import { DownOutlined, EllipsisOutlined, PlayCircleOutlined, SaveOutlined, ArrowLeftOutlined, EditOutlined, PauseCircleOutlined, DeleteOutlined, CloudUploadOutlined, HistoryOutlined, ApiOutlined, CopyOutlined } from "@ant-design/icons";
import { ReactFlowProvider } from "reactflow";
import { useNavigate } from "react-router-dom";
import apiClient from "../api/client";
import { formatApiError } from "../api/client";
import OperatorPanel from "../components/workspace/OperatorPanel";
import WorkflowCanvas from "../components/workspace/WorkflowCanvas";
import NodeConfigPanel, { NodeResultPanel } from "../components/workspace/NodeConfigPanel";
import ExecutionProgress from "../components/workspace/ExecutionProgress";
import { normalizeNodeError, normalizeWorkflowHandle, useWorkflowStore } from "../stores/workflowStore";
import type { NodeRunStatus, WorkflowRunStatus } from "../stores/workflowStore";
import { deleteWorkflowVersion, listWorkflowVersions, publishWorkflow, publishWorkflowApi, restoreWorkflowVersion, WorkflowVersionSummary } from "../api/workflowVersions";
import { useI18n } from "../i18n";
import { formatLocalTime } from "../utils/time";

const { Sider, Content } = Layout;
const { Text } = Typography;

export function resolvePort(handleId: string, portList: {name:string}[]): string {
  if (!handleId) return "";
  const logicalHandle = normalizeWorkflowHandle(handleId) || "";
  // Already a port name (e.g., "data", "left") — pass through
  if (!/^(in|out)-\d+$/.test(logicalHandle)) return logicalHandle;
  const idx = parseInt(logicalHandle.replace(/^(in|out)-/, ""), 10);
  return (!isNaN(idx) && idx < portList.length) ? portList[idx].name : logicalHandle;
}

export function hydrateWorkflowEdges(edges: any[], nodes: any[] = []) {
  const nodesById = new Map(nodes.map((node) => [String(node.id), node]));
  return edges.reduce<any[]>((hydrated, edge: any) => {
    const source = String(edge.source_node_id ?? edge.source);
    const target = String(edge.target_node_id ?? edge.target);
    const normalized = {
      id: String(edge.id),
      source,
      target,
      sourceHandle: resolvePort(
        edge.source_port || edge.sourceHandle || "out-0",
        nodesById.get(source)?.data?.outputs || [],
      ) || "out-0",
      targetHandle: resolvePort(
        edge.target_port || edge.targetHandle || "in-0",
        nodesById.get(target)?.data?.inputs || [],
      ) || "in-0",
    };
    const survivors = hydrated.filter((existing) => (
      !(
        existing.source === normalized.source &&
        existing.sourceHandle === normalized.sourceHandle
      ) && !(
        existing.target === normalized.target &&
        existing.targetHandle === normalized.targetHandle
      )
    ));
    return [...survivors, normalized];
  }, []);
}

export default function WorkspacePage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const text = lang === "zh" ? {
    loadFailed: "工作流加载失败", saved: "已保存", saveFailed: "保存失败，请重试", publishFailed: "发布失败",
    historyFailed: "版本历史加载失败", cancelled: "已请求取消，当前节点结束后停止", cancelFailed: "取消失败",
    restored: "无法恢复运行状态", runFailed: "运行失败", runComplete: "工作流运行完成", runCancelled: "工作流已取消",
    liveClosed: "实时连接已关闭，正在恢复运行状态", deleteFailed: "删除失败，请重试", history: "版本历史",
    noVersions: "暂无已发布版本", restore: "恢复", delete: "删除", operatorPanel: "算子面板", nodeConfig: "节点配置",
    back: "返回", save: "保存", saveAsTemplate: "保存为模板", more: "更多", publish: "发布", version: "版本", run: "运行", stop: "终止",
    confirmDelete: "确认删除", cancel: "取消", deletePrompt: "确定要删除工作流", irreversible: "此操作不可撤销。",
    publishApi: "发布为 API", publishApiSuccess: "已发布为编排 API，可在 API 市场查看", publishApiFailed: "发布为 API 失败",
    tplModalTitle: "保存为模板", tplName: "模板名称", tplScope: "保存范围",
    scopeProject: "仅当前项目", scopeProjectHint: "项目内可见，可复用",
    scopeGlobal: "全平台通用", scopeGlobalHint: "所有项目可见可实例化；仅平台管理员可保存/编辑/删除",
    tplSaved: "已保存为模板", tplSavedGlobal: "已保存为平台通用模板", tplSaveFailed: "保存为模板失败，请重试",
  } : {
    loadFailed: "Failed to load workflow", saved: "Saved", saveFailed: "Save failed. Please retry.", publishFailed: "Publish failed",
    historyFailed: "Failed to load version history", cancelled: "Cancellation requested; the current node will stop safely.", cancelFailed: "Cancellation failed",
    restored: "Unable to recover run status", runFailed: "Workflow run failed", runComplete: "Workflow run completed", runCancelled: "Workflow run cancelled",
    liveClosed: "Live connection closed; recovering run status", deleteFailed: "Delete failed. Please retry.", history: "Version history",
    noVersions: "No published versions", restore: "Restore", delete: "Delete", operatorPanel: "Operator panel", nodeConfig: "Node configuration",
    back: "Back", save: "Save", saveAsTemplate: "Save as Template", more: "More", publish: "Publish", version: "Versions", run: "Run", stop: "Stop",
    confirmDelete: "Confirm deletion", cancel: "Cancel", deletePrompt: "Delete workflow", irreversible: "This action cannot be undone.",
    publishApi: "Publish as API", publishApiSuccess: "Published as an orchestration API — see the API Marketplace", publishApiFailed: "Publish as API failed",
    tplModalTitle: "Save as Template", tplName: "Template name", tplScope: "Scope",
    scopeProject: "This project only", scopeProjectHint: "Reusable inside the current project",
    scopeGlobal: "Platform-wide", scopeGlobalHint: "Visible and instantiable in every project; admins manage global templates",
    tplSaved: "Saved as template", tplSavedGlobal: "Saved as a platform-wide template", tplSaveFailed: "Save as template failed. Please retry.",
  };
  const { workflowId } = useParams<{ workflowId: string }>();
  const navigate = useNavigate();
  const {
    operators, setOperators, setNodes, setEdges, closeNodeResult,
    isRunning, setIsRunning, setNodeStatus, setNodeResult, setNodeError, setNodeProgress, resetExecution,
    currentRunId, setCurrentRunId, setWorkflowStatus,
    reset,
  } = useWorkflowStore();
  const [wfName, setWfName] = useState("");
  const [workflowProjectId, setWorkflowProjectId] = useState<string | undefined>();
  const [editingName, setEditingName] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [tplModalOpen, setTplModalOpen] = useState(false);
  const [tplForm] = Form.useForm();
  const isAdmin = localStorage.getItem("role") === "admin";
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versions, setVersions] = useState<WorkflowVersionSummary[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  // ── Build operator lookup ──
  function getOpMeta() {
    const map: Record<string, any> = {};
    const ops = useWorkflowStore.getState().operators || [];
    for (const op of ops) map[op.id] = op;
    return map;
  }

  const loadWorkflow = () => {
    if (!workflowId) return;
    const meta = getOpMeta();
    apiClient.get("/workflows/" + workflowId)
      .then((res) => {
        const wf = res.data;
        setWfName(wf.name || "untitled");
        setWorkflowProjectId(wf.project_id || undefined);
        const workflowNodes = (wf.nodes || []).map((n: any) => {
          const op = meta[n.operator_id] || {};
          return {
            id: String(n.id),
            type: "custom",
            position: { x: n.position_x || 200, y: n.position_y || 200 },
            data: {
              operatorId: n.operator_id,
              label: n.label || "",
              params: n.params || {},
              category: op.category || "utility",
              inputs: op.inputs || [],
              outputs: op.outputs || [],
            },
          };
        });
        if (wf.nodes) {
          setNodes(workflowNodes);
        }
        if (wf.edges) {
          setEdges(hydrateWorkflowEdges(wf.edges, workflowNodes));
        }
      })
      .catch(() => {
        message.warning(text.loadFailed);
      });
  };

  useEffect(() => {
    // Run state (isRunning/currentRunId/node statuses) lives in a global
    // store; clear it when switching workflows so one workflow's execution
    // state never leaks into another.
    resetExecution();
    apiClient.get("/operators")
      .then((res) => {
        const data = res.data;
        setOperators(Array.isArray(data) ? data : data.items || []);
      })
      .catch(() => {})
      .finally(() => {
        loadWorkflow();
        adoptActiveRun();
      });
    return () => {
      if (wsRef.current) wsRef.current.close();
      closeNodeResult();
    };
  }, [workflowId, closeNodeResult]);

  const buildPayload = () => {
    const store = useWorkflowStore.getState();
    const meta = getOpMeta();
    // Build port lookup per node
    const ports: Record<string, { ins: {name:string}[], outs: {name:string}[] }> = {};
    for (const n of store.nodes) {
      const op = meta[n.data.operatorId] || {};
      ports[n.id] = { ins: op.inputs || [], outs: op.outputs || [] };
    }
    return {
      name: wfName || "untitled",
      nodes: store.nodes.map((n: any) => ({
        id: n.id,
        operator_id: n.data.operatorId,
        label: n.data.label || "",
        position: { x: n.position.x, y: n.position.y },
        params: n.data.params || {},
      })),
      edges: store.edges.map((e: any) => {
        const srcP = ports[e.source];
        const tgtP = ports[e.target];
        const sourcePort = resolvePort(e.sourceHandle || "out-0", srcP?.outs || []);
        const targetPort = resolvePort(e.targetHandle || "in-0", tgtP?.ins || []);
        return {
          id: e.id,
          source: e.source,
          source_port: sourcePort,
          target: e.target,
          target_port: targetPort,
        };
      }),
    };
  };

  const handleSave = async () => {
    if (!workflowId) return;
    try {
      await apiClient.put("/workflows/" + workflowId, buildPayload());
      message.success(text.saved);
    } catch {
      message.error(text.saveFailed);
    }
  };

  // 先保存当前草稿，再把图复制为模板；作用域在弹窗中选择（项目/全平台通用）。
  const openTemplateModal = () => {
    tplForm.setFieldsValue({ name: `${wfName || "untitled"}-模板`, scope: "project" });
    setTplModalOpen(true);
  };

  const handleSaveAsTemplate = async (values: { name?: string; scope?: string }) => {
    if (!workflowId || !workflowProjectId) return;
    setSavingTemplate(true);
    try {
      await apiClient.put("/workflows/" + workflowId, buildPayload());
      const res = await apiClient.post(
        `/projects/${workflowProjectId}/workflows/${workflowId}/save-as-template`,
        { name: values.name || undefined, scope: values.scope || "project" },
      );
      const isGlobal = (values.scope || "project") === "global";
      message.success(isGlobal ? text.tplSavedGlobal : `${text.tplSaved}：${res.data?.name || wfName + "-模板"}`);
      setTplModalOpen(false);
    } catch (error) {
      message.error(formatApiError(error, text.tplSaveFailed));
    } finally {
      setSavingTemplate(false);
    }
  };

  const handleNameSave = async () => {
    setEditingName(false);
    if (!workflowId || !wfName.trim()) return;
    try {
      await apiClient.put("/workflows/" + workflowId, buildPayload());
    } catch { /* silent */ }
  };

  const handlePublish = async () => {
    if (!workflowId) return;
    try {
      await apiClient.put("/workflows/" + workflowId, buildPayload());
      const version = await publishWorkflow(workflowId);
      message.success(`已发布版本 v${version.version}`);
    } catch (error: any) {
      message.error(error.response?.data?.detail || text.publishFailed);
    }
  };

  // 方案B：把当前草稿发布为版本并注册为编排 API（推理子图 + 冻结模型制品）。
  const handlePublishApi = async () => {
    if (!workflowId) return;
    try {
      await apiClient.put("/workflows/" + workflowId, buildPayload());
      const version = await publishWorkflow(workflowId);
      const api = await publishWorkflowApi(workflowId, version.version);
      message.success(`${text.publishApiSuccess}（${api.name}）`);
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      message.error(typeof detail === "object" && detail?.message ? detail.message : (detail || text.publishApiFailed));
    }
  };

  const openVersions = async () => {
    if (!workflowId) return;
    setVersionsOpen(true);
    setVersionsLoading(true);
    try {
      setVersions(await listWorkflowVersions(workflowId));
    } catch {
      message.error(text.historyFailed);
    } finally {
      setVersionsLoading(false);
    }
  };

  const handleRestoreVersion = async (version: number) => {
    if (!workflowId) return;
    await restoreWorkflowVersion(workflowId, version);
    setVersionsOpen(false);
    loadWorkflow();
    message.success(`已恢复版本 v${version} 到草稿`);
  };

  const handleDeleteVersion = async (version: number) => {
    if (!workflowId) return;
    try {
      await deleteWorkflowVersion(workflowId, version);
      setVersions((current) => current.filter((item) => item.version !== version));
      message.success(`已删除版本 v${version}`);
    } catch (error: any) {
      message.error(error.response?.data?.detail || "删除版本失败");
    }
  };

  const handleStop = async () => {
    if (!currentRunId) {
      // Stale UI state without a run: self-heal instead of a silent no-op.
      setIsRunning(false);
      message.warning("当前没有正在运行的执行");
      return;
    }
    try {
      const response = await apiClient.post("/runs/" + currentRunId + "/cancel");
      setWorkflowStatus(response.data.status as WorkflowRunStatus);
      setNodeStatus("__wf__", "cancelled");
      // The executor task is terminated server-side, so no run_completed
      // event will arrive; leave the running state immediately.
      setIsRunning(false);
      message.info(text.cancelled);
    } catch (error: any) {
      message.error(error.response?.data?.detail || text.cancelFailed);
    }
  };

  const persistNodeRun = (nodeRun: any) => {
    const nodeId = String(nodeRun.node_id);
    const status = nodeRun.status as NodeRunStatus;
    setNodeStatus(nodeId, status);
    if (nodeRun.result !== undefined && nodeRun.result !== null || nodeRun.metrics || nodeRun.logs) {
      const baseResult = nodeRun.result && typeof nodeRun.result === "object" && !Array.isArray(nodeRun.result)
        ? { ...nodeRun.result }
        : (nodeRun.result === undefined || nodeRun.result === null ? {} : { value: nodeRun.result });
      if (nodeRun.metrics && (!baseResult.metrics || Object.keys(baseResult.metrics).length === 0)) {
        baseResult.metrics = nodeRun.metrics;
      }
      if (Array.isArray(nodeRun.logs) && (!Array.isArray(baseResult.logs) || baseResult.logs.length === 0)) {
        baseResult.logs = nodeRun.logs;
      }
      setNodeResult(nodeId, baseResult);
    }
    const resultError = nodeRun.result && typeof nodeRun.result === "object"
      ? nodeRun.result
      : undefined;
    const explicitError = nodeRun.error || nodeRun.error_code || nodeRun.error_message ||
      nodeRun.error_details || resultError?.error || resultError?.error_code || resultError?.error_message;
    if (explicitError && nodeId !== "__wf__") {
      const nodeError = normalizeNodeError(nodeId, {
        ...nodeRun,
        error: nodeRun.error ?? resultError?.error,
        error_code: nodeRun.error_code ?? resultError?.error_code,
        error_message: nodeRun.error_message ?? resultError?.error_message ?? resultError?.error,
      });
      if (nodeError) setNodeError(nodeId, nodeError);
    }
  };

  const reconcileRun = async (runId: string) => {
    try {
      const response = await apiClient.get("/runs/" + runId);
      const run = response.data;
      setWorkflowStatus(run.status as WorkflowRunStatus);
      setIsRunning(["pending", "running", "cancel_requested"].includes(run.status));
      for (const nodeRun of run.node_runs || []) {
        persistNodeRun(nodeRun);
      }
    } catch {
      message.warning("无法恢复运行状态");
    }
  };

  const showRunError = async (runId: string, fallback: string) => {
    try {
      const response = await apiClient.get("/runs/" + runId);
      const run = response.data;
      const failedAttempt = (run.node_runs || []).find((item: any) =>
        ["failed", "timed_out"].includes(item.status)
      );
      if (failedAttempt) persistNodeRun(failedAttempt);
      const lines = [
        run.error_code ? `错误码：${run.error_code}` : "",
        run.error_message || fallback,
        failedAttempt ? `节点：${failedAttempt.node_id}，第 ${failedAttempt.attempt} 次尝试` : "",
      ].filter(Boolean);
      Modal.error({ title: "运行失败", content: lines.join("\n") });
    } catch {
      message.error("运行失败: " + fallback);
    }
  };

  const attachRunListeners = (runId: string) => {
    const wsUrl = (window.location.protocol === "https:" ? "wss:" : "ws:") +
      "//" + window.location.host + "/ws/runs/" + runId;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      void reconcileRun(runId);
    };
    ws.onmessage = (event: MessageEvent) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "node_status") {
        persistNodeRun({
          ...msg,
          node_id: msg.node_id,
          error: msg.error,
          error_code: msg.error_code,
          error_message: msg.error_message,
          error_details: msg.error_details,
        });
        if (msg.node_id === "__wf__") setWorkflowStatus(msg.status as WorkflowRunStatus);
        if (msg.progress != null) setNodeProgress(msg.node_id, msg.progress);
      } else if (msg.type === "run_completed") {
        setIsRunning(false);
        setWorkflowStatus(msg.status as WorkflowRunStatus);
        wsRef.current = null;
        ws.close();
        if (msg.status === "completed") {
          message.success("工作流运行完成");
          setNodeStatus("__wf__", "completed");
        } else if (msg.status === "cancelled") {
          message.info("工作流已取消");
          setNodeStatus("__wf__", "cancelled");
        } else {
          void showRunError(runId, msg.error || "未知错误");
          setNodeStatus("__wf__", "failed");
        }
      }
    };
    ws.onerror = () => {
      wsRef.current = null;
      void reconcileRun(runId);
      message.warning("实时连接已关闭，正在恢复运行状态");
    };
  };

  // Restore the running-state UI when opening a workflow whose run is still
  // executing (e.g. after a page refresh or when switching between workflows).
  const adoptActiveRun = () => {
    if (!workflowId) return;
    apiClient.get("/workflows/" + workflowId + "/runs/active")
      .then((res) => {
        const run = res.data?.run;
        if (run && ["pending", "running", "cancel_requested"].includes(run.status)) {
          setCurrentRunId(run.id);
          setWorkflowStatus(run.status as WorkflowRunStatus);
          setIsRunning(true);
          attachRunListeners(run.id);
        }
      })
      .catch(() => {});
  };

  const handleRun = async () => {
    if (!workflowId) return;

    if (isRunning) {
      handleStop();
      return;
    }

    // Reset execution state before starting new run
    resetExecution();
    setIsRunning(true);
    setNodeStatus("__wf__", "pending");
    try {
      await apiClient.put("/workflows/" + workflowId, buildPayload());
      const reload = await apiClient.get("/workflows/" + workflowId);
        const meta = getOpMeta();
        const wf = reload.data;
        const workflowNodes = (wf.nodes || []).map((n: any) => {
          const op = meta[n.operator_id] || {};
          return {
            id: String(n.id),
            type: "custom",
            position: { x: n.position_x || 200, y: n.position_y || 200 },
            data: {
              operatorId: n.operator_id,
              label: n.label || "",
              params: n.params || {},
              category: op.category || "utility",
              inputs: op.inputs || [],
              outputs: op.outputs || [],
            },
          };
        });
        if (wf.nodes) {
          setNodes(workflowNodes);
        }
        if (wf.edges) {
          setEdges(hydrateWorkflowEdges(wf.edges, workflowNodes));
      }

      const runRes = await apiClient.post("/workflows/" + workflowId + "/run");
      const runId = runRes.data.run_id;
      setCurrentRunId(runId);
      setWorkflowStatus("pending");
      attachRunListeners(runId);
    } catch (e: any) {
      setIsRunning(false);
      setNodeStatus("__wf__", "failed");
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      message.error(formatApiError(e, "运行失败"));
    }
  };

  const handleDeleteWorkflow = async () => {
    if (!workflowId) return;
    setDeleting(true);
    try {
      await apiClient.delete("/workflows/" + workflowId);
      message.success("工作流已删除");
      navigate(-1);
    } catch {
      message.error("删除失败，请重试");
      setDeleting(false);
      setDeleteOpen(false);
    }
  };

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    const opData = JSON.parse(event.dataTransfer.getData("application/reactflow"));
    const rfInstance = useWorkflowStore.getState().reactFlowInstance;
    let position: { x: number; y: number };
    if (rfInstance) {
      position = rfInstance.screenToFlowPosition({ x: event.clientX, y: event.clientY });
    } else {
      const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect();
      position = { x: event.clientX - bounds.left - 75, y: event.clientY - bounds.top - 30 };
    }
    useWorkflowStore.getState().addNode(opData.id, position, opData);
  }, []);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  // 工具条三版可切换：URL 加 ?toolbar=a/b/c 预览（a=图标极简[默认] b=运行坞 c=紧凑文字）
  const toolbarVariant = (new URLSearchParams(window.location.search).get("toolbar") || "a") as
    "a" | "b" | "c";

  return (
    <ReactFlowProvider>
      <Layout className="workspace-layout">
        <Drawer title={text.history} open={versionsOpen} onClose={() => setVersionsOpen(false)} width={420}>
          <List
            loading={versionsLoading}
            dataSource={versions}
            locale={{ emptyText: text.noVersions }}
            renderItem={(item) => (
              <List.Item actions={[<Button key="restore" size="small" onClick={() => {
                Modal.confirm({
                  title: `恢复版本 v${item.version}？`,
                  content: "当前草稿将被该版本覆盖，已发布历史不会删除。",
                  onOk: () => handleRestoreVersion(item.version),
                });
              }}>{text.restore}</Button>, <Button key="delete" size="small" danger onClick={() => {
                Modal.confirm({
                  title: `删除版本 v${item.version}？`,
                  content: "此操作不可撤销。",
                  okType: "danger",
                  onOk: () => handleDeleteVersion(item.version),
                });
              }}>{text.delete}</Button>]}>
                <List.Item.Meta
                  title={<Space><Tag color="blue">v{item.version}</Tag>{item.name}</Space>}
                  description={formatLocalTime(item.published_at, true)}
                />
              </List.Item>
            )}
          />
        </Drawer>
        <Sider className="workspace-sider workspace-sider--operators" width={210} style={{ background: "var(--bg-surface)", borderRight: "1px solid var(--border-default)", overflow: "auto" }}>
          <div className="workspace-sider-header">
            {text.operatorPanel}
          </div>
          <OperatorPanel />
        </Sider>

        <Content className="workspace-canvas" onDrop={onDrop} onDragOver={onDragOver}>
          <div className="workspace-title-chip">
            <Button type="text" size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}
              aria-label={text.back} title={text.back} />
            <Divider type="vertical" style={{ margin: "0 2px" }} />
            {editingName ? (
              <Input size="small" value={wfName} onChange={(e) => setWfName(e.target.value)}
                onPressEnter={handleNameSave} onBlur={handleNameSave} autoFocus style={{ width: 180 }} />
            ) : (
              <>
                <span style={{ fontWeight: 600, fontSize: 14, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {wfName || "untitled"}
                </span>
                <Button type="text" size="small" icon={<EditOutlined />} onClick={() => setEditingName(true)} />
              </>
            )}
          </div>

          <WorkflowCanvas />
          <ExecutionProgress />

          {/* 工具条三版可切换：URL 加 ?toolbar=a/b/c 预览（a=图标极简[默认] b=运行坞 c=紧凑文字） */}
          <div className="workspace-actions" data-variant={toolbarVariant}>
            {/* 保存（各版通用）：高频操作 */}
            <Tooltip title={text.save}>
              <Button size={toolbarVariant === "c" ? "small" : "middle"} icon={<SaveOutlined />}
                onClick={handleSave} aria-label={text.save} />
            </Tooltip>
            {/* 发布下拉：发布版本 / 发布为 API 两个发布动作合一 */}
            <Dropdown
              menu={{
                items: [
                  { key: "publish", icon: <CloudUploadOutlined />, label: text.publish },
                  { key: "publish-api", icon: <ApiOutlined />, label: text.publishApi },
                ],
                onClick: ({ key }) => {
                  if (key === "publish") handlePublish();
                  if (key === "publish-api") handlePublishApi();
                },
              }}
              trigger={["click"]}
            >
              {toolbarVariant === "a" ? (
                <Button icon={<CloudUploadOutlined />} aria-label={text.publish} />
              ) : (
                <Button size={toolbarVariant === "c" ? "small" : "middle"}>
                  <CloudUploadOutlined /> {text.publish} <DownOutlined />
                </Button>
              )}
            </Dropdown>
            {/* 更多下拉：模板 / 版本 / 删除 等低频操作收纳于此 */}
            <Dropdown
              menu={{
                items: [
                  { key: "template", icon: <CopyOutlined />, label: text.saveAsTemplate || "保存为模板" },
                  { key: "versions", icon: <HistoryOutlined />, label: text.version },
                  { type: "divider" },
                  { key: "delete", icon: <DeleteOutlined />, label: text.delete, danger: true },
                ],
                onClick: ({ key }) => {
                  if (key === "template") openTemplateModal();
                  if (key === "versions") openVersions();
                  if (key === "delete") setDeleteOpen(true);
                },
              }}
              trigger={["click"]}
            >
              {toolbarVariant === "a" ? (
                <Button icon={<EllipsisOutlined />} aria-label={text.more || "更多"} />
              ) : (
                <Button size={toolbarVariant === "c" ? "small" : "middle"}
                  icon={<EllipsisOutlined />} aria-label={text.more || "更多"} />
              )}
            </Dropdown>
            {/* 运行：画布主操作。a/c 版常驻行尾；b 版移入右下运行坞 */}
            {toolbarVariant !== "b" && (isRunning ? (
              <Button danger icon={<PauseCircleOutlined />} onClick={handleRun}>
                {text.stop}
              </Button>
            ) : (
              <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleRun}>
                {text.run}
              </Button>
            ))}
          </div>
          {toolbarVariant === "b" && (
            <div className="workspace-run-dock">
              {isRunning ? (
                <Button danger shape="circle" icon={<PauseCircleOutlined />}
                  onClick={handleRun} aria-label={text.stop} />
              ) : (
                <Button type="primary" shape="circle" size="large" icon={<PlayCircleOutlined />}
                  onClick={handleRun} aria-label={text.run} />
              )}
            </div>
          )}
        </Content>

        <Sider className="workspace-sider workspace-sider--config" width={290} style={{ background: "var(--bg-surface)", borderLeft: "1px solid var(--border-default)", overflow: "auto" }}>
          <div className="workspace-sider-header">
            {text.nodeConfig}
          </div>
          <NodeConfigPanel projectId={workflowProjectId} />
        </Sider>
      </Layout>

      <NodeResultPanel />

      <Modal title={text.confirmDelete} open={deleteOpen} onOk={handleDeleteWorkflow}
        onCancel={() => setDeleteOpen(false)} confirmLoading={deleting}
        okText={text.delete} cancelText={text.cancel} okButtonProps={{ danger: true }}>
        <p>{text.deletePrompt} <b>{wfName || "untitled"}</b>? {text.irreversible}</p>
      </Modal>

      <Modal
        title={text.tplModalTitle}
        open={tplModalOpen}
        onCancel={() => setTplModalOpen(false)}
        onOk={() => tplForm.submit()}
        confirmLoading={savingTemplate}
        okText={text.save} cancelText={text.cancel}
      >
        <Form form={tplForm} layout="vertical" onFinish={handleSaveAsTemplate}>
          <Form.Item name="name" label={text.tplName} rules={[{ required: true, message: text.tplName }]}>
            <Input maxLength={128} />
          </Form.Item>
          <Form.Item name="scope" label={text.tplScope} initialValue="project">
            <Radio.Group>
              <Radio value="project">{text.scopeProject}</Radio>
              {isAdmin && <Radio value="global">{text.scopeGlobal}</Radio>}
            </Radio.Group>
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.scope !== cur.scope}>
            {() => (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {tplForm.getFieldValue("scope") === "global" ? text.scopeGlobalHint : text.scopeProjectHint}
              </Text>
            )}
          </Form.Item>
        </Form>
      </Modal>
    </ReactFlowProvider>
  );
}
