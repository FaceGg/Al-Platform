import { useEffect, useRef, useState } from "react";
import { Button, Divider, Form, Input, InputNumber, Modal, Select, Space, Switch, Upload, Typography } from "antd";
import { useI18n } from "../../i18n";
import { createDemoLoop, updateDemoLoop, type DemoLoopConfig } from "../../api/demoLoop";
import { apiGet, formatApiError } from "../../api/client";
import { message } from "antd";

export type LoopEditorState =
  | { mode: "create"; defaults?: Partial<Record<string, unknown>> }
  | { mode: "edit"; loop: DemoLoopConfig };

/** 可复用字段解释的标注任务（task_snapshot.field_descriptions 非空） */
export interface FieldDescTask {
  id: string;
  name: string;
  descriptions: Record<string, string>;
}

interface Props {
  editor: LoopEditorState | null;
  projectId: string;
  deployments: Array<{ id: string; name: string; observed_state: string }>;
  datasets: Array<{ id: string; name: string }>;
  annotators: Array<{ id: string; username: string }>;
  fieldDescTasks?: FieldDescTask[];
  onCancel: () => void;
  onSaved: (loop: DemoLoopConfig) => void;
}

const FEATURE_OPERATOR_IDS = [
  "spot_weld_feature_engineering",
  "tighten_feature_engineering",
  "auto_feature_engineering",
];

const FEATURE_MODE_OPTIONS = [
  { value: "legacy", label: "内置点焊特征桥（原始点焊报告数据 → 73 特征）" },
  { value: "operator", label: "工作流特征工程算子（沿用节点已保存参数）" },
  { value: "script", label: "Python 脚本自定义（与 python_script 算子同接口）" },
];

/** 「特征工程」类别下的算子（与算子面板分类一致，随平台算子扩展自动更新） */
async function fetchFeatureOperatorIds(): Promise<Set<string>> {
  try {
    const data = await apiGet("/operators");
    const ops = Array.isArray(data) ? data : data.items || [];
    const ids = new Set<string>(
      ops.filter((op: any) => op.category === "feature_engineering").map((op: any) => op.id),
    );
    if (ids.size > 0) return ids;
  } catch {
    // 拉取失败时退回内置清单
  }
  return new Set<string>(FEATURE_OPERATOR_IDS);
}

async function fetchPythonScriptTemplate(): Promise<string> {
  try {
    const data = await apiGet("/operators");
    const ops = Array.isArray(data) ? data : data.items || [];
    const scriptOp = ops.find((op: any) => op.id === "python_script");
    return scriptOp?.parameters?.find((p: any) => p.name === "script")?.default || "";
  } catch {
    return "";
  }
}

const RATIO_OPTIONS: Array<{ value: string; label: string }> = [
  ...Array.from({ length: 9 }, (_, i) => ({
    value: `${10 - i}:1`, label: `错误:正确 = ${10 - i}:1（多收正确数据）`,
  })),
  { value: "1:1", label: "错误:正确 = 1:1" },
  ...Array.from({ length: 9 }, (_, i) => ({
    value: `1:${i + 2}`, label: `错误:正确 = 1:${i + 2}（多收报错数据）`,
  })),
];

