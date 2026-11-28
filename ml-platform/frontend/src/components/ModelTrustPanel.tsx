import { useCallback, useEffect, useState } from "react";
import {
  App as AntApp, Button, Card, Descriptions, Form, Input, Space, Spin, Table, Tag, Typography,
} from "antd";
import { apiErrorText } from "../api/qualityAlerts";
import {
  cbpeEstimate, computeTrustScore, explainSample, listTrustScores, refreshModelCard,
} from "../api/auditQa";
import type { TrustScore } from "../api/auditQa";
import { useI18n } from "../i18n";

/** 模型可信度面板（补齐路线第二批 B2-04，导航归属计划 §10.2「算法平台 ·
 * 模型库——模型详情内，不新增菜单」）：七因子可信度评分 + A–D 档（GET 即
 * 计算并落历史）、CBPE 估计（估计口径 + 强制脚注）、模型卡 11 章节重建
 * （数据指纹变化 → 审批回 pending 重签）、单样本解释（重要性×偏离近似 +
 * 口径脚注）。 */

const GRADE_COLOR: Record<string, string> = {
  A: "green", B: "blue", C: "orange", D: "red",
};

export default function ModelTrustPanel({
  projectId, versionId, versionNumber, canManage,
}: {
  projectId: string;
  versionId: string;
  versionNumber: number | string;
  canManage: boolean;
}) {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [trust, setTrust] = useState<TrustScore | null>(null);
  const [history, setHistory] = useState<{ score: number; grade: string; computed_at: string | null }[]>([]);
  const [cbpe, setCbpe] = useState<Record<string, unknown> | null>(null);
  const [cardResult, setCardResult] = useState<{ data_fingerprint_changed: boolean; approval_status: string } | null>(null);
  const [explainResult, setExplainResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [explainForm] = Form.useForm<{ row: string }>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [score, scores] = await Promise.all([
        computeTrustScore(projectId, versionId),
        listTrustScores(projectId, versionId).catch(() => []),
      ]);
      setTrust(score);
      setHistory(scores);
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setLoading(false);
    }
  }, [projectId, versionId, message]);

  useEffect(() => { void load(); }, [load]);

  const run = async (operation: () => Promise<unknown>, successText: string) => {
    setBusy(true);
    try {
      await operation();
      message.success(successText);
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const factorEntries = Object.entries(trust?.factors ?? {});

  return (
    <div data-testid="model-trust-panel" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card size="small" title={zh ? "七因子可信度（GET 即计算并落历史）" : "Trust score"}>
        {loading ? (
          <Spin />
        ) : trust ? (
          <>
            <Descriptions size="small" column={2}>
              <Descriptions.Item label={zh ? "评分" : "Score"}>
                <Typography.Text strong>{trust.score}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label={zh ? "档位" : "Grade"}>
                <Tag color={GRADE_COLOR[trust.grade] ?? "default"}>{trust.grade}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label={zh ? "计算时间" : "Computed at"}>{trust.computed_at ?? "-"}</Descriptions.Item>
            </Descriptions>
            <div style={{ marginTop: 8 }}>
              {factorEntries.map(([key, value]) => (
                <Tag key={key}>{key}: {typeof value === "object" ? JSON.stringify(value) : String(value)}</Tag>
              ))}
            </div>
          </>
        ) : (
          <Typography.Text type="secondary">{zh ? "评分不可用。" : "Score unavailable."}</Typography.Text>
        )}
        {history.length > 0 && (
          <Table rowKey={(row) => String(row.computed_at)} size="small" style={{ marginTop: 12 }}
            pagination={false}
            dataSource={history}
            columns={[
              { title: zh ? "评分" : "Score", dataIndex: "score", width: 90 },
              {
                title: zh ? "档位" : "Grade", dataIndex: "grade", width: 90,
                render: (value: string) => <Tag color={GRADE_COLOR[value] ?? "default"}>{value}</Tag>,
              },
              { title: zh ? "时间" : "Time", dataIndex: "computed_at" },
            ]} />
        )}
      </Card>

      <Card size="small" title={zh ? "CBPE 性能估计（估计口径，非实测）" : "CBPE estimate"}
        extra={
          <Button size="small" loading={busy} onClick={() => void run(async () => {
            setCbpe(await cbpeEstimate(projectId, versionId));
          }, zh ? "已估计" : "Estimated")}>
            {zh ? "估计" : "Estimate"}
          </Button>
        }>
        {cbpe ? (
          <Space wrap>
            {Object.entries(cbpe).map(([key, value]) => (
              <Tag key={key}>{key}: {typeof value === "object" ? JSON.stringify(value) : String(value)}</Tag>
            ))}
          </Space>
        ) : (
          <Typography.Text type="secondary">
            {zh ? "点「估计」获取（结果带强制脚注：估计口径）。" : "Click estimate."}
          </Typography.Text>
        )}
      </Card>

      <Card size="small" title={zh ? "模型卡 11 章节（数据指纹变化 → 审批回 pending）" : "Model card"}
        extra={
          canManage && (
            <Button size="small" loading={busy} data-testid="refresh-card"
              onClick={() => void run(async () => {
                const result = await refreshModelCard(projectId, versionId);
                setCardResult({ data_fingerprint_changed: result.data_fingerprint_changed, approval_status: result.approval_status });
              }, zh ? "模型卡已重建" : "Card refreshed")}>
              {zh ? "重建模型卡" : "Refresh card"}
            </Button>
          )
        }>
        {cardResult ? (
          <Space wrap>
            <Tag color={cardResult.data_fingerprint_changed ? "orange" : "green"}>
              {zh ? "数据指纹" : "fingerprint"}: {cardResult.data_fingerprint_changed ? (zh ? "已变化" : "changed") : (zh ? "未变" : "unchanged")}
            </Tag>
            <Tag>{zh ? "审批状态" : "approval"}: {cardResult.approval_status}</Tag>
            {cardResult.data_fingerprint_changed && (
              <Typography.Text type="secondary">
                {zh ? "指纹变化 → 版本审批回 pending，需重签后才能发布。" : "Approval reset to pending."}
              </Typography.Text>
            )}
          </Space>
        ) : (
          <Typography.Text type="secondary">
            {zh ? canManage ? "重建后展示指纹与审批状态（需 model.approve 权限）。" : "需要 model.approve 权限。" : "Requires model.approve permission."}
          </Typography.Text>
        )}
      </Card>

      <Card size="small" title={zh ? "单样本解释（重要性×偏离近似 + 口径脚注）" : "Explain sample"}>
        <Form form={explainForm} layout="vertical" size="small" data-testid="explain-form"
          onFinish={(values) => void run(async () => {
            let row: Record<string, unknown>;
            try {
              row = JSON.parse(values.row) as Record<string, unknown>;
            } catch {
              throw new Error(zh ? "JSON 格式不合法" : "Invalid JSON");
            }
            setExplainResult(await explainSample(projectId, versionId, row));
          }, zh ? "解释已生成" : "Explained")}>
          <Form.Item name="row" rules={[{ required: true }]} label={zh ? "样本行 (JSON)" : "Row (JSON)"}>
            <Input.TextArea rows={2} placeholder='{"feature_a": 1.5}' />
          </Form.Item>
          <Button htmlType="submit" loading={busy} data-testid="explain-submit">{zh ? "解释" : "Explain"}</Button>
        </Form>
        {explainResult && (
          <Space wrap style={{ marginTop: 8 }}>
            {Object.entries(explainResult).map(([key, value]) => (
              <Typography.Text key={key}>
                {key}: {typeof value === "object" ? JSON.stringify(value) : String(value)}；{" "}
              </Typography.Text>
            ))}
          </Space>
        )}
      </Card>

      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {zh
          ? `口径说明：可信度评分与 CBPE 均为估计口径（不替代盲测实测）；发布门禁的终验指标只取锁定盲测段真实打分。版本 v${versionNumber}。`
          : `Trust score and CBPE are estimates; release gates use real blind-split scoring. Version v${versionNumber}.`}
      </Typography.Paragraph>
    </div>
  );
}
