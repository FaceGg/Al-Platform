import { useCallback, useEffect, useState } from "react";
import {
  App as AntApp, Button, Card, Collapse, Form, Input, InputNumber, Select, Space,
  Table, Tag, Typography,
} from "antd";
import { apiErrorText } from "../../api/qualityAlerts";
import {
  computeRoundKappa, createActiveLearningSelection, createPseudoLabelBatch,
  decideArbitration, labelQualityGate, listActiveLearningSelections, listArbitrations,
  openConsistencyRound, pseudoCredentialExportUrl, submitBlindLabel,
} from "../../api/labelQuality";
import type { ActiveLearningSelection, LabelArbitration, LabelQualityGate } from "../../api/labelQuality";
import { listAnnotatorSubjects } from "../../api/annotatorAssignments";
import type { AnnotatorSubject } from "../../api/annotatorAssignments";
import { useI18n } from "../../i18n";

/** 标注质量面板（补齐路线第二批 S3：主动学习 B2-05 / Kappa 一致性轮与
 * 仲裁 B2-06 / 伪标签 B2-G4 / E15 质量门，导航归属计划 §10.2「算法平台 ·
 * 数据标注——标注页内页签」）。
 *
 * 主动学习的 frame_rows 由调用方冻结传入（与后端合同一致：样本池 JSON
 * 粘贴）；盲标提交身份绑定登录用户（后端强制，无 subject 输入）。 */

