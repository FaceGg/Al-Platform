import { useEffect, useCallback, useState, useRef } from "react";
import { useParams } from "react-router-dom";
import { App as AntApp, Layout, Button, Space, Input, Modal, Drawer, List, Tag } from "antd";
import { PlayCircleOutlined, SaveOutlined, ArrowLeftOutlined, EditOutlined, PauseCircleOutlined, DeleteOutlined, CloudUploadOutlined, HistoryOutlined } from "@ant-design/icons";
import { ReactFlowProvider } from "reactflow";
import { useNavigate } from "react-router-dom";
import apiClient from "../api/client";
import { formatApiError } from "../api/client";
import OperatorPanel from "../components/workspace/OperatorPanel";
import WorkflowCanvas from "../components/workspace/WorkflowCanvas";
import NodeConfigPanel from "../components/workspace/NodeConfigPanel";
import ExecutionProgress from "../components/workspace/ExecutionProgress";
import { useWorkflowStore } from "../stores/workflowStore";
import type { NodeRunStatus, WorkflowRunStatus } from "../stores/workflowStore";
import { deleteWorkflowVersion, listWorkflowVersions, publishWorkflow, restoreWorkflowVersion, WorkflowVersionSummary } from "../api/workflowVersions";
import { useI18n } from "../i18n";

const { Sider, Content } = Layout;

