import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, Button, Card, Col, Input, InputNumber, message, Progress, Row, Select, Space, Statistic,
  Table, Tag, Timeline, Typography, Upload,
} from "antd";
import {
  ArrowLeftOutlined, CaretRightOutlined, DeploymentUnitOutlined, EditOutlined,
  MonitorOutlined, PauseOutlined, ReloadOutlined, RestOutlined, UploadOutlined,
} from "@ant-design/icons";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import AppLayout from "../components/AppLayout";
import PageHeading from "../components/PageHeading";
import LoopConfigModal, { type FieldDescTask, type LoopEditorState } from "../components/loop/LoopConfigModal";
import FleetShardPanel from "../components/loop/FleetShardPanel";
import { formatApiError } from "../api/client";
import {
  addFleetShard, deriveSupervisedDataset, fetchFleetOverview, labelRecalibrateVersion,
  recalibrateDeviceVersion,
  type DerivedSupervisedDatasetResult, type DeviceRecalibrateResult, type FleetShardCreatePayload,
  type FleetShardResult, type LabelRecalibrateResult,
} from "../api/modelRegistry";
import { listAnnotationTasks } from "../api/annotationTasks";
import {
  type DemoLoopConfig, type DemoLoopPredictResult, type DemoLoopStatus, type ReflowRow,
  fetchDemoLoopAnnotators, fetchDemoLoopDatasets, fetchDemoLoopDeployments,
  fetchDemoLoops, fetchDemoLoopStatusScoped, fetchReflowRows, markReflowRow,
  predictDemoLoopRowScoped,
  resetDemoLoopScoped,
} from "../api/demoLoop";
import { useI18n } from "../i18n";
import { parseBackendTime } from "../utils/time";

const { Text } = Typography;

interface ParsedRow { __index: number; values: Record<string, unknown>; }

function parseCsv(text: string): ParsedRow[] {
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 1; } else { inQuotes = false; }
      } else { field += ch; }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(field); field = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i += 1;
      row.push(field); field = "";
      if (row.some((item) => item !== "")) rows.push(row);
      row = [];
    } else { field += ch; }
  }
  row.push(field);
  if (row.some((item) => item !== "")) rows.push(row);
  if (rows.length < 2) return [];
  const header = rows[0].map((item) => item.trim());
  return rows.slice(1).map((cells, index) => {
    const values: Record<string, unknown> = {};
    header.forEach((name, position) => {
      const raw = (cells[position] ?? "").trim();
      const numeric = raw !== "" && !Number.isNaN(Number(raw)) ? Number(raw) : raw;
      values[name] = numeric;
    });
    return { __index: index + 1, values };
  });
}

const EVENT_COLORS: Record<string, string> = {
  row_predicted: "blue", error_row: "red", error_appended: "red",
  alert_triggered: "orange", review_task_created: "orange",
  retrain_triggered: "purple", retrain_running: "purple",
  retrain_completed: "purple", retrain_failed: "purple",
  retrain_agent_triggered: "geekblue", retrain_agent_accepted: "green",
  retrain_agent_rejected: "red", retrain_agent_failed: "red",
  retrain_agent_timeout: "red", retrain_agent_circuit_break: "red",
  retrain_casting_started: "purple", retrain_reservitize_manual: "gold",
  model_swapped: "gold", swap_failed: "red", loop_reset: "blue",
};
/** 报警确认反馈面板（技术方案 §3.6 弱监督回流）：回流行逐条「确认故障/误报」。
 *
 * 标记随下次重拟合消费——误报行进排除集（收窄误包络）、确认故障行进换模
 * 门禁验证集（防重拟合洗掉历史检出能力）。状态 2s 轮询自愈，无需本地刷新。
 */
