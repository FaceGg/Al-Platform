import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, Button, Card, Col, message, Progress, Row, Space, Statistic, Tag, Timeline, Typography, Upload,
} from "antd";
import {
  ArrowLeftOutlined, CaretRightOutlined, DeploymentUnitOutlined, EditOutlined,
  MonitorOutlined, PauseOutlined, ReloadOutlined, ThunderboltOutlined, UploadOutlined,
} from "@ant-design/icons";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import AppLayout from "../components/AppLayout";
import LoopConfigModal, { type LoopEditorState } from "../components/loop/LoopConfigModal";
import { formatApiError } from "../api/client";
import {
  type DemoLoopConfig, type DemoLoopPredictResult, type DemoLoopStatus,
  fetchDemoLoopAnnotators, fetchDemoLoopDatasets, fetchDemoLoopDeployments,
  fetchDemoLoops, fetchDemoLoopStatusScoped, predictDemoLoopRowScoped,
  resetDemoLoopScoped,
} from "../api/demoLoop";
import { useI18n } from "../i18n";
import { parseBackendTime } from "../utils/time";

const { Title, Text } = Typography;

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
  model_swapped: "gold", swap_failed: "red", loop_reset: "blue",
};
const EVENT_LABELS: Record<string, string> = {
  row_predicted: "正常预测", error_row: "命中报错类别", error_appended: "错误数据回流",
  alert_triggered: "触发管理员告警", review_task_created: "创建人工审核任务",
  retrain_triggered: "自动建模已触发", retrain_running: "自动建模执行中",
  retrain_completed: "自动建模完成", retrain_failed: "自动建模失败",
  model_swapped: "推理模型已替换", swap_failed: "模型替换失败", loop_reset: "闭环重置",
};

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
  const [editor, setEditor] = useState<LoopEditorState | null>(null);

  const [rows, setRows] = useState<ParsedRow[]>([]);
  const [fileName, setFileName] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [results, setResults] = useState<Array<{ index: number; prediction: string; confidence: number | null; error: boolean; appended: boolean }>>([]);
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
      })));
      setDatasets((ds?.items || []).map((item: any) => ({ id: item.id, name: item.name })));
      setAnnotators((ann?.items || []).map((item: any) => ({ id: item.id, username: item.username })));
    } catch (error) {
      message.error(formatApiError(error, "闭环数据加载失败"));
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
    try {
      for (let i = 0; i < rows.length; i += 1) {
        if (pauseRef.current) break;
        const result: DemoLoopPredictResult = await predictDemoLoopRowScoped(projectId, loopId, rows[i].values);
        setResults((prev) => [...prev.slice(-29), {
          index: rows[i].__index,
          prediction: result.prediction,
          confidence: result.confidence,
          error: result.error_matched,
          appended: result.appended,
        }]);
        setStatus((prev) => prev && ({
          ...prev,
          error_count: result.error_count,
          alert_count: result.alert_count,
          retrain_status: result.retrain_status,
        }));
        setProgress(Math.round(((i + 1) / rows.length) * 100));
        await new Promise((resolve) => setTimeout(resolve, 240));
      }
    } catch (error) {
      message.error(formatApiError(error, "单行调用失败，闭环已停止"));
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
      message.error(formatApiError(error, "重置失败"));
    }
  };

  const errorCount = status?.error_count ?? 0;
  const totalCount = status?.total_count ?? 0;
  const alertThreshold = loop?.alert_threshold_rows ?? 1;
  const retrainThreshold = loop?.retrain_threshold_rows ?? 0;
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

      <Card style={{ marginBottom: 16 }}>
        <Space wrap size="large">
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/demo-loop`)}>返回任务列表</Button>
          <Title level={3} style={{ margin: 0 }}>
            <DeploymentUnitOutlined /> {loop?.name || "闭环任务详情"}
          </Title>
          <Button icon={<EditOutlined />} disabled={running || !loop}
            onClick={() => loop && setEditor({ mode: "edit", loop })}>编辑配置</Button>
          <Button icon={<ReloadOutlined />} onClick={() => { loadLoop(); }}>刷新</Button>
          <Button type="primary" ghost icon={<MonitorOutlined />}
            onClick={() => window.open(`/demo-showcase.html`, "_blank")}>
            {tr.showcase || "运行监控大屏"}
          </Button>
          <Button danger onClick={handleReset} disabled={!loop}>{tr.reset || "重置闭环"}</Button>
        </Space>
      </Card>

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
                    <Text>第 {item.index} 行 · 预测 <Text strong>{item.prediction}</Text>
                      {item.confidence !== null && item.confidence !== undefined ? ` · 置信度 ${(item.confidence * 100).toFixed(1)}%` : null}</Text>
                    {item.appended ? <Tag color="red">已回流</Tag> : <Tag color="green">正常</Tag>}
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
                <Col span={6}><Statistic title="已推理" value={totalCount} /></Col>
                <Col span={6}><Statistic title="回流行数" value={errorCount} valueStyle={{ color: errorCount ? "#cf1322" : undefined }} /></Col>
                <Col span={6}><Statistic title="告警次数" value={status?.alert_count ?? 0} /></Col>
                <Col span={6}>
                  <Statistic title="自动建模" valueRender={() => (
                    <Tag color={status?.retrain_status === "completed" ? "green"
                      : status?.retrain_status === "failed" ? "red"
                        : status?.retrain_status === "running" || status?.retrain_status === "queued" ? "blue" : "default"}
                      style={{ marginTop: 8 }}>
                      {status?.retrain_status === "completed" ? "已完成" : status?.retrain_status === "failed" ? "失败"
                        : status?.retrain_status === "running" ? "执行中" : status?.retrain_status === "queued" ? "已排队" : "空闲"}
                    </Tag>
                  )} />
                </Col>
              </Row>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>告警进度（{errorCount}/{alertThreshold}）</Text>
                <Progress percent={Math.min(100, alertThreshold ? (errorCount % alertThreshold || (errorCount ? alertThreshold : 0)) / alertThreshold * 100 : 0)}
                  showInfo={false} size="small" strokeColor="#fa8c16" />
                {retrainThreshold > 0 && (
                  <>
                    <Text type="secondary" style={{ fontSize: 12 }}>重训进度（{errorCount}/{retrainThreshold}）</Text>
                    <Progress percent={Math.min(100, errorCount / retrainThreshold * 100)}
                      showInfo={false} size="small" strokeColor="#722ed1" />
                  </>
                )}
              </div>
              {status?.error_artifact && (
                <Text>报错数据文件：<a href="/data">{status.error_artifact.name}</a> · {status.error_artifact.row_count} 行</Text>
              )}
              {status?.review_task_id && (
                <Alert type="info" showIcon message={<a href="/annotations">人工审核任务已创建，前往标注工作台</a>} />
              )}
              {status?.retrain_job_id && (
                <Alert type="info" showIcon message={<a href={`/automl/task/${status.retrain_job_id}`}>查看自动建模任务</a>} />
              )}
              <div style={{ maxHeight: 320, overflowY: "auto" }}>
                <Timeline
                  items={(status?.events || []).slice().reverse().map((event) => ({
                    color: EVENT_COLORS[event.event_type] || "gray",
                    children: (
                      <div className={event.event_type === "model_swapped" ? "demo-swap-card" : undefined}>
                        <Text strong style={{ fontSize: 13 }}>{EVENT_LABELS[event.event_type] || event.event_type}</Text>
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
        onCancel={() => setEditor(null)}
        onSaved={(saved) => { setEditor(null); setLoop(saved); void loadLoop(); }}
      />
    </AppLayout>
  );
}
