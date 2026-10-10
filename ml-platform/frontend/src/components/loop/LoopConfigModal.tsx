import { useEffect } from "react";
import { Button, Divider, Form, Input, InputNumber, Modal, Select, Space, Switch } from "antd";
import { useI18n } from "../../i18n";
import { createDemoLoop, updateDemoLoop, type DemoLoopConfig } from "../../api/demoLoop";
import { formatApiError } from "../../api/client";
import { message } from "antd";

export type LoopEditorState =
  | { mode: "create"; defaults?: Partial<Record<string, unknown>> }
  | { mode: "edit"; loop: DemoLoopConfig };

interface Props {
  editor: LoopEditorState | null;
  projectId: string;
  deployments: Array<{ id: string; name: string; observed_state: string }>;
  datasets: Array<{ id: string; name: string }>;
  annotators: Array<{ id: string; username: string }>;
  onCancel: () => void;
  onSaved: (loop: DemoLoopConfig) => void;
}

export default function LoopConfigModal({ editor, projectId, deployments, datasets, annotators, onCancel, onSaved }: Props) {
  const { t } = useI18n();
  const tr = ((t as unknown as Record<string, Record<string, string | undefined>>).demo_loop ?? {}) as Record<string, string | undefined>;
  const [form] = Form.useForm();

  useEffect(() => {
    if (!editor) return;
    form.resetFields();
    if (editor.mode === "edit") {
      const cfg = editor.loop;
      form.setFieldsValue({
        name: cfg.name, deployment_id: cfg.deployment_id, error_classes: cfg.error_classes,
        preprocess_enabled: cfg.preprocess_enabled, alert_threshold_rows: cfg.alert_threshold_rows,
        require_review: cfg.require_review, review_annotator_ids: cfg.review_annotator_ids,
        retrain_enabled: cfg.retrain_enabled, retrain_threshold_rows: cfg.retrain_threshold_rows,
        retrain_dataset_artifact_ids: cfg.retrain_dataset_artifact_ids
          || (cfg.retrain_dataset_artifact_id ? [cfg.retrain_dataset_artifact_id] : []),
        retrain_target_column: cfg.retrain_target_column, retrain_max_trials: cfg.retrain_max_trials,
      });
    } else {
      form.setFieldsValue({
        name: "自动化闭环", error_classes: [], preprocess_enabled: false,
        alert_threshold_rows: 1, require_review: false, review_annotator_ids: [],
        retrain_enabled: false, retrain_threshold_rows: 20, retrain_dataset_artifact_ids: [],
        retrain_max_trials: 10, ...(editor.defaults || {}),
      });
    }
  }, [editor, form]);

  const handleSave = async (values: Record<string, unknown>) => {
    const payload = {
      ...values,
      error_classes: (values.error_classes as string[]) || [],
      review_annotator_ids: values.require_review ? (values.review_annotator_ids as string[]) || [] : [],
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
          name="preprocess_enabled"
          label={tr.preprocess || "自动特征工程（原始点焊报告数据 → 73 特征）"}
          tooltip={tr.preprocess_hint || "开启后，上传原始点焊报告行（报告字段 + cvei/cvev/cver/cvep 波形列）会先经平台特征工程算子补齐派生列再做预测"}
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