function ReflowFeedbackPanel({ projectId, loopId, onChanged }: {
  projectId: string; loopId: string; onChanged?: () => void;
}) {
  const [rows, setRows] = useState<ReflowRow[]>([]);
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [marking, setMarking] = useState<number | null>(null);

  const load = useCallback(() => {
    if (!projectId || !loopId) return;
    fetchReflowRows(projectId, loopId, 50)
      .then((res: any) => {
        setRows(res?.rows || []);
        setArtifactId(res?.artifact_id || null);
      })
      .catch(() => undefined);
  }, [projectId, loopId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const mark = async (rowIndex: number, mark: "confirmed_fault" | "false_alarm" | "none") => {
    if (!artifactId) return;
    setMarking(rowIndex);
    try {
      await markReflowRow(projectId, loopId, { artifact_id: artifactId, row_index: rowIndex, mark });
      onChanged?.();
    } catch (error: any) {
      message.error(formatApiError(error, "标记失败"));
    } finally {
      setMarking(null);
      load();
    }
  };

  if (!rows.length) return null;
  return (
    <div style={{ border: "1px solid var(--v2-line, #eee)", borderRadius: 8, padding: "8px 12px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Text strong style={{ fontSize: 13 }}>报警确认（回流行标记 · 影响下次重拟合）</Text>
        <Button type="link" size="small" onClick={() => setOpen(!open)}>{open ? "收起" : `展开（${rows.length} 行）`}</Button>
      </Space>
      {open && (
        <div style={{ maxHeight: 240, overflowY: "auto", marginTop: 6 }}>
          {rows.map((row) => (
            <div key={row.row_index} style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 0", borderBottom: "1px dashed var(--v2-line, #f0f0f0)" }}>
              <Text type="secondary" style={{ fontSize: 12, minWidth: 46 }}>#{row.row_index}</Text>
              <Text style={{ fontSize: 12, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {Object.entries(row.record || {}).slice(0, 4).map(([key, value]) => `${key}=${String(value)}`).join(" · ")}
              </Text>
              {row.anomaly_score != null && <Tag color="orange" style={{ fontSize: 11 }}>分数 {row.anomaly_score}</Tag>}
              {row.feedback === "confirmed_fault" && <Tag color="red">确认故障</Tag>}
              {row.feedback === "false_alarm" && <Tag color="green">误报</Tag>}
              {!row.feedback && (
                <>
                  <Button size="small" danger loading={marking === row.row_index} onClick={() => void mark(row.row_index, "confirmed_fault")}>确认故障</Button>
                  <Button size="small" loading={marking === row.row_index} onClick={() => void mark(row.row_index, "false_alarm")}>误报</Button>
                </>
              )}
              {row.feedback && (
                <Button size="small" type="text" loading={marking === row.row_index} onClick={() => void mark(row.row_index, "none")}>撤销</Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const EVENT_LABELS: Record<string, string> = {
  row_predicted: "正常预测", error_row: "命中报错类别", error_appended: "错误数据回流",
  alert_triggered: "触发管理员告警", review_task_created: "创建人工审核任务",
  retrain_triggered: "自动建模已触发", retrain_running: "自动建模执行中",
  retrain_completed: "自动建模完成", retrain_failed: "自动建模失败",
  retrain_agent_triggered: "智能体重训已触发", retrain_agent_accepted: "智能体重放验收通过",
  retrain_agent_rejected: "智能体重放未通过验收", retrain_agent_failed: "智能体重放失败",
  retrain_agent_timeout: "智能体重放超时", retrain_agent_circuit_break: "智能体重训熔断",
  retrain_casting_started: "部署模型铸造中", retrain_reservitize_manual: "建议重新服务化",
  // 换模语义按模式区分：agent 轮特征工程+模型一起更新（配方重放产物），
  // engine 轮只换模型。事件流文案在渲染处按 isAgentMode 动态取。
  model_swapped: "模型与特征工程已更新", swap_failed: "模型替换失败", loop_reset: "闭环重置",
};

/** M9 新设备重标定 + 迁移版本挂载（技术方案 §7.2 / §7.1.4，三期 M9）。
 *
 * 现场流程：新设备采一批**纯正常**数据 → 选标定数据集 + 填工况值（设备号/
 * 工位号）→ `recalibrate-device` 只重跑标定层（不动检测器主体）→ fleet_fit
 * 判定：compatible → 可挂载；unfit → §7.2「不硬迁」——版本仍产出但标记 unfit，
 * 界面明确拒挂并提示独立建模。
 *
 * 挂载走 `fleet-shards`：新 stable revision = 既有分片全量复制 + 新分片；工况列
 * 必须与部署一致（服务端 fail-closed），故按部署 fleet-overview 读出后透传。
 */
function DeviceRecalibratePanel({
  deploymentId, sourceVersionId, calibrationArtifact, datasets,
}: {
  deploymentId: string | null;
  sourceVersionId: string | null;
  calibrationArtifact: { id: string; name: string } | null;
  datasets: Array<{ id: string; name: string }>;
}) {
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const [conditionValue, setConditionValue] = useState("");
  const [conditionColumn, setConditionColumn] = useState<string | null>(null);
  const [rows, setRows] = useState<number | null>(null);
  const [totalRows, setTotalRows] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DeviceRecalibrateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState<FleetShardResult | null>(null);
  const [mountError, setMountError] = useState<string | null>(null);

  // 标定数据集默认取闭环回流的报错数据集（与 M6 面板同一数据源）
  const selectedArtifactId = artifactId ?? calibrationArtifact?.id ?? null;
  const artifactOptions = [
    ...(calibrationArtifact
      ? [{ value: calibrationArtifact.id, label: `${calibrationArtifact.name}（回流报错集）` }]
      : []),
    ...datasets
      .filter((item) => item.id !== calibrationArtifact?.id)
      .map((item) => ({ value: item.id, label: item.name })),
  ];

  // 部署工况列（挂载 fail-closed 校验用）：读不到则不传（服务端按缺省处理）
  useEffect(() => {
    if (!deploymentId) {
      setConditionColumn(null);
      return;
    }
    let cancelled = false;
    fetchFleetOverview(deploymentId)
      .then((data) => { if (!cancelled) setConditionColumn(data?.condition_column ?? null); })
      .catch(() => { if (!cancelled) setConditionColumn(null); });
    return () => { cancelled = true; };
  }, [deploymentId]);

  const runRecalibrate = async () => {
    if (!sourceVersionId || busy) return;
    const artifact = selectedArtifactId;
    const condition = conditionValue.trim();
    if (!artifact || !condition) {
      setError(!artifact ? "请选择标定数据集" : "请填写工况值（设备号/工位号）");
      return;
    }
    setBusy(true);
    setError(null);
    setMounted(null);
    setMountError(null);
    try {
      setResult(await recalibrateDeviceVersion(sourceVersionId, {
        calibration_artifact_id: artifact,
        condition_value: condition,
      }));
      message.success("M9 设备重标定完成");
    } catch (err) {
      setError(formatApiError(err, "M9 设备重标定失败"));
    } finally {
      setBusy(false);
    }
  };

  const runMount = async () => {
    if (!deploymentId || !result || busy) return;
    if (result.unfit_for_fleet || !result.fleet_fit?.compatible) {
      // §7.2「不硬迁」：unfit 版本不得挂载为机群分片——界面层拒绝，不调 API
      const reason = "该迁移版本被判定为机群不适配（unfit），按 §7.2「不硬迁」不可挂载：请为该设备独立建模或补充标定数据后重试";
      setMountError(reason);
      message.error(reason);
      return;
    }
    setBusy(true);
    setMountError(null);
    try {
      const payload: FleetShardCreatePayload = {
        model_version_id: result.version_id,
        condition_value: conditionValue.trim(),
        ...(conditionColumn ? { condition_column: conditionColumn } : {}),
        ...(rows != null && totalRows != null ? { rows, total_rows: totalRows } : {}),
      };
      setMounted(await addFleetShard(deploymentId, payload));
      message.success("迁移版本已挂载为部署分片");
    } catch (err) {
      setMountError(formatApiError(err, "挂载分片失败"));
    } finally {
      setBusy(false);
    }
  };

  if (!sourceVersionId) return null;
  const unfit = result ? (result.unfit_for_fleet || !result.fleet_fit?.compatible) : false;
  const fleetFpr = result?.fleet_fit?.fleet_fpr ?? null;

  return (
    <div style={{ border: "1px solid var(--v2-line, #eee)", borderRadius: 8, padding: "8px 12px", marginBottom: 12 }}>
      <Space direction="vertical" style={{ width: "100%" }} size="small">
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <Text strong style={{ fontSize: 13 }}>M9 新设备重标定（纯正常数据 → fleet_fit 判定 → 迁移版本）</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>源版本 {sourceVersionId}</Text>
        </Space>
        <Space wrap size={8}>
          <Select
            style={{ width: 220 }}
            size="small"
            placeholder="标定数据集"
            value={selectedArtifactId ?? undefined}
            options={artifactOptions}
            onChange={(value) => setArtifactId(String(value))}
          />
          <Input
            style={{ width: 200 }}
            size="small"
            maxLength={128}
            placeholder="工况值（设备号/工位号）"
            value={conditionValue}
            onChange={(event) => setConditionValue(event.target.value)}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>工况列：{conditionColumn ?? "device_id（缺省）"}</Text>
          <Button size="small" type="primary" loading={busy} onClick={() => void runRecalibrate()}>
            执行 M9 设备重标定
          </Button>
        </Space>
        {error && <Alert type="warning" showIcon message={error} />}
        {result && (
          <Alert
            type={unfit ? "warning" : "success"}
            showIcon
            message={(
              <span>
                M9 设备重标定完成（工况值 {conditionValue.trim()}）：
                {unfit ? <Text strong>机群不适配（unfit）</Text> : <Text strong>机群兼容</Text>}
                （fleet_fpr {fleetFpr == null ? "—" : fleetFpr} / 容差 {result.fleet_fit?.tolerance ?? "—"}），
                迁移版本 <Text strong>{result.registered_model_name}</Text>（{result.version_id}），
                标定阈值 {result.threshold_score}，标定样本 {result.calibration_rows} 行
              </span>
            )}
            description={unfit
              ? "按 §7.2「不硬迁」：版本仍产出但标记 unfit_for_fleet，禁止挂载为机群分片；建议该设备独立建模或补充标定数据后重试。"
              : `迁移版本状态 pending，需先在模型库审批（approve）后再挂载；回测 AUC ${result.backtest?.synthetic_auc ?? "—"}、留出 ${result.backtest?.holdout_rows ?? "—"} 行`}
          />
        )}
        {result && (
          <Space wrap size={8}>
            <InputNumber
              size="small" min={0} style={{ width: 130 }}
              placeholder="新分片行数" value={rows}
              onChange={(value) => setRows(typeof value === "number" ? value : null)}
            />
            <InputNumber
              size="small" min={0} style={{ width: 130 }}
              placeholder="总分片行数" value={totalRows}
              onChange={(value) => setTotalRows(typeof value === "number" ? value : null)}
            />
            <Button
              size="small"
              danger={unfit}
              loading={busy}
              disabled={!deploymentId}
              onClick={() => void runMount()}
            >
              {unfit ? "挂载为部署分片（unfit 将被拒绝）" : "挂载为部署分片"}
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>填行数按比例分配权重（§6.3）</Text>
          </Space>
        )}
        {mountError && <Alert type="error" showIcon message={mountError} />}
        {mounted && (
          <Alert
            type="success"
            showIcon
            message={`已挂载为部署分片：revision r${mounted.revision_number}（共 ${mounted.targets.length} 个分片）`}
          />
        )}
      </Space>
    </div>
  );
}

export default function DemoLoopDetailPage() {
  const { loopId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project") || "";
  const navigate = useNavigate();
  const { t } = useI18n();
  const tr = ((t as unknown as Record<string, Record<string, string | undefined>>).demo_loop ?? {}) as Record<string, string | undefined>;

  const [loop, setLoop] = useState<DemoLoopConfig | null>(null);
  const [loops, setLoops] = useState<DemoLoopConfig[]>([]);
  const [status, setStatus] = useState<DemoLoopStatus | null>(null);
  const [deployments, setDeployments] = useState<Array<{ id: string; name: string; observed_state: string }>>([]);
  const [datasets, setDatasets] = useState<Array<{ id: string; name: string }>>([]);
  const [annotators, setAnnotators] = useState<Array<{ id: string; username: string }>>([]);
  const [fieldDescTasks, setFieldDescTasks] = useState<FieldDescTask[]>([]);
  const [editor, setEditor] = useState<LoopEditorState | null>(null);

  const [rows, setRows] = useState<ParsedRow[]>([]);
  const [fileName, setFileName] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  // M6 半监督档 1（技术方案 §6.2）：标签阈值重标定 + 弱监督派生导出入口状态
  const [m6Busy, setM6Busy] = useState(false);
  const [m6Result, setM6Result] = useState<LabelRecalibrateResult | null>(null);
  const [m6Error, setM6Error] = useState<string | null>(null);
  const [derivedInfo, setDerivedInfo] = useState<DerivedSupervisedDatasetResult | null>(null);

  const runLabelRecalibrate = async () => {
    if (!status?.swapped_model_version_id || !status?.error_artifact?.id || m6Busy) return;
    setM6Busy(true);
    setM6Error(null);
    try {
      setM6Result(await labelRecalibrateVersion(status.swapped_model_version_id, {
        labeled_artifact_id: status.error_artifact.id,
      }));
      message.success("M6 档 1 阈值重标定完成，新版本待审批后挂载");
      void loadLoop();
    } catch (error) {
      setM6Error(formatApiError(error, "M6 操作失败"));
    } finally {
      setM6Busy(false);
    }
  };

  const runDeriveSupervised = async () => {
    if (!status?.swapped_model_version_id || !status?.error_artifact?.id || m6Busy) return;
    setM6Busy(true);
    setM6Error(null);
    try {
      setDerivedInfo(await deriveSupervisedDataset(status.swapped_model_version_id, {
        labeled_artifact_id: status.error_artifact.id,
      }));
      message.success("派生监督数据集已生成（数据管理可见）");
    } catch (error) {
      setM6Error(formatApiError(error, "M6 操作失败"));
    } finally {
      setM6Busy(false);
    }
  };
  const [results, setResults] = useState<Array<{ index: number; prediction: string; confidence: number | null; error: boolean; appended: boolean; failed?: boolean }>>([]);
  const pauseRef = useRef(false);
  const swapSeenRef = useRef<string | null>(null);
  const [swapPulse, setSwapPulse] = useState(false);

  const loadLoop = useCallback(async () => {
    if (!projectId || !loopId) return;
    try {
      const [loopsRes, dep, ds, ann] = await Promise.all([
        fetchDemoLoops(projectId).catch(() => ({ items: [] })),
        fetchDemoLoopDeployments(projectId).catch(() => ({ items: [] })),
        fetchDemoLoopDatasets(projectId).catch(() => ({ items: [] })),
        fetchDemoLoopAnnotators(projectId).catch(() => ({ items: [] })),
      ]);
      const items: DemoLoopConfig[] = loopsRes?.items || [];
      setLoops(items);
      setLoop(items.find((item) => item.id === loopId) || null);
      setDeployments((dep?.items || []).map((item: any) => ({
        id: item.id, name: item.name, observed_state: item.observed_state,
        target_columns: item.target_columns,
      })));
      setDatasets((ds?.items || []).map((item: any) => ({ id: item.id, name: item.name })));
      setAnnotators((ann?.items || []).map((item: any) => ({ id: item.id, username: item.username })));
    } catch (error) {
      message.error(formatApiError(error, tr.load_failed || "闭环数据加载失败"));
    }
  }, [projectId, loopId]);

  useEffect(() => { loadLoop(); }, [loadLoop]);

  // 详情页状态：挂载立即拉一次，此后按 2s 轮询（均绑定路由任务）。
  useEffect(() => {
    if (!projectId || !loopId) return;
    fetchDemoLoopStatusScoped(projectId, loopId)
      .then((st: DemoLoopStatus) => setStatus(st))
      .catch(() => undefined);
    const timer = setInterval(async () => {
      try {
        const st: DemoLoopStatus = await fetchDemoLoopStatusScoped(projectId, loopId);
        setStatus(st);
        if (st.swapped_model_version_id && st.swapped_model_version_id !== swapSeenRef.current) {
          swapSeenRef.current = st.swapped_model_version_id;
          setSwapPulse(true);
          setTimeout(() => setSwapPulse(false), 1600);
          fetchDemoLoops(projectId).then((res: any) => {
            const items: DemoLoopConfig[] = res?.items || [];
            setLoops(items);
            setLoop((prev) => (prev ? items.find((item) => item.id === prev.id) || prev : prev));
          }).catch(() => undefined);
        }
      } catch { /* transient poll errors are non-fatal */ }
    }, 2000);
    return () => clearInterval(timer);
  }, [projectId, loopId]);

  const handleUpload = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const parsed = parseCsv(String(reader.result || ""));
      setRows(parsed);
      setResults([]);
      setProgress(0);
      setFileName(file.name);
      if (!parsed.length) message.warning(tr.no_rows || "文件中没有可用数据行");
    };
    reader.readAsText(file);
    return false;
  };

  const runLoop = async () => {
    if (!rows.length || running || !loopId) return;
    pauseRef.current = false;
    setRunning(true);
    const MAX_RETRY = 3;               // 瞬态失败（网络/5xx）单行重试次数
    const CONSECUTIVE_LIMIT = 10;      // 连续失败达到该行数才终止（服务不可用）
    let consecutiveFailures = 0;
    let failedRows = 0;
    let stoppedByFailures = false;
    try {
      for (let i = 0; i < rows.length; i += 1) {
        if (pauseRef.current) break;
        let result: DemoLoopPredictResult | null = null;
        let lastError: unknown = null;
        for (let attempt = 0; attempt <= MAX_RETRY; attempt += 1) {
          try {
            result = await predictDemoLoopRowScoped(projectId, loopId, rows[i].values);
            break;
          } catch (error: any) {
            lastError = error;
            const requestStatus = error?.response?.status;
            // 4xx 属于数据/请求本身的问题（如特征列含空值），重试无意义
            if (requestStatus && requestStatus < 500 && requestStatus !== 429) break;
            if (attempt < MAX_RETRY) await new Promise((resolve) => setTimeout(resolve, 1000));
          }
        }
        if (pauseRef.current) break;
        if (!result) {
          // 重试仍失败：跳过该行并在结果面板标记，不中断整个回放
          consecutiveFailures += 1;
          failedRows += 1;
          const reason = formatApiError(lastError, tr.call_failed || "调用失败");
          const detail = reason.length > 80 ? `${reason.slice(0, 80)}…` : reason;
          setResults((prev) => [...prev.slice(-29), {
            index: rows[i].__index,
            prediction: detail,
            confidence: null,
            error: true,
            appended: false,
            failed: true,
          }]);
          if (consecutiveFailures >= CONSECUTIVE_LIMIT) {
            stoppedByFailures = true;
            message.error((tr.consecutive_stop || "连续 {n} 行调用失败，闭环已停止，请检查推理服务与网络后重试").replace("{n}", String(CONSECUTIVE_LIMIT)));
            break;
          }
          continue;
        }
        consecutiveFailures = 0;
        const current = result;
        setResults((prev) => [...prev.slice(-29), {
          index: rows[i].__index,
          prediction: current.prediction,
          confidence: current.confidence,
          error: current.error_matched,
          appended: current.appended,
        }]);
        setStatus((prev) => prev && ({
          ...prev,
          error_count: current.error_count,
          alert_count: current.alert_count,
          retrain_status: current.retrain_status,
        }));
        setProgress(Math.round(((i + 1) / rows.length) * 100));
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      if (!stoppedByFailures && failedRows > 0) {
        message.warning((tr.playback_done || "回放结束：{n} 行调用失败已跳过（详见结果面板）").replace("{n}", String(failedRows)));
      }
    } catch (error) {
      message.error(formatApiError(error, tr.call_failed_stop || "单行调用失败，闭环已停止"));
    } finally {
      setRunning(false);
      fetchDemoLoopStatusScoped(projectId, loopId).then((st: any) => setStatus(st)).catch(() => undefined);
      loadLoop();
    }
  };

  const handleReset = async () => {
    try {
      const st: any = await resetDemoLoopScoped(projectId, loopId);
      setStatus(st);
      setResults([]);
      setProgress(0);
      message.success(tr.reset_done || "闭环状态已重置");
    } catch (error) {
      message.error(formatApiError(error, tr.reset_failed || "重置失败"));
    }
  };

  const errorCount = status?.error_count ?? 0;
  const totalCount = status?.total_count ?? 0;
  const alertThreshold = loop?.alert_threshold_rows ?? 1;
  const retrainThreshold = loop?.retrain_threshold_rows ?? 0;
  // 重训模式感知：agent=智能体全流程重训（重放验收后换模，特征工程随配方更新）；
  // engine=引擎直接重训换模。状态卡/事件文案/换模提示按模式区分。
  const isAgentMode = (loop?.retrain_mode ?? status?.retrain_mode ?? "engine") === "agent";
  const lastEvent = status?.events?.[status.events.length - 1];
  const lastEventAgeMs = lastEvent ? (Date.now() - (parseBackendTime(lastEvent.created_at)?.getTime() ?? Number.NaN)) : Number.NaN;
  const alertActive = (status?.alert_count ?? 0) > 0 && loop?.alert_threshold_rows === 1
    ? true
    : (lastEvent?.event_type === "alert_triggered" && Number.isFinite(lastEventAgeMs) && lastEventAgeMs < 30000);

  return (
    <AppLayout>
      <style>{`
        @keyframes demoRowIn { from { opacity: 0; transform: translateX(18px); } to { opacity: 1; transform: none; } }
        .demo-row-item { animation: demoRowIn .38s ease; }
        @keyframes demoAlertPulse { 0%,100% { box-shadow: 0 0 0 0 rgba(255,77,79,.45); } 50% { box-shadow: 0 0 0 10px rgba(255,77,79,0); } }
        .demo-alert-pulse { animation: demoAlertPulse 1.4s ease infinite; }
        @keyframes demoSwapGlow { 0% { transform: rotateY(90deg); opacity: .2; } 100% { transform: rotateY(0); opacity: 1; } }
        .demo-swap-card { animation: demoSwapGlow 1.1s ease; transform-origin: center; }
      `}</style>

      <PageHeading
        section="algo"
        parent={{ navKey: "demo_loop", to: "/demo-loop" }}
        title={loop?.name || tr.detail_title || "闭环任务详情"}
        actions={(
          <>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/demo-loop`)}>{tr.back_to_list || "返回任务列表"}</Button>
            <Button icon={<EditOutlined />} disabled={running || !loop}
              onClick={async () => {
                if (loop) {
                  setEditor({ mode: "edit", loop });
                  try {
                    const tasksRes: any = await listAnnotationTasks(projectId, 50);
                    const tasks = tasksRes?.items || tasksRes || [];
                    setFieldDescTasks((Array.isArray(tasks) ? tasks : [])
                      .filter((task: any) => Object.keys(task.task_snapshot?.field_descriptions || {}).length > 0)
                      .map((task: any) => ({
                        id: task.id,
                        name: task.name || task.id.slice(0, 8),
                        descriptions: task.task_snapshot?.field_descriptions || {},
                      })));
                  } catch { setFieldDescTasks([]); }
                }
              }}>{tr.edit_config || "编辑配置"}</Button>
            <Button icon={<ReloadOutlined />} onClick={() => { loadLoop(); }}>{tr.refresh || "刷新"}</Button>
            <Button icon={<MonitorOutlined />}
              onClick={() => window.open(`/demo-showcase.html`, "_blank")}>
              {tr.showcase || "运行监控大屏"}
            </Button>
            <Button danger icon={<RestOutlined />} onClick={handleReset} disabled={!loop}>{tr.reset || "重置闭环"}</Button>
          </>
        )}
      />

      <Row gutter={16}>
        <Col span={14}>
          <Card title={(
            <>
              <UploadOutlined /> {tr.playback || "逐行推理调用"}
              <Tag color="blue" style={{ marginLeft: 8 }}>{loop?.name ?? "..."}</Tag>
            </>
          )} size="small">
            <Space direction="vertical" style={{ width: "100%" }} size="middle">
              <Upload accept=".csv" maxCount={1} beforeUpload={handleUpload} showUploadList={false}>
                <Button icon={<UploadOutlined />} disabled={!loop}>
                  {tr.upload || "上传 CSV 数据"}
                </Button>
              </Upload>
              {fileName && <Text type="secondary">{fileName} · {rows.length} {tr.rows || "行"}</Text>}
              <Space>
                <Button type="primary" icon={<CaretRightOutlined />} onClick={runLoop}
                  loading={running} disabled={!rows.length || !loop}>
                  {running ? (tr.running || "运行中...") : (tr.start || "启动闭环")}
                </Button>
                <Button icon={<PauseOutlined />} onClick={() => { pauseRef.current = true; }} disabled={!running}>
                  {tr.pause || "暂停"}
                </Button>
              </Space>
              <Progress percent={progress} status={running ? "active" : undefined} />
              {alertActive && (
                <Alert
                  className="demo-alert-pulse"
                  type="error" showIcon
                  message={(tr.alert_banner || "管理员告警：报错数据达到阈值（已告警 {n} 次）").replace("{n}", String(status?.alert_count ?? 0))}
                  description={tr.alert_desc || "已发送站内通知，可在右上角通知中心查看。"}
                />
              )}
              <div style={{ maxHeight: 360, overflowY: "auto" }}>
                {results.map((item) => (
                  <div key={item.index} className="demo-row-item"
                    style={{
                      display: "flex", justifyContent: "space-between", padding: "4px 10px",
                      borderRadius: 6, marginBottom: 4,
                      background: item.error ? "rgba(255,77,79,.08)" : "rgba(82,196,26,.06)",
                    }}>
                    <Text>{(tr.row_prefix || "第 {n} 行").replace("{n}", String(item.index))} · {item.failed ? (tr.call_failed_colon || "调用失败：") : (tr.predicted || "预测 ")}<Text strong>{item.prediction}</Text>
                      {item.confidence !== null && item.confidence !== undefined ? ` · ${(tr.confidence || "置信度 {p}%").replace("{p}", (item.confidence * 100).toFixed(1))}` : null}</Text>
                    {item.failed ? <Tag color="red">{tr.tag_failed || "调用失败"}</Tag> : item.appended ? <Tag color="red">{tr.tag_appended || "已回流"}</Tag> : <Tag color="green">{tr.tag_normal || "正常"}</Tag>}
                  </div>
                ))}
              </div>
            </Space>
          </Card>
        </Col>

        <Col span={10}>
          <Card title={(
            <>
              <DeploymentUnitOutlined /> {tr.status || "闭环状态"}
              <Tag color="blue" style={{ marginLeft: 8 }}>{loop?.name ?? "..."}</Tag>
            </>
          )} size="small">
            <Space direction="vertical" style={{ width: "100%" }} size="middle">
              <Row gutter={12}>
                <Col span={6}><Statistic title={tr.stat_inferred || "已推理"} value={totalCount} /></Col>
                <Col span={6}><Statistic title={tr.stat_reflow || "回流行数"} value={errorCount} valueStyle={{ color: errorCount ? "#cf1322" : undefined }} /></Col>
                <Col span={6}><Statistic title={tr.stat_alerts || "告警次数"} value={status?.alert_count ?? 0} /></Col>
                <Col span={6}>
                  <Statistic title={isAgentMode ? (tr.stat_agent_retrain || "智能体重训") : (tr.stat_retrain || "自动建模")} valueRender={() => (
                    <Tag color={status?.retrain_status === "completed" ? "green"
                      : status?.retrain_status === "failed" ? "red"
                        : status?.retrain_status === "agent_running" ? "geekblue"
                          : status?.retrain_status === "running" || status?.retrain_status === "queued" ? "blue" : "default"}
                      style={{ marginTop: 8 }}>
                      {status?.retrain_status === "completed" ? (isAgentMode ? (tr.retrain_done_agent || "已验收换模") : (tr.retrain_done || "已完成")) : status?.retrain_status === "failed" ? (tr.retrain_failed || "失败")
                        : status?.retrain_status === "agent_running" ? (tr.retrain_agent_running || "智能体重训中") : status?.retrain_status === "running" ? (tr.retrain_running || "执行中") : status?.retrain_status === "queued" ? (tr.retrain_queued || "已排队") : (tr.retrain_idle || "空闲")}
                    </Tag>
                  )} />
                </Col>
              </Row>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>{(tr.alert_progress || "告警进度（{e}/{t}）").replace("{e}", String(errorCount)).replace("{t}", String(alertThreshold))}</Text>
                <Progress percent={Math.min(100, alertThreshold ? (errorCount % alertThreshold || (errorCount ? alertThreshold : 0)) / alertThreshold * 100 : 0)}
                  showInfo={false} size="small" strokeColor="#fa8c16" />
                {retrainThreshold > 0 && (
                  <>
                    {/* 增量触发：进度按「未消费报错」（error_count - 已部署模型消费基线）计 */}
                    <Text type="secondary" style={{ fontSize: 12 }}>{(tr.retrain_progress || "重训进度（{e}/{t}）").replace("{e}", String(Math.max(0, errorCount - (status?.retrain_trained_baseline_count ?? 0)))).replace("{t}", String(retrainThreshold))}</Text>
                    <Progress percent={Math.min(100, Math.max(0, errorCount - (status?.retrain_trained_baseline_count ?? 0)) / retrainThreshold * 100)}
                      showInfo={false} size="small" strokeColor="#722ed1" />
                  </>
                )}
              </div>
              {status?.error_artifact && (
                <Text>{tr.error_file || "报错数据文件："}<a href="/data">{status.error_artifact.name}</a> · {status.error_artifact.row_count} {tr.rows_unit || "行"}</Text>
              )}
              {status?.review_task_id && (
                <Alert type="info" showIcon message={<a href="/annotations">{tr.review_created || "人工审核任务已创建，前往标注工作台"}</a>} />
              )}
              {status?.retrain_job_id && (
                <Alert type="info" showIcon message={<a href={`/automl/task/${status.retrain_job_id}`}>{isAgentMode ? (tr.view_casting || "查看铸造任务（重放验收后的部署模型）") : (tr.view_retrain || "查看自动建模任务")}</a>} />
              )}
              {/* 无监督漂移治理（技术方案 §3.6）：PSI 状态展示 + 报警行确认反馈 */}
              {status?.psi_enabled && (
                <Alert
                  type={status?.psi_state?.level === "alert" ? "warning" : "info"}
                  showIcon
                  message={(
                    <span>
                      分数漂移 PSI（阈值 {status?.psi_threshold ?? 0.25}）：
                      <Text strong>{status?.psi_state?.psi ?? "—"}</Text>
                      <Tag color={status?.psi_state?.level === "alert" ? "orange" : status?.psi_state?.level === "watch" ? "gold" : "green"} style={{ marginLeft: 6 }}>
                        {status?.psi_state?.level === "alert" ? "漂移预警" : status?.psi_state?.level === "watch" ? "观察" : status?.psi_state?.level === "no_data" ? "无回流分数" : "稳定"}
                      </Tag>
                      <Text type="secondary" style={{ fontSize: 12 }}>（样本 {status?.psi_state?.sample_count ?? 0} 行）</Text>
                    </span>
                  )}
                />
              )}
              {/* 机群分片概览（技术方案 §7 三-3，三期 M10）：分片部署时展示
                  per-device 阈值/兼容性/回测 + PSI 分片明细；普通部署不渲染 */}
              <FleetShardPanel deploymentId={status?.deployment_id ?? null} />
              {/* M6 半监督档 1（技术方案 §6.2）：确认标注回流上做标签阈值
                  重标定（confirmed≥50 门槛 fail-closed）与弱监督派生导出
                  （§2.3.3）——机制就绪，confirmed 积累到位即可用 */}
              {status?.swapped_model_version_id && status?.error_artifact && (
                <Space style={{ marginBottom: 12 }}>
                  <Button
                    size="small"
                    disabled={m6Busy}
                    onClick={() => void runLabelRecalibrate()}
                  >
                    M6 档 1 阈值重标定（confirmed≥50）
                  </Button>
                  <Button
                    size="small"
                    disabled={m6Busy}
                    onClick={() => void runDeriveSupervised()}
                  >
                    派生监督数据集
                  </Button>
                </Space>
              )}
              {m6Result && (
                <Alert
                  type="success"
                  showIcon
                  message={(
                    <span>
                      M6 重标定完成：阈值 {m6Result.old_threshold ?? "—"} → <Text strong>{m6Result.new_threshold}</Text>
                      （loss {m6Result.loss}，confirmed {m6Result.confirmed_count} / 误报 {m6Result.false_alarm_count}），
                      新版本 {m6Result.registered_model_name}（待审批后挂载）
                    </span>
                  )}
                  description={(
                    <Space direction="vertical" size={4} style={{ width: "100%" }}>
                      {/* 误报形态报表（技术方案 §3.2 G3 结果展示项）：按形态簇给出
                          样本数与密集特征（feature + mean_z），供误标质量诊断 */}
                      <Text strong style={{ fontSize: 12 }}>
                        误报形态报表（样本 {m6Result.false_alarm_report?.sample_count ?? 0}）
                      </Text>
                      <Table
                        size="small"
                        pagination={false}
                        rowKey={(row) => String(row.cluster)}
                        dataSource={m6Result.false_alarm_report?.clusters ?? []}
                        locale={{ emptyText: "无误报形态簇" }}
                        columns={[
                          { title: "形态簇", dataIndex: "cluster", width: 72 },
                          { title: "样本数", dataIndex: "sample_count", width: 72 },
                          {
                            title: "密集特征（mean_z）",
                            key: "dense_features",
                            render: (_value, row) => (
                              <Space size={4} wrap>
                                {(row.dense_features ?? []).length === 0
                                  ? <Text type="secondary">—</Text>
                                  : row.dense_features.map((item) => (
                                    <Tag key={item.feature} style={{ fontSize: 11 }}>
                                      {item.feature} {item.mean_z}
                                    </Tag>
                                  ))}
                              </Space>
                            ),
                          },
                        ]}
                      />
                      <Text style={{ fontSize: 12 }}>
                        派生版本：
                        {derivedInfo ? (
                          <a href={`/data?projectId=${projectId}`}>
                            {derivedInfo.dataset_name}（artifact {derivedInfo.dataset_artifact_id}）
                          </a>
                        ) : (
                          <Text type="secondary">尚未派生（点「派生监督数据集」导出弱监督演进数据集）</Text>
                        )}
                      </Text>
                    </Space>
                  )}
                  style={{ marginBottom: 12 }}
                />
              )}
              {m6Error && (
                <Alert type="warning" showIcon message={m6Error} style={{ marginBottom: 12 }} />
              )}
              {derivedInfo && (
                <Alert
                  type="info"
                  showIcon
                  message={(
                    <span>
                      派生监督数据集已生成（{derivedInfo.positives} 正 / {derivedInfo.negatives} 负），
                      可在数据管理中查看并创建监督分类任务（弱监督演进）
                    </span>
                  )}
                  description={(
                    <a href={`/data?projectId=${projectId}`}>
                      {derivedInfo.dataset_name}（artifact {derivedInfo.dataset_artifact_id}，{derivedInfo.rows} 行，标签列 {derivedInfo.label_column}）
                    </a>
                  )}
                  style={{ marginBottom: 12 }}
                />
              )}
              {/* M9 新设备重标定 + 迁移版本挂载（技术方案 §7.2 / §7.1.4，三期 M9）：
                  新设备纯正常数据 → fleet_fit 判定 → 迁移版本挂载为部署分片 */}
              <DeviceRecalibratePanel
                deploymentId={status?.deployment_id ?? loop?.deployment_id ?? null}
                sourceVersionId={status?.swapped_model_version_id ?? null}
                calibrationArtifact={status?.error_artifact ?? null}
                datasets={datasets}
              />
              {/* 运行期误报实证（技术方案 §3.3 第三层）：同一批回流行上阈值法
                  vs 模型报警累计对比（判据④的运行期持续口径） */}
              {status?.alert_comparison && (
                <Alert
                  type="info"
                  showIcon
                  message={(
                    <span>
                      运行期报警对比（回流 {status.alert_comparison.rows} 行）：
                      阈值法 <Text strong>{status.alert_comparison.threshold_alerts}</Text> 次
                      （{status.alert_comparison.threshold_alert_rate != null ? `${(status.alert_comparison.threshold_alert_rate * 100).toFixed(2)}%` : "—"}）
                      · 异常检测 <Text strong>{status.alert_comparison.model_alerts}</Text> 次
                      （{status.alert_comparison.model_alert_rate != null ? `${(status.alert_comparison.model_alert_rate * 100).toFixed(2)}%` : "—"}）
                    </span>
                  )}
                />
              )}
              <ReflowFeedbackPanel projectId={projectId} loopId={loopId} />
              <div style={{ maxHeight: 320, overflowY: "auto" }}>
                <Timeline
                  items={(status?.events || []).slice().reverse().map((event) => ({
                    color: EVENT_COLORS[event.event_type] || "gray",
                    children: (
                      <div className={event.event_type === "model_swapped" ? "demo-swap-card" : undefined}>
                        <Text strong style={{ fontSize: 13 }}>
                          {event.event_type === "model_swapped" && !isAgentMode
                            ? (tr.ev_model_swapped_engine || "推理模型已替换")
                            : tr[`ev_${event.event_type}`] || EVENT_LABELS[event.event_type] || event.event_type}
                        </Text>
                        <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                          {event.message}
                          {event.created_at ? ` · ${parseBackendTime(event.created_at)?.toLocaleTimeString() ?? ""}` : ""}
                        </div>
                      </div>
                    ),
                  }))}
                />
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      <LoopConfigModal
        editor={editor}
        projectId={projectId}
        deployments={deployments}
        datasets={datasets}
        annotators={annotators}
        fieldDescTasks={fieldDescTasks}
        onCancel={() => setEditor(null)}
        onSaved={(saved) => { setEditor(null); setLoop(saved); void loadLoop(); }}
      />
    </AppLayout>
  );
}
