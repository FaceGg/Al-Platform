import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, Button, Card, Col, Divider, Form, Input, InputNumber, message, Progress,
  Row, Select, Space, Statistic, Switch, Tag, Timeline, Typography, Upload,
} from "antd";
import {
  CaretRightOutlined, DeploymentUnitOutlined, PauseOutlined, ReloadOutlined,
  ThunderboltOutlined, UploadOutlined,
} from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import { formatApiError } from "../api/client";
import {
  DemoLoopConfig, DemoLoopPredictResult, DemoLoopStatus,
  fetchDemoLoopAnnotators, fetchDemoLoopConfig, fetchDemoLoopDatasets,
  fetchDemoLoopDeployments, fetchDemoLoopProjects, fetchDemoLoopStatus,
  predictDemoLoopRow, resetDemoLoop, saveDemoLoopConfig,
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
  info: "blue", warning: "orange", critical: "red",
};
const EVENT_LABELS: Record<string, string> = {
  row_predicted: "正常预测",
  error_row: "命中报错类别",
  error_dataset_created: "创建报错数据集",
  error_appended: "错误数据回流",
  alert_triggered: "触发管理员告警",
  review_task_created: "创建人工审核任务",
  review_skipped: "跳过人工审核",
  review_task_failed: "审核任务失败",
  retrain_triggered: "自动建模已触发",
  retrain_running: "自动建模执行中",
  retrain_completed: "自动建模完成",
  retrain_failed: "自动建模失败",
  model_swapped: "推理模型已替换",
  swap_failed: "模型替换失败",
  loop_reset: "闭环重置",
};

