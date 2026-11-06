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
  deployments: Array<{ id: string; name: string; observed_state: string; target_columns?: string[] }>;
  datasets: Array<{ id: string; name: string }>;
  annotators: Array<{ id: string; username: string }>;
  fieldDescTasks?: FieldDescTask[];
  onCancel: () => void;
  onSaved: (loop: DemoLoopConfig) => void;
}

/** 特征工程方式选项；label 随语言。 */
function buildFeatureModeOptions(zh: boolean): Array<{ value: string; label: string }> {
  return zh ? [
    { value: "legacy", label: "内置点焊特征桥（原始点焊报告数据 → 73 特征）" },
    { value: "operator", label: "特征工程类别算子（面板「特征工程」类别，按默认参数执行）" },
    { value: "script", label: "Python 脚本自定义（与 python_script 算子同接口）" },
  ] : [
    { value: "legacy", label: "Built-in spot-weld bridge (raw report rows → 73 features)" },
    { value: "operator", label: "Feature-engineering operator (default parameters)" },
    { value: "script", label: "Custom Python script (same interface as python_script)" },
  ];
}

/** 「特征工程」类别下的算子（与算子面板分类一致，随平台算子扩展自动更新） */
async function fetchFeatureOperators(): Promise<Array<{ id: string; name: string }>> {
  try {
    const data = await apiGet("/operators");
    const ops = Array.isArray(data) ? data : data.items || [];
    return ops
      .filter((op: any) => op.category === "feature_engineering")
      .map((op: any) => ({ id: String(op.id), name: String(op.name || op.id) }));
  } catch {
    return [];
  }
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

/** 错误:正确 收集比例选项；label 随语言（zh 用「错误:正确」，en 用 "Error:Correct"）。 */
function buildRatioOptions(zh: boolean): Array<{ value: string; label: string }> {
  const prefix = zh ? "错误:正确" : "Error:Correct";
  return [
    ...Array.from({ length: 9 }, (_, i) => ({
      value: `${10 - i}:1`, label: `${prefix} = ${10 - i}:1`,
    })),
    { value: "1:1", label: `${prefix} = 1:1` },
    ...Array.from({ length: 9 }, (_, i) => ({
      value: `1:${i + 2}`, label: `${prefix} = 1:${i + 2}`,
    })),
  ];
}

/** 项目内固化配方（agent 重训模式绑定选择用）。 */
async function fetchAgentRecipes(projectId: string): Promise<Array<{ id: string; name: string; has_guidance: boolean; current_version: number }>> {
  try {
    const data = await apiGet(`/agent/recipes?project_id=${projectId}`);
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export default function LoopConfigModal({ editor, projectId, deployments, datasets, annotators, fieldDescTasks, onCancel, onSaved }: Props) {
  const { t, lang } = useI18n();
  const zh = (lang ?? "zh") === "zh";
  const tr = ((t as unknown as Record<string, Record<string, string | undefined>>).demo_loop ?? {}) as Record<string, string | undefined>;
  const [form] = Form.useForm();
  const [feOperatorOptions, setFeOperatorOptions] = useState<Array<{ value: string; label: string }>>([]);
  const [feOperatorsLoading, setFeOperatorsLoading] = useState(true);
  const [recipeOptions, setRecipeOptions] = useState<Array<{ value: string; label: string }>>([]);
  const scriptTemplateRef = useRef("");
  const featureMode = Form.useWatch("feature_engineering_mode", form);
  const retrainMode = Form.useWatch("retrain_mode", form);

  // 打开弹窗时：拉取项目内固化配方（agent 重训模式绑定选择用）
  useEffect(() => {
    if (!editor) return;
    let cancelled = false;
    fetchAgentRecipes(projectId).then((recipes) => {
      if (cancelled) return;
      setRecipeOptions(recipes.map((recipe) => ({
        value: recipe.id,
        label: `${recipe.name}（v${recipe.current_version}${recipe.has_guidance ? "" : "，" + (tr.recipe_no_guidance || "无重放快照") }）`,
      })));
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, projectId]);

  // 打开弹窗时：列出算子面板「特征工程」类别下的全部算子（operator 模式选项）
  useEffect(() => {
    if (!editor) return;
    let cancelled = false;
    fetchFeatureOperators().then((operators) => {
      if (cancelled) return;
      const operatorNames = ((t as unknown as Record<string, Record<string, string | undefined>>).operator ?? {}) as Record<string, string | undefined>;
      setFeOperatorOptions(operators.map((op) => ({
        value: op.id,
        label: `${operatorNames[op.id] || op.name}（${op.id}）`,
      })));
      setFeOperatorsLoading(false);
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor]);
  // EXPERIMENT-A: fetchFeatureOperators effect kept above

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
      // 重训数据集默认包含闭环收集的报错数据集；目标列默认取模型 label 列
      const retrainIds = new Set<string>(
        cfg.retrain_dataset_artifact_ids || (cfg.retrain_dataset_artifact_id ? [cfg.retrain_dataset_artifact_id] : []),
      );
      if (cfg.error_artifact_id) retrainIds.add(cfg.error_artifact_id);
      const defaultTarget = cfg.retrain_target_column
        || cfg.current_model?.target_columns?.[0] || "";
      form.setFieldsValue({
        name: cfg.name, deployment_id: cfg.deployment_id, error_classes: cfg.error_classes,
        preprocess_enabled: cfg.preprocess_enabled,
        feature_engineering_mode: cfg.feature_engineering_mode || "legacy",
        feature_operator_id: cfg.feature_operator_id || undefined,
        feature_script: cfg.feature_script || undefined,
        alert_threshold_rows: cfg.alert_threshold_rows,
        require_review: cfg.require_review, review_annotator_ids: cfg.review_annotator_ids,
        retrain_enabled: cfg.retrain_enabled, retrain_threshold_rows: cfg.retrain_threshold_rows,
        retrain_dataset_artifact_ids: [...retrainIds],
        retrain_target_column: defaultTarget, retrain_max_trials: cfg.retrain_max_trials,
        retrain_ensemble_enabled: !!cfg.retrain_ensemble_enabled,
        retrain_ensemble_top_k: cfg.retrain_ensemble_top_k || 3,
        retrain_mode: cfg.retrain_mode || "engine",
        retrain_agent_recipe_id: cfg.retrain_agent_recipe_id || undefined,
        collect_correct_enabled: cfg.collect_correct_enabled,
        correct_sample_ratio: cfg.correct_sample_ratio || "1:1",
        field_descriptions: cfg.field_descriptions || {},
      });
    } else {
      form.setFieldsValue({
        name: tr.default_name || "自动化闭环", error_classes: [], preprocess_enabled: false,
        feature_engineering_mode: "legacy", feature_operator_id: undefined,
        feature_script: undefined,
        alert_threshold_rows: 1, require_review: false, review_annotator_ids: [],
        retrain_enabled: false, retrain_threshold_rows: 20, retrain_dataset_artifact_ids: [],
        retrain_max_trials: 10, retrain_ensemble_enabled: false, retrain_ensemble_top_k: 3,
        retrain_mode: "engine", retrain_agent_recipe_id: undefined,
        ...(editor.defaults || {}),
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
      const suffix = finalName !== submittedName
        ? (tr.renamed_suffix || "（重名，已自动命名为 {name}）").replace("{name}", finalName)
        : "";
      message.success((editor?.mode === "create" ? (tr.created || "闭环任务已创建") : (tr.saved || "配置已保存")) + suffix);
      onSaved(cfg as DemoLoopConfig);
    } catch (error) {
      message.error(formatApiError(error, editor?.mode === "create"
        ? (tr.create_failed || "闭环创建失败")
        : (tr.save_failed || "配置保存失败")));
    }
  };

  return (
    <Modal
      open={editor !== null}
      title={editor?.mode === "create"
        ? (tr.create_title || "新建闭环任务")
        : (tr.edit_title || "编辑闭环配置：{name}").replace("{name}", editor?.mode === "edit" ? editor.loop.name : "")}
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
          <Select
            options={deployments.map((item) => ({
              value: item.id,
              label: `${item.name}（${item.observed_state === "running" ? (tr.state_running || "运行中") : item.observed_state}）`,
            }))}
            placeholder={tr.choose_deployment || "选择推理部署"}
            onChange={(value) => {
              // 选择推理部署后：目标列为空时自动填充部署模型的 label 列。
              // 事件驱动实现——勿改回 useEffect + Form.useWatch：form 状态
              // 更新会与该 effect 互相触发，造成 Maximum update depth 渲染
              // 循环（r17 门禁 CI 前端套件卡死的根因）。
              if (!(form.getFieldValue("retrain_target_column") as string || "").trim()) {
                const deployment = deployments.find((item) => item.id === value);
                const target = deployment?.target_columns?.[0];
                if (target) form.setFieldsValue({ retrain_target_column: target });
              }
            }}
          />
        </Form.Item>
        <Form.Item name="error_classes" label={tr.error_classes || "报错类别（命中即回流）"} rules={[{ required: true }]}>
          <Select mode="tags" open={false} placeholder={tr.error_classes_hint || "输入类别后回车"} />
        </Form.Item>
        <Form.Item
          name="feature_engineering_mode"
          label={tr.preprocess || "特征工程方式"}
          initialValue="legacy"
          tooltip={tr.preprocess_tooltip || "上传数据缺少模型特征列时的自动补齐方式：内置点焊桥 / 「特征工程」类别算子 / 自写 Python 脚本"}
        >
          <Select options={buildFeatureModeOptions(zh)} />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.feature_engineering_mode !== next.feature_engineering_mode}>
          {({ getFieldValue }) => {
            const mode = getFieldValue("feature_engineering_mode") || "legacy";
            if (mode === "operator") {
              return (
                <Form.Item
                  name="feature_operator_id"
                  label={tr.fe_operator || "特征工程算子"}
                  rules={[{ required: true, message: tr.fe_operator_rule || "请选择「特征工程」类别下的算子" }]}
                  tooltip={tr.fe_operator_tooltip || "直接选用算子面板「特征工程」类别下的算子，按其默认参数执行（如拧紧特征工程默认剔除 DECIDE_ONE/DECIDE_TWO 泄漏列、中位数填充缺失并生成缺失标记列；需要自定义逻辑请用 Python 脚本模式）"}
                >
                  <Select
                    showSearch
                    optionFilterProp="label"
                    loading={feOperatorsLoading}
                    options={feOperatorOptions}
                    placeholder={feOperatorsLoading
                      ? (tr.fe_operator_loading || "正在加载特征工程算子…")
                      : (tr.fe_operator_placeholder || "选择「特征工程」类别下的算子")}
                    notFoundContent={tr.fe_operator_empty || "未找到「特征工程」类别下的算子"}
                  />
                </Form.Item>
              );
            }
            if (mode === "script") {
              return (
                <Form.Item
                  name="feature_script"
                  label={tr.fe_script || "特征工程 Python 脚本"}
                  rules={[{ required: true, message: tr.fe_script_rule || "请填写特征工程脚本" }]}
                  tooltip={tr.fe_script_tooltip || "与 python_script 算子相同的固定输入输出接口：输入 df（单行记录的 DataFrame），在 process(df) 中补齐模型特征列并返回；缺失依赖库按平台白名单源自动安装"}
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
                  {tr.legacy_hint || "上传原始点焊报告行（报告字段 + cvei/cvev/cver/cvep 波形列）时会先经内置特征桥补齐 73 特征再做预测；拧紧等其它场景请切换为「工作流特征工程算子」或「Python 脚本」。"}
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
        <Divider plain style={{ margin: "8px 0" }}>{tr.data_collection || "数据收集"}</Divider>
        <Form.Item
          name="collect_correct_enabled"
          label={tr.collect_correct || "同步收集正确数据"}
          valuePropName="checked"
          tooltip={tr.collect_correct_tooltip || "回流报错行时，按比例自动并入缓冲中的正常预测行（重新平衡重训数据的正负样本）"}
        >
          <Switch />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.collect_correct_enabled !== next.collect_correct_enabled}>
          {({ getFieldValue }) => getFieldValue("collect_correct_enabled") ? (
            <Form.Item
              name="correct_sample_ratio"
              label={tr.collect_ratio_label || "错误:正确 收集比例"}
              initialValue="1:1"
              rules={[{ required: true, message: tr.collect_ratio_rule || "请选择收集比例" }]}
            >
              <Select options={buildRatioOptions(zh)} />
            </Form.Item>
          ) : null}
        </Form.Item>
        <Divider plain style={{ margin: "8px 0" }}>{tr.field_interp || "字段解释"}</Divider>
        <Form.Item label={tr.reuse_field_desc || "复用已有标注任务的字段解释（可选）"}>
          <Select
            allowClear
            placeholder={(fieldDescTasks || []).length
              ? (tr.choose_desc_task || "选择标注任务")
              : (tr.no_desc_tasks || "暂无带字段解释的标注任务")}
            disabled={!(fieldDescTasks || []).length}
            options={(fieldDescTasks || []).map((task) => ({
              value: task.id,
              label: `${task.name}（${Object.keys(task.descriptions).length} ${zh ? "个字段" : "fields"}）`,
            }))}
            onSelect={(taskId: string) => {
              const task = (fieldDescTasks || []).find((item) => item.id === taskId);
              if (task) form.setFieldValue("field_descriptions", { ...task.descriptions });
            }}
          />
        </Form.Item>
        <Form.Item label={tr.upload_desc || "或上传字段解释文件（csv/txt，每行：字段名,描述）"}>
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
                  message.success((tr.parsed_ok || "已解析 {n} 个字段说明").replace("{n}", String(Object.keys(descriptions).length)));
                } else {
                  message.error(tr.parsed_empty || "未从文件中解析到任何「字段名,描述」行");
                }
              });
              return false;
            }}
          >
            <Button>{tr.choose_file || "选择文件"}</Button>
          </Upload>
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.field_descriptions !== next.field_descriptions}>
          {({ getFieldValue }) => {
            const descriptions = (getFieldValue("field_descriptions") as Record<string, string>) || {};
            const count = Object.keys(descriptions).length;
            return (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {count
                  ? (tr.desc_configured || "已配置 {n} 个字段解释，将展示在标注员工作区的对应字段旁").replace("{n}", String(count))
                  : (tr.desc_none || "未配置字段解释")}
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
              <Form.Item
                name="retrain_mode"
                label={tr.retrain_mode || "重训模式"}
                initialValue="engine"
                tooltip={tr.retrain_mode_tooltip || "引擎：平台 AutoML 直接重训换模（快）；智能体：复用固化配方重放完整智能体流程（分析/特征/建模/验收）后再换模（更稳，消耗 LLM）"}
              >
                <Select
                  aria-label={tr.retrain_mode_aria || "重训模式"}
                  options={[
                    { value: "engine", label: tr.retrain_mode_engine || "引擎快速重训（AutoML）" },
                    { value: "agent", label: tr.retrain_mode_agent || "智能体全流程重训（重放配方）" },
                  ]}
                />
              </Form.Item>
              <Form.Item noStyle shouldUpdate={(prev, cur) => prev.retrain_mode !== cur.retrain_mode}>
                {({ getFieldValue }) => getFieldValue("retrain_mode") === "agent" ? (
                  <>
                    <Form.Item
                      name="retrain_agent_recipe_id"
                      label={tr.retrain_agent_recipe || "绑定的固化配方"}
                      rules={[{ required: true, message: tr.retrain_agent_recipe_rule || "智能体模式必须绑定验收通过的固化配方" }]}
                    >
                      <Select
                        options={recipeOptions}
                        placeholder={tr.retrain_agent_recipe_ph || "选择配方（须含重放快照）"}
                      />
                    </Form.Item>
                    <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
                      {tr.retrain_agent_hint || "触发后智能体在合并回流数据上重放全流程（分析→特征→建模→验收），验收通过后由引擎铸造部署模型并自动换模；同部署串行、含冷却与 24h 熔断（默认 3 次/日）。"}
                    </Typography.Text>
                  </>
                ) : null}
              </Form.Item>
              <Form.Item name="retrain_threshold_rows" label={tr.retrain_threshold || "重训触发行数"} initialValue={20}>
                <InputNumber min={1} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item
                name="retrain_dataset_artifact_ids"
                label={tr.retrain_dataset || "重训数据集（可多选合并训练；闭环收集的报错数据集默认参与）"}
                rules={[{ required: true, message: tr.retrain_dataset_rule || "请选择至少一个重训数据集" }]}
              >
                <Select
                  mode="multiple"
                  options={(() => {
                    const options = datasets.map((item) => ({ value: item.id, label: item.name }));
                    const errId = editor?.mode === "edit" ? editor.loop.error_artifact_id : undefined;
                    if (errId && !options.some((o) => o.value === errId)) {
                      options.unshift({ value: errId, label: tr.error_dataset_tag || "报错数据集（闭环自动收集）" });
                    }
                    return options;
                  })()}
                  placeholder={tr.choose_dataset || "选择数据集（可多选）"}
                />
              </Form.Item>
              <Form.Item name="retrain_target_column" label={tr.retrain_target || "目标列"} rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="retrain_max_trials" label={tr.retrain_trials || "搜索试验次数"} initialValue={10}>
                <InputNumber min={5} max={200} style={{ width: "100%" }} />
              </Form.Item>
              <Form.Item
                name="retrain_ensemble_enabled"
                label={tr.ensemble_label || "集成学习（多模型加权投票）"}
                valuePropName="checked"
                initialValue={false}
                tooltip={tr.ensemble_tooltip || "重训时按主指标取前 K 名模型做 soft-voting；不低于单模型冠军才成为任务冠军并参与换模（仅单输出分类）"}
              >
                <Switch aria-label={tr.ensemble_aria || "重训集成学习"} />
              </Form.Item>
              <Form.Item noStyle shouldUpdate={(prev, cur) => prev.retrain_ensemble_enabled !== cur.retrain_ensemble_enabled}>
                {({ getFieldValue }) => getFieldValue("retrain_ensemble_enabled") ? (
                  <Form.Item name="retrain_ensemble_top_k" label={tr.ensemble_members || "集成成员数"} initialValue={3}>
                    <Select
                      aria-label={tr.ensemble_members_aria || "重训集成成员数"}
                      options={[2, 3, 4, 5].map((k) => ({ value: k, label: zh ? `前 ${k} 名` : `Top ${k}` }))}
                    />
                  </Form.Item>
                ) : null}
              </Form.Item>
            </>
          ) : null}
        </Form.Item>
        <Space style={{ width: "100%", justifyContent: "flex-end" }}>
          <Button onClick={onCancel}>{tr.cancel || "取消"}</Button>
          <Button type="primary" htmlType="submit" disabled={!projectId}>
            {editor?.mode === "create" ? (tr.create || "创建闭环") : (tr.save || "保存配置")}
          </Button>
        </Space>
      </Form>
    </Modal>
  );
}