export function resolvePort(handleId: string, portList: {name:string}[]): string {
  if (!handleId) return "";
  // Already a port name (e.g., "data", "left") — pass through
  if (!/^(in|out)-\d+$/.test(handleId)) return handleId;
  const idx = parseInt(handleId.replace(/^(in|out)-/, ""), 10);
  return (!isNaN(idx) && idx < portList.length) ? portList[idx].name : handleId;
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
    back: "返回", save: "保存", publish: "发布", version: "版本", run: "运行", stop: "终止",
    confirmDelete: "确认删除", cancel: "取消", deletePrompt: "确定要删除工作流", irreversible: "此操作不可撤销。",
  } : {
    loadFailed: "Failed to load workflow", saved: "Saved", saveFailed: "Save failed. Please retry.", publishFailed: "Publish failed",
    historyFailed: "Failed to load version history", cancelled: "Cancellation requested; the current node will stop safely.", cancelFailed: "Cancellation failed",
    restored: "Unable to recover run status", runFailed: "Workflow run failed", runComplete: "Workflow run completed", runCancelled: "Workflow run cancelled",
    liveClosed: "Live connection closed; recovering run status", deleteFailed: "Delete failed. Please retry.", history: "Version history",
    noVersions: "No published versions", restore: "Restore", delete: "Delete", operatorPanel: "Operator panel", nodeConfig: "Node configuration",
    back: "Back", save: "Save", publish: "Publish", version: "Versions", run: "Run", stop: "Stop",
    confirmDelete: "Confirm deletion", cancel: "Cancel", deletePrompt: "Delete workflow", irreversible: "This action cannot be undone.",
  };
  const { workflowId } = useParams<{ workflowId: string }>();
  const navigate = useNavigate();
  const {
    operators, setOperators, setNodes, setEdges,
    isRunning, setIsRunning, setNodeStatus, setNodeResult, setNodeProgress, resetExecution,
    currentRunId, setCurrentRunId, setWorkflowStatus,
    reset,
  } = useWorkflowStore();
  const [wfName, setWfName] = useState("");
  const [editingName, setEditingName] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
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
        if (wf.nodes) {
          setNodes(
            wf.nodes.map((n: any) => {
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
            })
          );
        }
        if (wf.edges) {
          setEdges(
            wf.edges.map((e: any) => ({
              id: String(e.id),
              source: String(e.source_node_id),
              target: String(e.target_node_id),
              sourceHandle: e.source_port || "out-0",
              targetHandle: e.target_port || "in-0",
            }))
          );
        }
      })
      .catch(() => {
        message.warning(text.loadFailed);
      });
  };

  useEffect(() => {
    apiClient.get("/operators")
      .then((res) => {
        const data = res.data;
        setOperators(Array.isArray(data) ? data : data.items || []);
      })
      .catch(() => {})
      .finally(() => {
        loadWorkflow();
      });
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, [workflowId]);

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
    if (!currentRunId) return;
    try {
      const response = await apiClient.post("/runs/" + currentRunId + "/cancel");
      setWorkflowStatus(response.data.status as WorkflowRunStatus);
      setNodeStatus("__wf__", "cancelled");
      message.info(text.cancelled);
    } catch (error: any) {
      message.error(error.response?.data?.detail || text.cancelFailed);
    }
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
      if (wf.nodes) {
        setNodes(
          wf.nodes.map((n: any) => {
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
          })
        );
      }
      if (wf.edges) {
        setEdges(
          wf.edges.map((e: any) => ({
            id: String(e.id),
            source: String(e.source_node_id),
            target: String(e.target_node_id),
            sourceHandle: e.source_port || "out-0",
            targetHandle: e.target_port || "in-0",
          }))
        );
      }

      const runRes = await apiClient.post("/workflows/" + workflowId + "/run");
      const runId = runRes.data.run_id;
      setCurrentRunId(runId);
      setWorkflowStatus("pending");

      const reconcileRun = async () => {
        try {
          const response = await apiClient.get("/runs/" + runId);
          const run = response.data;
          setWorkflowStatus(run.status as WorkflowRunStatus);
          setIsRunning(["pending", "running", "cancel_requested"].includes(run.status));
          for (const nodeRun of run.node_runs || []) {
            setNodeStatus(String(nodeRun.node_id), nodeRun.status as NodeRunStatus);
            if (nodeRun.result) setNodeResult(String(nodeRun.node_id), nodeRun.result);
          }
        } catch {
          message.warning("无法恢复运行状态");
        }
      };

      const showRunError = async (fallback: string) => {
        try {
          const response = await apiClient.get("/runs/" + runId);
          const run = response.data;
          const failedAttempt = (run.node_runs || []).find((item: any) =>
            ["failed", "timed_out"].includes(item.status)
          );
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

      const wsUrl = (window.location.protocol === "https:" ? "wss:" : "ws:") +
        "//" + window.location.host + "/ws/runs/" + runId;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => { /* connected */ };
      ws.onmessage = (event: MessageEvent) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "node_status") {
          setNodeStatus(msg.node_id, msg.status as NodeRunStatus);
          if (msg.node_id === "__wf__") setWorkflowStatus(msg.status as WorkflowRunStatus);
          if (msg.result) setNodeResult(msg.node_id, msg.result);
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
            void showRunError(msg.error || "未知错误");
            setNodeStatus("__wf__", "failed");
          }
        }
      };
      ws.onerror = () => {
        wsRef.current = null;
        void reconcileRun();
        message.warning("实时连接已关闭，正在恢复运行状态");
      };
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

  return (
    <ReactFlowProvider>
      <Layout style={{ height: "100vh" }}>
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
                  description={item.published_at ? new Date(item.published_at).toLocaleString() : ""}
                />
              </List.Item>
            )}
          />
        </Drawer>
        <Sider width={210} style={{ background: "#fff", borderRight: "1px solid #e8e8e8", overflow: "auto" }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid #f0f0f0", fontWeight: 600, fontSize: 14, background: "#fafafa" }}>
            {text.operatorPanel}
          </div>
          <OperatorPanel />
        </Sider>

        <Content onDrop={onDrop} onDragOver={onDragOver} style={{ position: "relative", background: "#f5f5f5" }}>
          <div style={{
            position: "absolute", top: 10, left: 10, zIndex: 10,
            background: "rgba(255,255,255,0.95)", borderRadius: 8, padding: "6px 14px",
            boxShadow: "0 2px 8px rgba(0,0,0,0.08)", display: "flex", alignItems: "center", gap: 8,
            backdropFilter: "blur(8px)",
          }}>
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

          <Space style={{ position: "absolute", top: 10, right: 10, zIndex: 10 }}>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ borderRadius: 6 }}>
              {text.back}
            </Button>
            <Button icon={<SaveOutlined />} onClick={handleSave} style={{ borderRadius: 6 }}>
              {text.save}
            </Button>
            <Button icon={<CloudUploadOutlined />} onClick={handlePublish} style={{ borderRadius: 6 }}>
              {text.publish}
            </Button>
            <Button icon={<HistoryOutlined />} onClick={openVersions} style={{ borderRadius: 6 }}>
              {text.version}
            </Button>
            {isRunning ? (
              <Button danger icon={<PauseCircleOutlined />} onClick={handleRun} style={{ borderRadius: 6, fontWeight: 600 }}>
                {text.stop}
              </Button>
            ) : (
              <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleRun} style={{ borderRadius: 6, fontWeight: 600 }}>
                {text.run}
              </Button>
            )}
            <Button danger icon={<DeleteOutlined />} onClick={() => setDeleteOpen(true)} style={{ borderRadius: 6 }}>
              {text.delete}
            </Button>
          </Space>
        </Content>

        <Sider width={290} style={{ background: "#fff", borderLeft: "1px solid #e8e8e8", overflow: "auto" }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid #f0f0f0", fontWeight: 600, fontSize: 14, background: "#fafafa" }}>
            {text.nodeConfig}
          </div>
          <NodeConfigPanel />
        </Sider>
      </Layout>

      <Modal title={text.confirmDelete} open={deleteOpen} onOk={handleDeleteWorkflow}
        onCancel={() => setDeleteOpen(false)} confirmLoading={deleting}
        okText={text.delete} cancelText={text.cancel} okButtonProps={{ danger: true }}>
        <p>{text.deletePrompt} <b>{wfName || "untitled"}</b>? {text.irreversible}</p>
      </Modal>
    </ReactFlowProvider>
  );
}
