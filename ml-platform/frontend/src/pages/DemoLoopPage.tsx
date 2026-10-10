import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert, Button, Card, Col, Divider, Form, Input, InputNumber, message, Popconfirm,
  Progress, Row, Select, Space, Statistic, Switch, Tag, Timeline, Typography, Upload,
} from "antd";
import {
  CaretRightOutlined, DeleteOutlined, DeploymentUnitOutlined, PauseOutlined,
  PlusOutlined, ReloadOutlined, ThunderboltOutlined, UploadOutlined,
} from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import { formatApiError } from "../api/client";
import {
  DemoLoopConfig, DemoLoopPredictResult, DemoLoopStatus,
  createDemoLoop, deleteDemoLoop, fetchDemoLoopAnnotators, fetchDemoLoopDatasets,
  fetchDemoLoopDeployments, fetchDemoLoopProjects, fetchDemoLoops,
  fetchDemoLoopStatusScoped, predictDemoLoopRowScoped, resetDemoLoop,
  resetDemoLoopScoped, updateDemoLoop,
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
  const [loops, setLoops] = useState<DemoLoopConfig[]>([]);
  const [activeLoopId, setActiveLoopId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
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
  const creatingRef = useRef(false);
  const [swapPulse, setSwapPulse] = useState(false);

  useEffect(() => {
    fetchDemoLoopProjects().then((res: any) => {
      const items = res.items || [];
      setProjects(items);
      if (items.length) setProjectId(items[0].id);
    }).catch((error) => message.error(formatApiError(error, "项目加载失败")));
  }, []);

  const applyConfigToForm = useCallback((cfg: DemoLoopConfig, st: DemoLoopStatus | null) => {
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
  }, [form]);

  // 任务列表 + 参照数据（部署/数据集/标注员）
  const loadProjectData = useCallback(async (pid: string) => {
    if (!pid) return;
    try {
      const [loopsRes, dep, ds, ann] = await Promise.all([
        fetchDemoLoops(pid).catch(() => ({ items: [] })),
        fetchDemoLoopDeployments(pid).catch(() => ({ items: [] })),
        fetchDemoLoopDatasets(pid).catch(() => ({ items: [] })),
        fetchDemoLoopAnnotators(pid).catch(() => ({ items: [] })),
      ]);
      const items: DemoLoopConfig[] = loopsRes?.items || [];
      setLoops(items);
      setDeployments((dep?.items || []).map((item: any) => ({
        id: item.id, name: item.name, observed_state: item.observed_state,
      })));
      setDatasets((ds?.items || []).map((item: any) => ({ id: item.id, name: item.name })));
      setAnnotators((ann?.items || []).map((item: any) => ({ id: item.id, username: item.username })));
      setActiveLoopId((prev) => (prev && items.some((item) => item.id === prev) ? prev : items[0]?.id ?? null));
      if (!creatingRef.current) {
        // 新建草稿进行中（含初次加载未完成即点击新建）不重置创建状态。
        setCreating(false);
      }
    } catch (error) {
      message.error(formatApiError(error, "闭环数据加载失败"));
    }
  }, []);

  // 当前选中闭环的配置与状态（切换/新建后都会触发）
  useEffect(() => {
    if (!projectId || !activeLoopId) { setConfig(null); setStatus(null); return; }
    if (creatingRef.current) return; // 新建草稿模式不被异步选中结果覆盖
    let cancelled = false;
    (async () => {
      try {
        const st: DemoLoopStatus = await fetchDemoLoopStatusScoped(projectId, activeLoopId);
        // 完成点复查：等待期间进入新建草稿，则丢弃本次选中结果。
        if (cancelled || creatingRef.current) return;
        const cfg = loops.find((item) => item.id === activeLoopId) || null;
        setConfig(cfg);
        setStatus(st);
        applyConfigToForm(cfg as DemoLoopConfig, st);
      } catch (error) {
        if (!cancelled) {
          setConfig(null);
          setStatus(null);
          message.error(formatApiError(error, "闭环状态加载失败"));
        }
      }
    })();
    return () => { cancelled = true; };
  }, [projectId, activeLoopId, loops, applyConfigToForm]);

  // Poll active loop status so alerts / retrain progress / model swap stay live.
  useEffect(() => {
    if (!projectId || !activeLoopId) return;
    const timer = setInterval(async () => {
      try {
        const st: DemoLoopStatus = await fetchDemoLoopStatusScoped(projectId, activeLoopId);
        setStatus(st);
        if ((st.alert_count ?? 0) > alertSeenRef.current) {
          alertSeenRef.current = st.alert_count ?? 0;
        }
        if (st.swapped_model_version_id && st.swapped_model_version_id !== swapSeenRef.current) {
          swapSeenRef.current = st.swapped_model_version_id;
          setSwapPulse(true);
          setTimeout(() => setSwapPulse(false), 1600);
          fetchDemoLoops(projectId).then((res: any) => setLoops(res?.items || [])).catch(() => undefined);
        }
      } catch { /* transient poll errors are non-fatal */ }
    }, 2000);
    return () => clearInterval(timer);
  }, [projectId, activeLoopId]);

  const startCreate = () => {
    if (running) { message.warning("闭环运行中，请先暂停或等待结束"); return; }
    creatingRef.current = true;
    setCreating(true);
    setConfig(null);
    setStatus(null);
    form.resetFields();
    form.setFieldsValue({
      name: "自动化闭环", error_classes: [], preprocess_enabled: false,
      alert_threshold_rows: 1, require_review: false, review_annotator_ids: [],
      retrain_enabled: false, retrain_threshold_rows: 20, retrain_max_trials: 10,
    });
  };

  const handleSave = async (values: any) => {
    setSaving(true);
    const payload = {
      ...values,
      error_classes: values.error_classes || [],
      review_annotator_ids: values.require_review ? values.review_annotator_ids || [] : [],
    };
    try {
      const cfg: any = creating
        ? await createDemoLoop(projectId, payload)
        : await updateDemoLoop(projectId, activeLoopId as string, payload);
      message.success(creating ? (tr.created || "闭环任务已创建") : (tr.saved || "配置已保存"));
      const list: DemoLoopConfig[] = await fetchDemoLoops(projectId).then((res: any) => res?.items || []);
      setLoops(list);
      creatingRef.current = false;
      setCreating(false);
      setActiveLoopId(cfg.id);
      setConfig(cfg);
    } catch (error) {
      message.error(formatApiError(error, creating ? "闭环创建失败" : "配置保存失败"));
    } finally { setSaving(false); }
  };

  const handleDeleteLoop = async (loopId: string) => {
    if (running) { message.warning("闭环运行中，不能删除"); return; }
    try {
      await deleteDemoLoop(projectId, loopId);
      message.success(tr.deleted || "闭环任务已删除");
      const list: DemoLoopConfig[] = await fetchDemoLoops(projectId).then((res: any) => res?.items || []);
      setLoops(list);
      if (activeLoopId === loopId) {
        setActiveLoopId(list[0]?.id ?? null);
        if (!list.length) { setConfig(null); setStatus(null); }
      }
    } catch (error) {
      message.error(formatApiError(error, "删除失败"));
    }
  };

  useEffect(() => { loadProjectData(projectId); }, [projectId, loadProjectData]);

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
    if (!rows.length || running || !activeLoopId) return;
    pauseRef.current = false;
    setRunning(true);
    try {
      // Persist the current form (e.g. the feature-engineering toggle) so the
      // loop always predicts with the switches the user sees on screen.
      const values = await form.validateFields();
      const cfg: any = creating
        ? await createDemoLoop(projectId, {
          ...values,
          error_classes: values.error_classes || [],
          review_annotator_ids: values.require_review ? values.review_annotator_ids || [] : [],
        })
        : await updateDemoLoop(projectId, activeLoopId as string, {
          ...values,
          error_classes: values.error_classes || [],
          review_annotator_ids: values.require_review ? values.review_annotator_ids || [] : [],
        });
      setConfig(cfg);
      if (creating) {
        const list: DemoLoopConfig[] = await fetchDemoLoops(projectId).then((res: any) => res?.items || []);
        setLoops(list);
        setCreating(false);
        setActiveLoopId(cfg.id);
      }
      alertSeenRef.current = 0;
    } catch (error) {
      setRunning(false);
      message.error(formatApiError(error, "配置保存失败，未启动闭环"));
      return;
    }
    try {
      for (let i = 0; i < rows.length; i += 1) {
        if (pauseRef.current) break;
        const result: DemoLoopPredictResult = await predictDemoLoopRowScoped(projectId, activeLoopId as string, rows[i].values);
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
      if (projectId && activeLoopId) fetchDemoLoopStatusScoped(projectId, activeLoopId).then((st: any) => setStatus(st)).catch(() => undefined);
    }
  };

  const handleReset = async () => {
    try {
      const st: any = activeLoopId
        ? await resetDemoLoopScoped(projectId, activeLoopId)
        : await resetDemoLoop(projectId);
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
        .loop-task-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
        .loop-task-list { display: flex; flex-direction: column; gap: 4px; max-height: 168px; overflow-y: auto; margin-bottom: 10px; }
        .loop-task-item { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 5px 8px; border: 1px solid transparent; border-radius: 6px; cursor: pointer; background: rgba(0,0,0,.02); }
        .loop-task-item:hover { background: rgba(0,0,0,.05); }
        .loop-task-item--active { border-color: #1677ff; background: rgba(22,119,255,.08); }
        .loop-task-item__name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .loop-task-item__meta { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
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
            <div className="loop-task-toolbar">
              <Button size="small" type="primary" ghost icon={<PlusOutlined />}
                disabled={running} onClick={startCreate} data-testid="new-loop-btn">
                {tr.new_loop || "新建闭环"}
              </Button>
              <Text type="secondary">{tr.loop_count_hint || "点击列表切换，保存当前表单即修改"}</Text>
            </div>
            <div className="loop-task-list" data-testid="loop-task-list">
              {loops.length === 0 && !creating && (
                <Text type="secondary">暂无闭环任务，点击「新建闭环」创建</Text>
              )}
              {loops.map((loop) => (
                <div
                  key={loop.id}
                  className={"loop-task-item" + (loop.id === activeLoopId && !creating ? " loop-task-item--active" : "")}
                  onClick={() => { if (!running) { creatingRef.current = false; setCreating(false); setActiveLoopId(loop.id); } }}
                >
                  <span className="loop-task-item__name">
                    {loop.id === activeLoopId && !creating ? <ThunderboltOutlined /> : null} {loop.name}
                  </span>
                  <span className="loop-task-item__meta">
                    <Tag color={loop.error_count > 0 ? "orange" : "default"}>回流 {loop.error_count ?? 0}</Tag>
                    <Tag color={loop.retrain_status === "completed" ? "green" : loop.retrain_status === "failed" ? "red" : "default"}>
                      {loop.retrain_status === "completed" ? "已换模" : loop.retrain_status === "failed" ? "重训失败" : loop.retrain_status === "running" || loop.retrain_status === "queued" ? "重训中" : "未重训"}
                    </Tag>
                    <Popconfirm
                      title="删除该闭环任务？"
                      description="事件与计数一并删除，报错数据文件保留。"
                      onConfirm={(event) => { event?.stopPropagation(); handleDeleteLoop(loop.id); }}
                      onCancel={(event) => event?.stopPropagation()}
                    >
                      <Button
                        size="small" type="text" danger icon={<DeleteOutlined />}
                        disabled={running}
                        onClick={(event) => event.stopPropagation()}
                      />
                    </Popconfirm>
                  </span>
                </div>
              ))}
            </div>
            {creating && (
              <Alert type="info" showIcon message="正在新建闭环任务，填写后点「创建闭环」" style={{ margin: "10px 0" }} />
            )}
            {!creating && config === null && loops.length > 0 && (
              <Alert type="warning" showIcon message="闭环配置加载失败，请刷新重试" style={{ margin: "10px 0" }} />
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
                {creating ? (tr.create || "创建闭环") : (tr.save || "保存配置")}
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