export default function LabelQualityPanel({ projectId }: { projectId: string }) {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [gate, setGate] = useState<LabelQualityGate | null>(null);
  const [selections, setSelections] = useState<ActiveLearningSelection[]>([]);
  const [arbitrations, setArbitrations] = useState<LabelArbitration[]>([]);
  const [annotators, setAnnotators] = useState<AnnotatorSubject[]>([]);
  const [busy, setBusy] = useState(false);
  const [roundForm] = Form.useForm<{ annotator_subject_ids: string[]; sample_ids: string; kappa_threshold: number }>();
  const [blindForm] = Form.useForm<{ round_id: string; sample_id: string; values: string }>();
  const [kappaForm] = Form.useForm<{ round_id: string }>();
  const [arbitrationForm] = Form.useForm<{ arbitration_id: string; decision_values: string; note?: string }>();
  const [selectionForm] = Form.useForm<{ strategy: string; frame_rows: string; budget_initial: number; budget_per_round: number }>();
  const [pseudoForm] = Form.useForm<{ candidates: string; threshold: number }>();
  const [lastPseudoBatch, setLastPseudoBatch] = useState<{ id: string; selected_count: number } | null>(null);

  const load = useCallback(() => {
    if (!projectId) return;
    labelQualityGate(projectId).then(setGate).catch(() => setGate(null));
    listActiveLearningSelections(projectId).then(setSelections).catch(() => setSelections([]));
    listArbitrations(projectId).then(setArbitrations).catch(() => setArbitrations([]));
    listAnnotatorSubjects("", projectId).then(setAnnotators).catch(() => setAnnotators([]));
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  const run = async (operation: () => Promise<unknown>, successText: string) => {
    setBusy(true);
    try {
      await operation();
      message.success(successText);
      load();
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const parseJson = (text: string): unknown => {
    try {
      return JSON.parse(text);
    } catch {
      throw new Error(zh ? "JSON 格式不合法" : "Invalid JSON");
    }
  };

  const selectionColumns = [
    {
      title: zh ? "策略" : "Strategy", key: "strategy",
      render: (_: unknown, row: ActiveLearningSelection) => {
        const name = (row.strategy as { name?: string } | undefined)?.name;
        return <Tag color="blue">{name ?? "-"}</Tag>;
      },
    },
    { title: zh ? "选出样本" : "Selected", dataIndex: "selected_count", key: "count", width: 100 },
    { title: zh ? "每轮预算" : "Per round", dataIndex: "budget_per_round", key: "budget", width: 100 },
    { title: zh ? "时间" : "Created", dataIndex: "created_at", key: "created_at", width: 180 },
  ];

  const arbitrationColumns = [
    { title: zh ? "样本" : "Sample", dataIndex: "sample_id", key: "sample", width: 160, ellipsis: true },
    {
      title: zh ? "状态" : "Status", dataIndex: "status", key: "status", width: 110,
      render: (value: string) => <Tag color={value === "decided" ? "green" : "orange"}>{value}</Tag>,
    },
    {
      title: zh ? "分歧" : "Conflict", key: "conflict", ellipsis: true,
      render: (_: unknown, row: LabelArbitration) => JSON.stringify(row.conflict),
    },
    {
      title: zh ? "终审值" : "Decision", key: "decision",
      render: (_: unknown, row: LabelArbitration) =>
        row.decision_values ? JSON.stringify(row.decision_values) : "-",
    },
  ];

  return (
    <div data-testid="label-quality-panel" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card size="small" title={zh ? "E15 标签质量门" : "Label quality gate"}>
        {gate === null ? (
          <Typography.Text type="secondary">
            {zh ? "质量门状态不可用：开一致性轮并计算 κ 后出现（训练入口会按此门置 failed）。" : "Gate status appears after a consistency round."}
          </Typography.Text>
        ) : (
          <Space wrap>
            <Tag color={gate.status === "passed" ? "green" : gate.status === "failed" ? "red" : "orange"}>
              {String(gate.status ?? "-")}
            </Tag>
            <Typography.Text>{zh ? "κ：" : "κ: "}{String(gate.kappa ?? "-")}</Typography.Text>
            <Typography.Text type="secondary">{zh ? "阈值：" : "threshold: "}{String(gate.threshold ?? "-")}</Typography.Text>
            {Object.entries(gate)
              .filter(([key]) => !["status", "kappa", "threshold"].includes(key))
              .map(([key, value]) => (
                <Typography.Text key={key} type="secondary">{key}: {JSON.stringify(value)}</Typography.Text>
              ))}
          </Space>
        )}
      </Card>

      <Collapse items={[
        {
          key: "round",
          label: zh ? "一致性轮（Kappa 仲裁 B2-06）" : "Consistency rounds (B2-06)",
          children: (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Form form={roundForm} layout="inline" size="small" data-testid="round-form"
                onFinish={(values) => void run(async () => {
                  const sampleIds = values.sample_ids.split(/[\s,;]+/).filter(Boolean);
                  if (sampleIds.length === 0) throw new Error(zh ? "至少 1 个样本" : "At least one sample");
                  await openConsistencyRound(projectId, {
                    annotator_subject_ids: values.annotator_subject_ids,
                    sample_ids: sampleIds,
                    kappa_threshold: values.kappa_threshold,
                  });
                }, zh ? "一致性轮已开启：让各标注员盲标后计算 κ" : "Round opened")}>
                <Form.Item name="annotator_subject_ids" rules={[{ required: true, min: 2 }]}
                  label={zh ? "标注员（≥2）" : "Annotators"}>
                  <Select mode="multiple" style={{ minWidth: 240 }} maxTagCount={3}
                    options={annotators.map((item) => ({ value: item.id, label: item.display_name || item.username }))} />
                </Form.Item>
                <Form.Item name="sample_ids" rules={[{ required: true }]}
                  label={zh ? "样本（逗号/空格分隔）" : "Sample ids"}>
                  <Input style={{ minWidth: 220 }} placeholder="sk-1, sk-2, sk-3" />
                </Form.Item>
                <Form.Item name="kappa_threshold" initialValue={0.6} label="κ 阈值">
                  <InputNumber min={0} max={1} step={0.05} />
                </Form.Item>
                <Form.Item>
                  <Button type="primary" htmlType="submit" loading={busy}>{zh ? "开轮" : "Open"}</Button>
                </Form.Item>
              </Form>

              <Form form={blindForm} layout="inline" size="small" data-testid="blind-form"
                onFinish={(values) => void run(async () => {
                  const parsed = parseJson(values.values) as Record<string, unknown>;
                  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
                    throw new Error(zh ? "values 须为 JSON 对象" : "values must be a JSON object");
                  }
                  await submitBlindLabel(projectId, values.round_id.trim(), {
                    sample_id: values.sample_id.trim(), values: parsed,
                  });
                }, zh ? "盲标已提交（身份=当前登录用户）" : "Blind label submitted")}>
                <Form.Item name="round_id" rules={[{ required: true }]} label={zh ? "轮 ID" : "Round id"}>
                  <Input style={{ width: 220 }} placeholder="UUID" />
                </Form.Item>
                <Form.Item name="sample_id" rules={[{ required: true }]} label={zh ? "样本" : "Sample"}>
                  <Input style={{ width: 160 }} />
                </Form.Item>
                <Form.Item name="values" rules={[{ required: true }]} label="values (JSON)">
                  <Input style={{ width: 200 }} placeholder='{"quality": "ok"}' />
                </Form.Item>
                <Form.Item>
                  <Button htmlType="submit" loading={busy}>{zh ? "提交盲标" : "Submit"}</Button>
                </Form.Item>
              </Form>

              <Form form={kappaForm} layout="inline" size="small" data-testid="kappa-form"
                onFinish={(values) => void run(async () => {
                  const result = await computeRoundKappa(projectId, values.round_id.trim());
                  message.info(zh
                    ? `κ 计算完成：pairwise=${JSON.stringify(result.kappa_pairwise)} average=${JSON.stringify(result.kappa_average)} 状态=${result.status}（分歧已自动进仲裁队列）`
                    : `Kappa computed: ${result.status}`);
                }, zh ? "κ 已计算" : "Kappa computed")}>
                <Form.Item name="round_id" rules={[{ required: true }]} label={zh ? "轮 ID" : "Round id"}>
                  <Input style={{ width: 220 }} placeholder="UUID" />
                </Form.Item>
                <Form.Item>
                  <Button htmlType="submit" loading={busy}>{zh ? "计算 κ 并归档分歧" : "Compute κ"}</Button>
                </Form.Item>
              </Form>
            </div>
          ),
        },
        {
          key: "arbitration",
          label: zh ? "仲裁队列（终审值由你写回规范通道）" : "Arbitration queue",
          children: (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Table rowKey="id" size="small" columns={arbitrationColumns} dataSource={arbitrations}
                pagination={{ pageSize: 5 }}
                locale={{ emptyText: zh ? "暂无仲裁：一致性轮计算 κ 后分歧自动进入" : "No arbitrations yet" }} />
              <Form form={arbitrationForm} layout="inline" size="small" data-testid="arbitration-form"
                onFinish={(values) => void run(async () => {
                  const parsed = parseJson(values.decision_values) as Record<string, unknown>;
                  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
                    throw new Error(zh ? "终审值须为 JSON 对象" : "decision must be a JSON object");
                  }
                  await decideArbitration(projectId, values.arbitration_id.trim(), {
                    decision_values: parsed, note: values.note?.trim() || null,
                  });
                }, zh ? "仲裁已终审（仲裁人≠盲标人由后端强制）" : "Arbitration decided")}>
                <Form.Item name="arbitration_id" rules={[{ required: true }]} label={zh ? "仲裁 ID" : "Arbitration id"}>
                  <Input style={{ width: 220 }} placeholder="UUID" />
                </Form.Item>
                <Form.Item name="decision_values" rules={[{ required: true }]} label={zh ? "终审值 (JSON)" : "Decision (JSON)"}>
                  <Input style={{ width: 200 }} placeholder='{"quality": "ng"}' />
                </Form.Item>
                <Form.Item name="note" label={zh ? "备注" : "Note"}>
                  <Input style={{ width: 160 }} maxLength={256} />
                </Form.Item>
                <Form.Item>
                  <Button htmlType="submit" loading={busy}>{zh ? "终审" : "Decide"}</Button>
                </Form.Item>
              </Form>
            </div>
          ),
        },
        {
          key: "active-learning",
          label: zh ? "主动学习选样（B2-05）" : "Active learning (B2-05)",
          children: (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                {zh
                  ? "样本池由调用方冻结传入：粘贴 JSON 行数组（含样本键/特征列，可选 probability 列供不确定性策略用），九策略按预算出样。"
                  : "Paste a frozen frame (rows JSON) for the nine selection strategies."}
              </Typography.Paragraph>
              <Form form={selectionForm} layout="vertical" size="small" data-testid="selection-form"
                onFinish={(values) => void run(async () => {
                  const strategy = parseJson(values.strategy) as Record<string, unknown>;
                  const frameRows = parseJson(values.frame_rows) as Record<string, unknown>[];
                  if (!Array.isArray(frameRows) || frameRows.length === 0) {
                    throw new Error(zh ? "样本池须为非空 JSON 行数组" : "frame_rows must be a non-empty array");
                  }
                  await createActiveLearningSelection(projectId, {
                    strategy, frame_rows: frameRows,
                    budget_initial: values.budget_initial, budget_per_round: values.budget_per_round,
                  });
                }, zh ? "选样完成（命中统计见历史）" : "Selection recorded")}>
                <Space wrap>
                  <Form.Item name="strategy" rules={[{ required: true }]} label={zh ? "策略 (JSON)" : "Strategy (JSON)"}>
                    <Input style={{ width: 240 }} placeholder='{"name": "uncertainty"}' />
                  </Form.Item>
                  <Form.Item name="budget_initial" initialValue={100} label={zh ? "初始预算" : "Initial budget"}>
                    <InputNumber min={1} />
                  </Form.Item>
                  <Form.Item name="budget_per_round" initialValue={50} label={zh ? "每轮预算" : "Per round"}>
                    <InputNumber min={1} />
                  </Form.Item>
                </Space>
                <Form.Item name="frame_rows" rules={[{ required: true }]} label={zh ? "样本池 (JSON 行数组)" : "frame_rows (JSON)"}>
                  <Input.TextArea rows={3} placeholder='[{"sample_key":"sk-1","probability":0.52}]' />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={busy}>{zh ? "发起选样" : "Select"}</Button>
              </Form>
              <Table rowKey="id" size="small" columns={selectionColumns} dataSource={selections}
                pagination={{ pageSize: 5 }}
                locale={{ emptyText: zh ? "暂无选样记录" : "No selections yet" }} />
            </div>
          ),
        },
        {
          key: "pseudo",
          label: zh ? "伪标签批（B2-G4）" : "Pseudo-label batches (B2-G4)",
          children: (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                {zh
                  ? "候选由模型打分产出后传入（sample_key / label / confidence）；平台做阈值过滤、每类限量与降权，凭证 CSV 可导出（样本/生成模型/训练折/置信度/权重）。"
                  : "Pass scored candidates; the platform filters, caps and down-weights them."}
              </Typography.Paragraph>
              <Form form={pseudoForm} layout="vertical" size="small" data-testid="pseudo-form"
                onFinish={(values) => void run(async () => {
                  const candidates = parseJson(values.candidates) as { sample_key: string; label: string; confidence: number }[];
                  if (!Array.isArray(candidates) || candidates.length === 0) {
                    throw new Error(zh ? "候选须为非空 JSON 数组" : "candidates must be a non-empty array");
                  }
                  const batch = await createPseudoLabelBatch(projectId, {
                    candidates, threshold: values.threshold,
                  });
                  setLastPseudoBatch(batch);
                }, zh ? "伪标签批已落库" : "Pseudo batch recorded")}>
                <Space wrap>
                  <Form.Item name="threshold" initialValue={0.9} label={zh ? "置信度阈值" : "Threshold"}>
                    <InputNumber min={0.5} max={1} step={0.01} />
                  </Form.Item>
                </Space>
                <Form.Item name="candidates" rules={[{ required: true }]} label={zh ? "候选 (JSON)" : "candidates (JSON)"}>
                  <Input.TextArea rows={3} placeholder='[{"sample_key":"sk-9","label":"ok","confidence":0.94}]' />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={busy}>{zh ? "落伪标签批" : "Create batch"}</Button>
              </Form>
              {lastPseudoBatch && (
                <Space>
                  <Typography.Text>
                    {zh ? `已选 ${lastPseudoBatch.selected_count} 条（批 ${lastPseudoBatch.id.slice(0, 8)}）` : `Selected ${lastPseudoBatch.selected_count}`}
                  </Typography.Text>
                  <Button size="small" href={pseudoCredentialExportUrl(projectId, lastPseudoBatch.id)} target="_blank">
                    {zh ? "下载凭证 CSV" : "Download credential CSV"}
                  </Button>
                </Space>
              )}
            </div>
          ),
        },
      ]} />
    </div>
  );
}
