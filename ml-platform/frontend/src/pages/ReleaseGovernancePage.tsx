import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App as AntApp, Button, Card, Form, Input, InputNumber, Modal, Select,
  Space, Table, Tag, Typography,
} from "antd";
import { DownloadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { apiErrorText } from "../api/qualityAlerts";
import {
  createReleaseRequest, grantPreauthorization, listShadowReports, registerChallenger,
  retireChallenger, revokePreauthorization, runShadowBatch, shadowReportExportUrl,
} from "../api/releaseGovernance";
import type { ReleaseCheck, ShadowComparisonReport } from "../api/releaseGovernance";
import { listDeployments, listRegisteredModels, listModelVersions } from "../api/modelRegistry";
import type { InferenceDeployment, ModelVersion } from "../api/modelRegistry";
import { useI18n } from "../i18n";

/** 发布治理与影子（补齐路线第二批 S2b：B2-02/03/09/G2/G3，导航归属
 * 计划 §10.2「算法平台 · 模型运营」——影子推理独立菜单项）。
 *
 * 发布门禁/预授权/回执的完整链路见模型库版本行（§10.2「模型详情与发布
 * 流程内，不新增菜单」）；本页承载部署域治理操作（challenger / 影子 /
 * 报告）与发布申请入口。 */

export default function ReleaseGovernancePage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [deployments, setDeployments] = useState<InferenceDeployment[]>([]);
  const [deploymentId, setDeploymentId] = useState<string | null>(null);
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [challengerVersionId, setChallengerVersionId] = useState<string | null>(null);
  const [reports, setReports] = useState<ShadowComparisonReport[]>([]);
  const [busy, setBusy] = useState(false);
  const [preauthOpen, setPreauthOpen] = useState(false);
  const [releaseOpen, setReleaseOpen] = useState(false);
  const [lastChecks, setLastChecks] = useState<ReleaseCheck[] | null>(null);
  const [shadowSource, setShadowSource] = useState<"random_sample" | "traffic_mirror">("random_sample");
  const [shadowSize, setShadowSize] = useState<number | null>(null);
  const [preauthForm] = Form.useForm<{ fingerprint: string; expires_at: string; max_releases: number; note?: string }>();
  const [releaseForm] = Form.useForm<{ model_version_id: string; strategy: string; preauthorization_id?: string }>();

  const deployment = useMemo(
    () => deployments.find((item) => item.id === deploymentId) ?? null,
    [deployments, deploymentId],
  );

  const loadDeployments = useCallback(async () => {
    if (!projectId) { setDeployments([]); setDeploymentId(null); return; }
    try {
      const items = await listDeployments(projectId);
      setDeployments(items);
      setDeploymentId((current) => current ?? (items[0]?.id ?? null));
    } catch (e) {
      message.error(apiErrorText(e));
    }
  }, [projectId, message]);

  useEffect(() => { void loadDeployments(); }, [loadDeployments]);

  useEffect(() => {
    if (!projectId) { setVersions([]); return; }
    listRegisteredModels(projectId)
      .then((models) => Promise.all(models.map((model) =>
        listModelVersions(model.id).catch(() => [] as ModelVersion[]))))
      .then((groups) => setVersions(groups.flat()))
      .catch(() => setVersions([]));
  }, [projectId]);

  const loadReports = useCallback(() => {
    if (!projectId || !deploymentId) { setReports([]); return; }
    listShadowReports(projectId, deploymentId).then(setReports).catch((e) => message.error(apiErrorText(e)));
  }, [projectId, deploymentId, message]);

  useEffect(() => { loadReports(); }, [loadReports]);

  const run = async (operation: () => Promise<unknown>, successText: string) => {
    setBusy(true);
    try {
      await operation();
      message.success(successText);
      loadReports();
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const versionOptions = versions.map((item) => ({
    value: item.id,
    label: `v${item.version_number} · ${item.approval_status}`,
  }));

  const exportReport = (row: ShadowComparisonReport) => {
    if (!projectId || !deploymentId) return;
    const anchor = document.createElement("a");
    anchor.href = shadowReportExportUrl(projectId, deploymentId, row.id);
    anchor.download = `shadow-report-${row.id.slice(0, 8)}.csv`;
    anchor.click();
  };

  const reportColumns = [
    {
      title: zh ? "样本来源" : "Source", dataIndex: "sample_source", key: "source", width: 130,
      render: (value: string | null) => value === "traffic_mirror"
        ? <Tag color="cyan">{zh ? "流量镜像" : "traffic mirror"}</Tag>
        : <Tag color="blue">{zh ? "随机抽样" : "random"}</Tag>,
    },
    { title: zh ? "样本数" : "Samples", dataIndex: "sample_count", key: "count", width: 90 },
    {
      title: zh ? "一致率" : "Agreement", dataIndex: "agreement_rate", key: "rate", width: 110,
      render: (value: number | null) => value === null ? "-" : `${(value * 100).toFixed(1)}%`,
    },
    {
      title: zh ? "可比/一致" : "Comparable/agreed", key: "detail", width: 110,
      render: (_: unknown, row: ShadowComparisonReport) =>
        `${row.detail?.comparable ?? 0} / ${row.detail?.agreed ?? 0}`,
    },
    { title: "fingerprint", dataIndex: "report_fingerprint", key: "fp", ellipsis: true },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 90,
      render: (_: unknown, row: ShadowComparisonReport) => (
        <Button size="small" icon={<DownloadOutlined />} aria-label={`导出影子报告 ${row.id}`}
          onClick={() => exportReport(row)}>{zh ? "导出" : "Export"}</Button>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="algo" navKey="release_governance" testId="v2-release-governance">
        <PageHeading
          section="algo"
          navKey="release_governance"
          desc={zh
            ? "发布治理链：注册影子候选（challenger 权重恒 0）→ 影子打分（随机抽样记种子 / 流量镜像按近期生产流量取键）→ 一致率报告；发布申请走门禁五项 + 不回退盲测配对，预授权可免审批（G2/G3）。"
            : "Release governance: challenger, shadow scoring (random / traffic-mirror), reports, gated release requests and preauthorization."}
          actions={
            <Space>
              <Select
                aria-label={zh ? "选择项目" : "Select project"}
                style={{ minWidth: 160 }}
                placeholder={zh ? "选择项目" : "Select project"}
                value={projectId ?? undefined}
                onChange={(value: string) => { setProjectId(value); setDeploymentId(null); }}
                options={projects.map((item) => ({ value: item.id, label: item.name }))}
              />
              <Select
                aria-label={zh ? "选择部署" : "Select deployment"}
                style={{ minWidth: 200 }}
                placeholder={zh ? "选择部署" : "Select deployment"}
                value={deploymentId ?? undefined}
                onChange={(value: string) => setDeploymentId(value)}
                options={deployments.map((item) => ({ value: item.id, label: item.name }))}
              />
            </Space>
          }
        />

        {!projectId || !deployment ? (
          <Card>
            <Typography.Paragraph type="secondary" data-testid="rg-empty">
              {zh
                ? "暂无部署：先在模型库为目标版本创建推理部署，再回到本页治理影子与发布。"
                : "No deployments yet — create one from the model library first."}
            </Typography.Paragraph>
          </Card>
        ) : (
          <>
            <Card title={zh ? "影子候选（challenger）" : "Challenger"} size="small" style={{ marginBottom: 16 }}>
              <Space wrap>
                <Select
                  aria-label={zh ? "候选版本" : "Challenger version"}
                  style={{ minWidth: 220 }}
                  placeholder={zh ? "选择候选版本（approved）" : "Pick a version"}
                  value={challengerVersionId ?? undefined}
                  options={versionOptions}
                  onChange={(value: string) => setChallengerVersionId(value)}
                />
                <Button disabled={busy || !challengerVersionId} data-testid="register-challenger"
                  onClick={() => void run(async () => {
                    await registerChallenger(projectId!, deploymentId!, challengerVersionId!);
                  }, zh ? "已注册影子候选（权重恒 0，不进生产路由）" : "Challenger registered")}>
                  {zh ? "注册候选" : "Register"}
                </Button>
                <Button danger disabled={busy} onClick={() => void run(async () => {
                  await retireChallenger(projectId!, deploymentId!);
                }, zh ? "已退役影子候选" : "Challenger retired")}>
                  {zh ? "退役候选" : "Retire challenger"}
                </Button>
                <Select
                  aria-label={zh ? "影子样本来源" : "Shadow sample source"}
                  style={{ minWidth: 150 }}
                  value={shadowSource}
                  onChange={(value: "random_sample" | "traffic_mirror") => setShadowSource(value)}
                  options={[
                    { value: "random_sample", label: zh ? "随机抽样（记种子）" : "Random sample" },
                    { value: "traffic_mirror", label: zh ? "流量镜像（近期生产流量）" : "Traffic mirror" },
                  ]}
                />
                {shadowSource === "random_sample" && (
                  <InputNumber aria-label={zh ? "样本量" : "Sample size"} min={1} max={100000}
                    placeholder="500" value={shadowSize ?? undefined}
                    onChange={(value) => setShadowSize(value ?? null)} />
                )}
                <Button type="primary" icon={<ThunderboltOutlined />} loading={busy}
                  data-testid="run-shadow"
                  disabled={!challengerVersionId}
                  onClick={() => void run(async () => {
                    const res = await runShadowBatch(projectId!, deploymentId!, {
                      model_version_id: challengerVersionId!,
                      sample_source: shadowSource,
                      sample_size: shadowSize ?? undefined,
                    });
                    setLastChecks(null);
                    message.info(zh
                      ? `影子打分 ${res.data.scored} 条，一致率 ${res.data.agreement_rate === null ? "-" : `${(res.data.agreement_rate * 100).toFixed(1)}%`}`
                      : `Scored ${res.data.scored}, agreement ${res.data.agreement_rate ?? "-"}`);
                  }, zh ? "影子打分完成" : "Shadow batch done")}>
                  {zh ? "运行影子打分" : "Run shadow"}
                </Button>
                <Button disabled={busy} data-testid="new-preauth"
                  onClick={() => { preauthForm.resetFields(); setPreauthOpen(true); }}>
                  {zh ? "授予预授权" : "Grant preauthorization"}
                </Button>
                <Button type="primary" disabled={busy} data-testid="new-release"
                  onClick={() => { releaseForm.resetFields(); setReleaseOpen(true); }}>
                  {zh ? "发布申请" : "Release request"}
                </Button>
              </Space>
              <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
                {zh
                  ? "候选权重恒 0 不进生产路由；影子打分不写预警表。流量镜像无生产流量或样本池无命中时后端拒绝（SHADOW_NO_TRAFFIC）。"
                  : "Challenger weight stays 0; shadow scoring never writes alerts. Traffic mirror fails honestly without production traffic (SHADOW_NO_TRAFFIC)."}
              </Typography.Paragraph>
            </Card>

            <Card title={zh ? "影子对照报告（内容变化=新行，不可变）" : "Shadow reports (immutable)"} size="small">
              <Table rowKey="id" size="small" columns={reportColumns} dataSource={reports} pagination={false}
                locale={{ emptyText: zh ? "暂无报告：运行一次影子打分后自动生成" : "No shadow reports yet" }} />
            </Card>
          </>
        )}

        <Modal open={preauthOpen} destroyOnClose title={zh ? "授予发布预授权（G2）" : "Grant preauthorization"}
          okText={zh ? "授予" : "Grant"} confirmLoading={busy}
          onCancel={() => setPreauthOpen(false)} onOk={() => preauthForm.submit()}>
          <Typography.Paragraph type="secondary">
            {zh ? "授权人须有 approval.approve 权限；申请人≠授权人在使用时强制（四眼）。" : "Granter needs approval.approve; self-release enforcement applies at use time."}
          </Typography.Paragraph>
          <Form form={preauthForm} layout="vertical" data-testid="preauth-form"
            onFinish={(values) => void run(async () => {
              await grantPreauthorization(projectId!, {
                deployment_id: deploymentId,
                acceptance_gates_fingerprint: values.fingerprint.trim(),
                expires_at: values.expires_at.trim(),
                max_releases: values.max_releases,
                note: values.note?.trim() || null,
              });
              setPreauthOpen(false);
            }, zh ? "预授权已授予" : "Preauthorization granted")}>
            <Form.Item name="fingerprint" label={zh ? "门禁指纹（acceptance_gates_fingerprint）" : "Gates fingerprint"}
              rules={[{ required: true, min: 8, max: 64 }]}>
              <Input maxLength={64} placeholder="sha256 前 64 位" />
            </Form.Item>
            <Form.Item name="expires_at" label={zh ? "失效时间（ISO 8601）" : "Expires at (ISO 8601)"}
              rules={[{ required: true }]}>
              <Input placeholder="2026-12-31T00:00:00" />
            </Form.Item>
            <Form.Item name="max_releases" label={zh ? "可发布次数" : "Max releases"}
              initialValue={1} rules={[{ required: true }]}>
              <InputNumber min={1} max={100} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item name="note" label={zh ? "备注（可选）" : "Note"}>
              <Input.TextArea rows={2} maxLength={256} />
            </Form.Item>
          </Form>
          <Button size="small" disabled={busy} onClick={() => {
            const input = window.prompt(zh ? "输入要吊销的预授权 ID" : "Preauthorization id to revoke");
            if (input) void run(() => revokePreauthorization(projectId!, input.trim()), zh ? "已吊销" : "Revoked");
          }}>{zh ? "按 ID 吊销预授权" : "Revoke by id"}</Button>
        </Modal>

        <Modal open={releaseOpen} destroyOnClose title={zh ? "发布申请（门禁先行）" : "Release request"}
          okText={zh ? "提交申请" : "Submit"} confirmLoading={busy}
          onCancel={() => setReleaseOpen(false)} onOk={() => releaseForm.submit()}>
          <Typography.Paragraph type="secondary">
            {zh ? "提交即创建 model_release 审批单并落门禁检查；门禁未过将返回 rejected 存档单（豁免依据落档）。" : "Creates a model_release approval with gate checks attached."}
          </Typography.Paragraph>
          <Form form={releaseForm} layout="vertical" data-testid="release-form"
            onFinish={(values) => void run(async () => {
              const versionId = values.model_version_id;
              const result = await createReleaseRequest(projectId!, versionId, {
                deployment_id: deploymentId!,
                model_version_id: versionId,
                preauthorization_id: values.preauthorization_id?.trim() || null,
                strategy: values.strategy || "canary",
              });
              setLastChecks(result.checks);
              setReleaseOpen(false);
            }, zh ? "发布申请已提交（审批中心可跟踪）" : "Release request submitted")}>
            <Form.Item name="model_version_id" label={zh ? "发布版本" : "Version"} rules={[{ required: true }]}>
              <Select options={versionOptions} placeholder={zh ? "选择版本" : "Pick a version"} />
            </Form.Item>
            <Form.Item name="strategy" label={zh ? "放量策略" : "Strategy"} initialValue="canary">
              <Select options={[
                { value: "canary", label: "canary" },
                { value: "immediate", label: "immediate" },
              ]} />
            </Form.Item>
            <Form.Item name="preauthorization_id" label={zh ? "预授权 ID（可选，免审批发布）" : "Preauthorization id"}>
              <Input placeholder="UUID" />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={lastChecks !== null} footer={null} width={640}
          onCancel={() => setLastChecks(null)} title={zh ? "门禁检查结果" : "Gate checks"}>
          {lastChecks && (
            <Table rowKey="check_key" size="small" pagination={false}
              dataSource={lastChecks}
              columns={[
                { title: zh ? "检查项" : "Check", dataIndex: "check_key" },
                {
                  title: zh ? "结论" : "Verdict", dataIndex: "verdict", width: 110,
                  render: (value: string) => <Tag color={value === "passed" ? "green" : value === "warning" ? "orange" : "red"}>{value}</Tag>,
                },
                { title: zh ? "阈值" : "Threshold", dataIndex: "threshold", width: 90 },
                { title: zh ? "实测" : "Observed", dataIndex: "observed", width: 90 },
              ]} />
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