export default function LoopConfigModal({ editor, projectId, deployments, datasets, annotators, fieldDescTasks, onCancel, onSaved }: Props) {
  const { t } = useI18n();
  const tr = ((t as unknown as Record<string, Record<string, string | undefined>>).demo_loop ?? {}) as Record<string, string | undefined>;
  const [form] = Form.useForm();
  const [feNodeOptions, setFeNodeOptions] = useState<Array<{ value: string; label: string }>>([]);
  const [feNodesLoading, setFeNodesLoading] = useState(false);
  const scriptTemplateRef = useRef("");
  const featureMode = Form.useWatch("feature_engineering_mode", form);

  // 打开弹窗时：按「特征工程」类别过滤项目工作流中的算子节点（operator 模式选项）
  useEffect(() => {
    if (!editor) return;
    let cancelled = false;
    setFeNodesLoading(true);
    (async () => {
      const feIds = await fetchFeatureOperatorIds();
      try {
        const wfList = await apiGet(`/projects/${projectId}/workflows`);
        // apiGet 已解包响应体：工作流列表是纯数组，详情含 nodes
        const workflows: Array<{ id: string; name: string }> = Array.isArray(wfList)
          ? wfList : wfList?.items || [];
        const options: Array<{ value: string; label: string }> = [];
        for (const wf of workflows) {
          try {
            const detail = await apiGet(`/workflows/${wf.id}`);
            for (const node of detail?.nodes || []) {
              if (feIds.has(node.operator_id)) {
                options.push({
                  value: String(node.id),
                  label: `${wf.name} · ${node.label || node.operator_id}（${node.operator_id}）`,
                });
              }
            }
          } catch {
            // 单个工作流拉取失败不影响其它选项
          }
        }
        if (!cancelled) setFeNodeOptions(options);
      } catch {
        if (!cancelled) setFeNodeOptions([]);
      } finally {
        if (!cancelled) setFeNodesLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [editor, projectId]);

  // 切到脚本模式且脚本为空时，用 python_script 算子的默认模板预填（与后端强校验保持同步）
  useEffect(() => {
    if (featureMode !== "script" || !editor) return;
    const current = (form.getFieldValue("feature_script") as string || "").trim();
    if (current) return;
    (async () => {
      if (!scriptTemplateRef.current) {
        scriptTemplateRef.current = await fetchPythonScriptTemplate();
      }
      if (scriptTemplateRef.current && !(form.getFieldValue("feature_script") as string || "").trim()) {
        form.setFieldsValue({ feature_script: scriptTemplateRef.current });
      }
    })();
  }, [featureMode, editor, form]);

  useEffect(() => {
    if (!editor) return;
    form.resetFields();
    if (editor.mode === "edit") {
      const cfg = editor.loop;
      form.setFieldsValue({
        name: cfg.name, deployment_id: cfg.deployment_id, error_classes: cfg.error_classes,
        preprocess_enabled: cfg.preprocess_enabled,
        feature_engineering_mode: cfg.feature_engineering_mode || "legacy",
        feature_operator_node_id: cfg.feature_operator_node_id || undefined,
        feature_script: cfg.feature_script || undefined,
        alert_threshold_rows: cfg.alert_threshold_rows,
        require_review: cfg.require_review, review_annotator_ids: cfg.review_annotator_ids,
        retrain_enabled: cfg.retrain_enabled, retrain_threshold_rows: cfg.retrain_threshold_rows,
        retrain_dataset_artifact_ids: cfg.retrain_dataset_artifact_ids
          || (cfg.retrain_dataset_artifact_id ? [cfg.retrain_dataset_artifact_id] : []),
        retrain_target_column: cfg.retrain_target_column, retrain_max_trials: cfg.retrain_max_trials,
        collect_correct_enabled: cfg.collect_correct_enabled,
        correct_sample_ratio: cfg.correct_sample_ratio || "1:1",
        field_descriptions: cfg.field_descriptions || {},
      });
    } else {
      form.setFieldsValue({
        name: "自动化闭环", error_classes: [], preprocess_enabled: false,
        feature_engineering_mode: "legacy", feature_operator_node_id: undefined,
        feature_script: undefined,
        alert_threshold_rows: 1, require_review: false, review_annotator_ids: [],
        retrain_enabled: false, retrain_threshold_rows: 20, retrain_dataset_artifact_ids: [],
        retrain_max_trials: 10, ...(editor.defaults || {}),
        collect_correct_enabled: false, correct_sample_ratio: "1:1", field_descriptions: {},
      });
    }
  }, [editor, form]);

  const handleSave = async (values: Record<string, unknown>) => {
    const payload = {
      ...values,
      error_classes: (values.error_classes as string[]) || [],
      review_annotator_ids: values.require_review ? (values.review_annotator_ids as string[]) || [] : [],
      collect_correct_enabled: !!values.collect_correct_enabled,
      correct_sample_ratio: values.collect_correct_enabled
        ? String(values.correct_sample_ratio || "1:1") : "1:1",
      // 字段解释由上传/复用经 setFieldValue 写入（无注册 Form.Item），需显式从 store 读取
      field_descriptions: (form.getFieldValue("field_descriptions") as Record<string, string>) || {},
    };
    try {
      const cfg: any = editor?.mode === "create"
        ? await createDemoLoop(projectId, payload)
        : await updateDemoLoop(projectId, (editor?.mode === "edit" && editor.loop.id) as string, payload);
      // 后端保证同项目任务名唯一（重名自动 -2/-3）；提示展示实际名称。
      const submittedName = String(values.name ?? "");
      const finalName = String(cfg?.name ?? submittedName);
      const suffix = finalName !== submittedName ? `（重名，已自动命名为 ${finalName}）` : "";
      message.success((editor?.mode === "create" ? (tr.created || "闭环任务已创建") : (tr.saved || "配置已保存")) + suffix);
      onSaved(cfg as DemoLoopConfig);
    } catch (error) {
      message.error(formatApiError(error, editor?.mode === "create" ? "闭环创建失败" : "配置保存失败"));
    }
  };

  return (
    <Modal
      open={editor !== null}
      title={editor?.mode === "create" ? "新建闭环任务" : `编辑闭环配置：${editor?.mode === "edit" ? editor.loop.name : ""}`}
      onCancel={onCancel}
      footer={null}
      width={560}
      destroyOnClose
    >
      <Form form={form} layout="vertical" onFinish={handleSave} style={{ marginTop: 12 }}>
        <Form.Item name="name" label={tr.name || "闭环名称"} rules={[{ required: true }]}>
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
          name="feature_engineering_mode"
          label={tr.preprocess || "特征工程方式"}
          initialValue="legacy"
          tooltip="上传数据缺少模型特征列时的自动补齐方式：内置点焊桥 / 复用工作流特征工程算子节点 / 自写 Python 脚本"
        >
          <Select options={FEATURE_MODE_OPTIONS} />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.feature_engineering_mode !== next.feature_engineering_mode}>
          {({ getFieldValue }) => {
            const mode = getFieldValue("feature_engineering_mode") || "legacy";
            if (mode === "operator") {
              return (
                <Form.Item
                  name="feature_operator_node_id"
                  label="特征工程算子节点"
                  rules={[{ required: true, message: "请选择工作流中的特征工程算子节点" }]}
                  tooltip="按所选节点已保存的参数执行特征工程（与训练时配置保持一致）"
                >
                  <Select
                    showSearch
                    optionFilterProp="label"
                    loading={feNodesLoading}
                    options={feNodeOptions}
                    placeholder={feNodesLoading ? "正在加载工作流算子节点…" : "选择工作流中的特征工程算子节点"}
                    notFoundContent="本项目工作流中未找到特征工程算子节点"
                  />
                </Form.Item>
              );
            }
            if (mode === "script") {
              return (
                <Form.Item
                  name="feature_script"
                  label="特征工程 Python 脚本"
                  rules={[{ required: true, message: "请填写特征工程脚本" }]}
                  tooltip="与 python_script 算子相同的固定输入输出接口：输入 df（单行记录的 DataFrame），在 process(df) 中补齐模型特征列并返回；缺失依赖库按平台白名单源自动安装"
                >
                  <Input.TextArea
                    rows={14}
                    style={{ fontFamily: "monospace", fontSize: 12 }}
                  />
                </Form.Item>
              );
            }
            return (
              <Form.Item>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  上传原始点焊报告行（报告字段 + cvei/cvev/cver/cvep 波形列）时会先经内置特征桥补齐 73 特征再做预测；拧紧等其它场景请切换为「工作流特征工程算子」或「Python 脚本」。
                </Typography.Text>
              </Form.Item>
            );
          }}
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
        <Divider plain style={{ margin: "8px 0" }}>数据收集</Divider>
        <Form.Item
          name="collect_correct_enabled"
          label="同步收集正确数据"
          valuePropName="checked"
          tooltip="回流报错行时，按比例自动并入缓冲中的正常预测行（重新平衡重训数据的正负样本）"
        >
          <Switch />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.collect_correct_enabled !== next.collect_correct_enabled}>
          {({ getFieldValue }) => getFieldValue("collect_correct_enabled") ? (
            <Form.Item
              name="correct_sample_ratio"
              label="错误:正确 收集比例"
              initialValue="1:1"
              rules={[{ required: true, message: "请选择收集比例" }]}
            >
              <Select options={RATIO_OPTIONS} />
            </Form.Item>
          ) : null}
        </Form.Item>
        <Divider plain style={{ margin: "8px 0" }}>字段解释</Divider>
        <Form.Item label="复用已有标注任务的字段解释（可选）">
          <Select
            allowClear
            placeholder={(fieldDescTasks || []).length ? "选择标注任务" : "暂无带字段解释的标注任务"}
            disabled={!(fieldDescTasks || []).length}
            options={(fieldDescTasks || []).map((task) => ({
              value: task.id,
              label: `${task.name}（${Object.keys(task.descriptions).length} 个字段）`,
            }))}
            onSelect={(taskId: string) => {
              const task = (fieldDescTasks || []).find((item) => item.id === taskId);
              if (task) form.setFieldValue("field_descriptions", { ...task.descriptions });
            }}
          />
        </Form.Item>
        <Form.Item label="或上传字段解释文件（csv/txt，每行：字段名,描述）">
          <Upload
            accept=".csv,.txt"
            maxCount={1}
            showUploadList={false}
            beforeUpload={(file) => {
              void file.text().then((text) => {
                const descriptions: Record<string, string> = {};
                for (const rawLine of text.split(/\r?\n/)) {
                  const line = rawLine.trim();
                  if (!line) continue;
                  const separators = [line.indexOf(","), line.indexOf("\t")].filter((index) => index >= 0);
                  if (!separators.length) continue;
                  const cut = Math.min(...separators);
                  const name = line.slice(0, cut).trim();
                  const description = line.slice(cut + 1).trim();
                  if (name) descriptions[name] = description;
                }
                if (Object.keys(descriptions).length) {
                  form.setFieldValue("field_descriptions", descriptions);
                  message.success(`已解析 ${Object.keys(descriptions).length} 个字段说明`);
                } else {
                  message.error("未从文件中解析到任何「字段名,描述」行");
                }
              });
              return false;
            }}
          >
            <Button>选择文件</Button>
          </Upload>
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.field_descriptions !== next.field_descriptions}>
          {({ getFieldValue }) => {
            const descriptions = (getFieldValue("field_descriptions") as Record<string, string>) || {};
            const count = Object.keys(descriptions).length;
            return (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {count ? `已配置 ${count} 个字段解释，将展示在标注员工作区的对应字段旁` : "未配置字段解释"}
              </Typography.Text>
            );
          }}
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
              <Form.Item
                name="retrain_dataset_artifact_ids"
                label={tr.retrain_dataset || "重训数据集（可多选合并训练；选报错数据时自动用推理结果作标签）"}
                rules={[{ required: true, message: "请选择至少一个重训数据集" }]}
              >
                <Select mode="multiple" options={datasets.map((item) => ({ value: item.id, label: item.name }))}
                  placeholder={tr.choose_dataset || "选择数据集（可多选）"} />
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
        <Space style={{ width: "100%", justifyContent: "flex-end" }}>
          <Button onClick={onCancel}>取消</Button>
          <Button type="primary" htmlType="submit" disabled={!projectId}>
            {editor?.mode === "create" ? (tr.create || "创建闭环") : (tr.save || "保存配置")}
          </Button>
        </Space>
      </Form>
    </Modal>
  );
}