export default function DemoLoopPage() {
  const { t } = useI18n();
  const tr = ((t as unknown as Record<string, Record<string, string | undefined>>).demo_loop ?? {}) as Record<string, string | undefined>;
  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [config, setConfig] = useState<DemoLoopConfig | null>(null);
  const [status, setStatus] = useState<DemoLoopStatus | null>(null);
  const [deployments, setDeployments] = useState<Array<{ id: string; name: string; observed_state: string }>>([]);
  const [datasets, setDatasets] = useState<Array<{ id: string; name: string }>>([]);
  const [annotators, setAnnotators] = useState<Array<{ id: string; username: string }>>([]);
  const [rows, setRows] = useState<ParsedRow[]>([]);
  const [fileName, setFileName] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [results, setResults] = useState<Array<{ index: number; prediction: string; confidence: number | null; error: boolean; appended: boolean }>>([]);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const pauseRef = useRef(false);
  const alertSeenRef = useRef(0);
  const swapSeenRef = useRef<string | null>(null);
  const [swapPulse, setSwapPulse] = useState(false);

  useEffect(() => {
    fetchDemoLoopProjects().then((res: any) => {
      const items = res.items || [];
      setProjects(items);
      if (items.length) setProjectId(items[0].id);
    }).catch((error) => message.error(formatApiError(error, "项目加载失败")));
  }, []);

  const loadProjectData = useCallback(async (pid: string) => {
    if (!pid) return;
    try {
      const [cfg, st, dep, ds, ann] = await Promise.all([
        fetchDemoLoopConfig(pid).catch(() => null),
        fetchDemoLoopStatus(pid).catch(() => null),
        fetchDemoLoopDeployments(pid).catch(() => ({ items: [] })),
        fetchDemoLoopDatasets(pid).catch(() => ({ items: [] })),
        fetchDemoLoopAnnotators(pid).catch(() => ({ items: [] })),
      ]);
      setConfig(cfg);
      setStatus(st);
      setDeployments((dep?.items || []).map((item: any) => ({
        id: item.id, name: item.name, observed_state: item.observed_state,
      })));
      setDatasets((ds?.items || []).map((item: any) => ({ id: item.id, name: item.name })));
      setAnnotators((ann?.items || []).map((item: any) => ({ id: item.id, username: item.username })));
      if (cfg) {
        form.setFieldsValue({
          name: cfg.name, deployment_id: cfg.deployment_id, error_classes: cfg.error_classes,
          preprocess_enabled: cfg.preprocess_enabled, alert_threshold_rows: cfg.alert_threshold_rows,
          require_review: cfg.require_review, review_annotator_ids: cfg.review_annotator_ids,
          retrain_enabled: cfg.retrain_enabled, retrain_threshold_rows: cfg.retrain_threshold_rows,
          retrain_dataset_artifact_id: cfg.retrain_dataset_artifact_id,
          retrain_target_column: cfg.retrain_target_column, retrain_max_trials: cfg.retrain_max_trials,
        });
        alertSeenRef.current = st?.alert_count ?? 0;
        swapSeenRef.current = cfg.swapped_model_version_id ?? null;
      }
    } catch (error) {
      message.error(formatApiError(error, "闭环数据加载失败"));
    }
  }, [form]);

  useEffect(() => { loadProjectData(projectId); }, [projectId, loadProjectData]);

  // Poll loop status so alerts / retrain progress / model swap stay live.
  useEffect(() => {
    if (!projectId || !config) return;
    const timer = setInterval(async () => {
      try {
        const st: DemoLoopStatus = await fetchDemoLoopStatus(projectId);
        setStatus(st);
        if ((st.alert_count ?? 0) > alertSeenRef.current) {
          alertSeenRef.current = st.alert_count ?? 0;
        }
        if (st.swapped_model_version_id && st.swapped_model_version_id !== swapSeenRef.current) {
          swapSeenRef.current = st.swapped_model_version_id;
          setSwapPulse(true);
          setTimeout(() => setSwapPulse(false), 1600);
          fetchDemoLoopConfig(projectId).then((cfg: any) => setConfig(cfg)).catch(() => undefined);
        }
      } catch { /* transient poll errors are non-fatal */ }
    }, 2000);
    return () => clearInterval(timer);
  }, [projectId, config]);

  const handleSave = async (values: any) => {
    setSaving(true);
    try {
      const cfg: any = await saveDemoLoopConfig(projectId, {
        ...values,
        error_classes: values.error_classes || [],
        review_annotator_ids: values.require_review ? values.review_annotator_ids || [] : [],
      });
      setConfig(cfg);
      message.success(tr.saved || "配置已保存");
      fetchDemoLoopStatus(projectId).then((st: any) => setStatus(st)).catch(() => undefined);
    } catch (error) {
      message.error(formatApiError(error, "配置保存失败"));
    } finally { setSaving(false); }
  };

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

  const runDemo = async () => {
    if (!rows.length || running) return;
    pauseRef.current = false;
    setRunning(true);
    try {
      // Persist the current form (e.g. the feature-engineering toggle) so the
      // loop always predicts with the switches the user sees on screen.
      const values = await form.validateFields();
      const cfg: any = await saveDemoLoopConfig(projectId, {
        ...values,
        error_classes: values.error_classes || [],
        review_annotator_ids: values.require_review ? values.review_annotator_ids || [] : [],
      });
      setConfig(cfg);
      alertSeenRef.current = 0;
    } catch (error) {
      setRunning(false);
      message.error(formatApiError(error, "配置保存失败，未启动闭环"));
      return;
    }
    try {
      for (let i = 0; i < rows.length; i += 1) {
        if (pauseRef.current) break;
        const result: DemoLoopPredictResult = await predictDemoLoopRow(projectId, rows[i].values);
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
      if (projectId) fetchDemoLoopStatus(projectId).then((st: any) => setStatus(st)).catch(() => undefined);
    }
  };

  const handleReset = async () => {
    try {
      const st: any = await resetDemoLoop(projectId);
      setStatus(st);
      setResults([]);
      setProgress(0);
      message.success(tr.reset_done || "闭环状态已重置");
    } catch (error) {
      message.error(formatApiError(error, "重置失败"));
    }
  };

  const errorCount = status?.error_count ?? 0;
  const alertThreshold = config?.alert_threshold_rows ?? 1;
  const retrainThreshold = config?.retrain_threshold_rows ?? 0;
  const lastEvent = status?.events?.[status.events.length - 1];
  const lastEventAgeMs = lastEvent ? (Date.now() - (parseBackendTime(lastEvent.created_at)?.getTime() ?? Number.NaN)) : Number.NaN;
  const alertActive = (status?.alert_count ?? 0) > 0 && config?.alert_threshold_rows === 1
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
          <Title level={3} style={{ margin: 0 }}>
            <DeploymentUnitOutlined /> {tr.title || "推理-回流-重训 自动化闭环"}
          </Title>
          <span>
            <Text type="secondary">{tr.project || "项目"}</Text>
            <Select
              style={{ minWidth: 220, marginLeft: 8 }}
              value={projectId || undefined}
              onChange={(value) => setProjectId(value)}
              options={projects.map((item) => ({ value: item.id, label: item.name }))}
              placeholder={tr.choose_project || "选择项目"}
            />
          </span>
          <Button icon={<ReloadOutlined />} onClick={() => loadProjectData(projectId)}>
            {tr.refresh || "刷新"}
          </Button>
          <Button type="primary" ghost onClick={() => window.open("/demo-showcase.html", "_blank")}>
            {tr.showcase || "运行监控大屏"}
          </Button>
          <Button danger onClick={handleReset} disabled={!config}>
            {tr.reset || "重置闭环"}
          </Button>
        </Space>
      </Card>

      <Row gutter={16}>
        <Col span={8}>
          <Card title={<><ThunderboltOutlined /> {tr.config || "闭环配置"}</>} size="small">
            {config === null && (
              <Alert type="info" showIcon
                message={tr.no_config || "当前项目尚未配置闭环，保存后自动创建"} style={{ marginBottom: 12 }} />
            )}
            <Form form={form} layout="vertical" onFinish={handleSave}>
              <Form.Item name="name" label={tr.name || "闭环名称"} initialValue="自动化闭环" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="deployment_id" label={tr.deployment || "推理部署"} rules={[{ required: true }]}>
                <Select options={deployments.map((item) => ({
                  value: item.id,
                  label: `${item.name}（${item.observed_state === "running" ? "运行中" : item.observed_state}）`,
                }))} placeholder={tr.choose_deployment || "选择推理部署"} />
              </Form.Item>
              <Form.Item name="error_classes" label={tr.error_classes || "报错类别（命中即回流）"} rules={[{ required: true }]}>
                <Select mode="tags" open={false} placeholder={tr.error_classes_hint || "输入类别后回车"} />
              </Form.Item>
              <Form.Item
                name="preprocess_enabled"
                label={tr.preprocess || "自动特征工程（原始点焊报告数据 → 73 特征）"}
                tooltip={tr.preprocess_hint || "开启后，上传原始点焊报告行（报告字段 + cvei/cvev/cver/cvep 波形列）会先经平台特征工程算子补齐派生列再做预测；改动需保存配置生效，启动闭环时也会自动保存"}
                valuePropName="checked"
              >
                <Switch />
              </Form.Item>
              <Form.Item name="alert_threshold_rows" label={tr.alert_threshold || "告警阈值（每 N 行报错触发一次）"} initialValue={1}>
                <InputNumber min={1} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item name="require_review" label={tr.require_review || "告警后人工审核"} valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item noStyle shouldUpdate={(prev, next) => prev.require_review !== next.require_review}>
                {({ getFieldValue }) => getFieldValue("require_review") ? (
                  <Form.Item name="review_annotator_ids" label={tr.annotators || "审核标注员"}>
                    <Select mode="multiple" options={annotators.map((item) => ({
                      value: item.id, label: item.username,
                    }))} placeholder={tr.choose_annotators || "选择标注员"} />
                  </Form.Item>
                ) : null}
              </Form.Item>
              <Divider plain style={{ margin: "8px 0" }}>{tr.retrain_section || "自动重训"}</Divider>
              <Form.Item name="retrain_enabled" label={tr.retrain_enabled || "积累后自动建模"} valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item noStyle shouldUpdate={(prev, next) => prev.retrain_enabled !== next.retrain_enabled}>
                {({ getFieldValue }) => getFieldValue("retrain_enabled") ? (
                  <>
                    <Form.Item name="retrain_threshold_rows" label={tr.retrain_threshold || "重训触发行数"} initialValue={20}>
                      <InputNumber min={1} style={{ width: "100%" }} />
                    </Form.Item>
                    <Form.Item name="retrain_dataset_artifact_id" label={tr.retrain_dataset || "重训数据集"} rules={[{ required: true }]}>
                      <Select options={datasets.map((item) => ({ value: item.id, label: item.name }))}
                        placeholder={tr.choose_dataset || "选择数据集"} />
                    </Form.Item>
                    <Form.Item name="retrain_target_column" label={tr.retrain_target || "目标列"} rules={[{ required: true }]}>
                      <Input />
                    </Form.Item>
                    <Form.Item name="retrain_max_trials" label={tr.retrain_trials || "搜索试验次数"} initialValue={10}>
                      <InputNumber min={5} max={200} style={{ width: "100%" }} />
                    </Form.Item>
                  </>
                ) : null}
              </Form.Item>
              <Button type="primary" htmlType="submit" block loading={saving} disabled={!projectId}>
                {tr.save || "保存配置"}
              </Button>
            </Form>
          </Card>
        </Col>

        <Col span={9}>
          <Card title={<><UploadOutlined /> {tr.playback || "逐行推理调用"}</>} size="small">
            <Space direction="vertical" style={{ width: "100%" }} size="middle">
              <Upload accept=".csv" maxCount={1} beforeUpload={handleUpload} showUploadList={false}>
                <Button icon={<UploadOutlined />} disabled={!config}>
                  {tr.upload || "上传 CSV 数据"}
                </Button>
              </Upload>
              {fileName && <Text type="secondary">{fileName} · {rows.length} {tr.rows || "行"}</Text>}
              <Space>
                <Button type="primary" icon={<CaretRightOutlined />} onClick={runDemo}
                  loading={running} disabled={!rows.length || !config}>
                  {running ? (tr.running || "运行中...") : (tr.start || "启动闭环")}
                </Button>
                <Button icon={<PauseOutlined />} onClick={() => { pauseRef.current = true; }}
                  disabled={!running}>
                  {tr.pause || "暂停"}
                </Button>
              </Space>
              <Progress percent={progress} status={running ? "active" : undefined} />
              {alertActive && (
                <Alert
                  className="demo-alert-pulse"
                  type="error"
                  showIcon
                  message={(tr.alert_banner || "管理员告警：报错数据达到阈值（已告警 {n} 次）").replace("{n}", String(status?.alert_count ?? 0))}
                  description={tr.alert_desc || "已发送站内通知，可在右上角通知中心查看。"}
                />
              )}
              <div style={{ maxHeight: 360, overflowY: "auto" }}>
                {results.length === 0 && <Text type="secondary">{tr.empty_results || "推理结果将在这里逐行展示"}</Text>}
                {[...results].reverse().map((item) => (
                  <div key={`${item.index}-${item.prediction}`} className="demo-row-item"
                    style={{
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      padding: "6px 10px", marginBottom: 6, borderRadius: 8,
                      background: item.error ? "rgba(255,77,79,.08)" : "rgba(82,196,26,.07)",
                      border: item.error ? "1px solid rgba(255,77,79,.35)" : "1px solid rgba(82,196,26,.3)",
                    }}>
                    <Text strong>#{item.index}</Text>
                    <Space>
                      <Tag color={item.error ? "red" : "green"}>{item.prediction}</Tag>
                      {item.confidence !== null && <Text type="secondary">{(item.confidence * 100).toFixed(1)}%</Text>}
                      {item.appended && <Tag color="volcano">{tr.appended || "已回流"}</Tag>}
                    </Space>
                  </div>
                ))}
              </div>
            </Space>
          </Card>
        </Col>

        <Col span={7}>
          <Card title={<><DeploymentUnitOutlined /> {tr.status || "闭环状态"}</>} size="small">
            <Row gutter={8}>
              <Col span={8}><Statistic title={tr.error_rows || "回流行数"} value={errorCount} /></Col>
              <Col span={8}><Statistic title={tr.alerts || "告警次数"} value={status?.alert_count ?? 0} /></Col>
              <Col span={8}>
                <Statistic title={tr.retrain_state || "自动建模"}
                  value={
                    { queued: "已排队", running: "执行中", completed: "已完成", failed: "失败" }[status?.retrain_status || "idle"] || "空闲"
                  }
                  valueStyle={{
                    fontSize: 18,
                    color: status?.retrain_status === "failed" ? "#cf1322" : undefined,
                  }} />
              </Col>
            </Row>
            <Divider style={{ margin: "12px 0" }} />
            {config && (
              <Space direction="vertical" style={{ width: "100%" }} size={4}>
                {config.alert_threshold_rows > 0 && (
                  <Progress type="dashboard" size={72}
                    percent={Math.min(100, Math.round((errorCount / config.alert_threshold_rows) * 100))}
                    format={() => `${errorCount}/${config.alert_threshold_rows}`} />
                )}
                {retrainThreshold > 0 && config.retrain_enabled && (
                  <Progress type="dashboard" size={72} strokeColor="#fa8c16"
                    percent={Math.min(100, Math.round((errorCount / retrainThreshold) * 100))}
                    format={() => `${errorCount}/${retrainThreshold}`} />
                )}
              </Space>
            )}
            {swapPulse && config?.current_model && (
              <Card size="small" className="demo-swap-card" style={{ marginTop: 12, borderColor: "#faad14" }}>
                <Text strong>{tr.swapped || "推理模型已替换"}</Text>
                <div>
                  <Text type="secondary">
                    {config.current_model.model_name || "-"} · v{config.current_model.version_number}
                  </Text>
                </div>
              </Card>
            )}
            {status?.review_task_id && (
              <Alert type="warning" showIcon style={{ marginTop: 12 }}
                message={<a href="/annotations">{tr.review_link || "人工审核任务已创建，前往标注工作台"}</a>} />
            )}
            {status?.retrain_job_id && (
              <Alert type="info" showIcon style={{ marginTop: 12 }}
                message={<a href={`/automl/task/${status.retrain_job_id}`}>{tr.retrain_link || "查看自动建模任务"}</a>} />
            )}
            {status?.error_artifact && (
              <div style={{ marginTop: 12 }}>
                <Text type="secondary">{tr.error_file || "报错数据文件"}</Text>
                <div>
                  <a href="/data">{status.error_artifact.name}</a>
                  <Text type="secondary"> · {status.error_artifact.row_count} 行</Text>
                </div>
              </div>
            )}
            <Divider style={{ margin: "12px 0" }} />
            <Timeline
              items={(status?.events || []).slice(-10).reverse().map((event) => ({
                color: EVENT_COLORS[event.severity] || "blue",
                children: (
                  <span>
                    <Tag>{EVENT_LABELS[event.event_type] || event.event_type}</Tag>
                    <Text type="secondary">{event.message}</Text>
                  </span>
                ),
              }))}
            />
          </Card>
        </Col>
      </Row>
    </AppLayout>
  );
}
