import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  App as AntApp, Button, Card, Col, Empty, Modal, Row, Select, Space, Statistic, Table,
  Tag, Typography,
} from "antd";
import { ReloadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import {
  DRIFT_LEVEL_COLOR, DRIFT_LEVEL_LABELS, DRIFT_SIGNAL_LABELS,
  getDriftDeployments, getDriftReport, getDriftReports, proposeRetrain, triggerDriftScan,
} from "../api/qualitySpc";
import type { DriftDeploymentItem, DriftLevel, DriftReport, DriftReportDetail } from "../api/qualitySpc";
import { apiErrorText } from "../api/qualityAlerts";
import { useI18n } from "../i18n";
import { formatLocalTime } from "../utils/time";

/** 算法平台 · 模型运营 / 漂移监控（B1-09，技术方案 §9C）。
 *
 * 运行态部署的特征级漂移分级报告；漂移是触发器不是自动开关——
 * 「转重训提案」只通知项目负责人并留痕，不自动处置。
 */

const NOT_WIRED_TEXT: Record<string, string> = {
  pca_reconstruction_error: "PCA 重构误差（平台不保存全量特征向量，未接入）",
  score_psi_in_report: "分数级 PSI 并入报告（闭环内独立运行，未接入）",
  per_shard_buckets: "分片部署按「版本 × 工况」分桶（按部署主版本合并统计）",
};

export default function DriftMonitorPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const navigate = useNavigate();
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [deployments, setDeployments] = useState<DriftDeploymentItem[]>([]);
  const [reports, setReports] = useState<DriftReport[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [deploymentFilter, setDeploymentFilter] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [scanBusy, setScanBusy] = useState(false);
  const [detail, setDetail] = useState<DriftReportDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const role = localStorage.getItem("role");
  const canManage = role === "owner" || role === "editor";

  const load = useCallback(() => {
    if (!projectId) { setDeployments([]); setReports([]); setTotal(0); return; }
    setLoading(true);
    getDriftDeployments(projectId).then(setDeployments).catch((e) => message.error(apiErrorText(e)));
    getDriftReports(projectId, deploymentFilter, page, pageSize)
      .then((result) => { setReports(result.items); setTotal(result.total); })
      .catch((e) => message.error(apiErrorText(e)))
      .finally(() => setLoading(false));
  }, [projectId, deploymentFilter, page, pageSize, message]);

  useEffect(() => { load(); }, [load]);

  const scan = async () => {
    if (!projectId) return;
    setScanBusy(true);
    try {
      const summary = await triggerDriftScan(projectId);
      const levels = Object.entries(summary.levels ?? {})
        .map(([key, value]) => `${DRIFT_LEVEL_LABELS[lang][key as DriftLevel]} ×${value}`).join("，");
      message.success(zh
        ? `已扫描 ${summary.scanned} 个部署${levels ? `：${levels}` : "（没有运行态部署）"}`
        : `Scanned ${summary.scanned} deployments`);
      load();
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setScanBusy(false);
    }
  };

  const openDetail = async (report: DriftReport) => {
    setDetailLoading(true);
    try {
      setDetail(await getDriftReport(projectId!, report.id));
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setDetailLoading(false);
    }
  };

  const propose = async () => {
    if (!detail || !projectId) return;
    try {
      await proposeRetrain(projectId, detail.id);
      message.success(zh ? "重训提案已提交：已通知项目负责人并留痕（审批流程尚未开通）" : "Proposal submitted");
      setDetail(await getDriftReport(projectId, detail.id));
      load();
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const severityRank: Record<string, number> = { severe: 2, watch: 1, stable: 0 };
  const worstLevel: DriftLevel | null = (() => {
    const relevant = deployments.filter((item) => item.latest);
    if (!relevant.length) return null;
    return relevant.reduce((worst, item) => {
      const level = item.latest!.level;
      return severityRank[level] > (severityRank[worst] ?? -1) ? level : worst;
    }, "stable" as DriftLevel);
  })();

  const reportColumns = [
    {
      title: zh ? "时间" : "Time", dataIndex: "created_at", key: "created_at", width: 170,
      render: (value: string | null) => (value ? formatLocalTime(value) : "-"),
    },
    {
      title: zh ? "部署" : "Deployment", dataIndex: "deployment_name", key: "deployment_name", ellipsis: true,
    },
    {
      title: zh ? "级别" : "Level", dataIndex: "level", key: "level", width: 110,
      render: (value: DriftLevel) => <Tag color={DRIFT_LEVEL_COLOR[value]}>{DRIFT_LEVEL_LABELS[lang][value]}</Tag>,
    },
    { title: zh ? "样本数" : "Samples", dataIndex: "sample_count", key: "sample_count", width: 90 },
    {
      title: zh ? "信号" : "Signals", key: "signals", render: (_: unknown, row: DriftReport) => {
        const counts = (row.summary?.signal_counts ?? {}) as Record<string, number>;
        const entries = Object.entries(counts);
        return entries.length
          ? entries.map(([kind, count]) => (
            <Tag key={kind} color={kind === "feature_psi" ? "orange" : "gold"}>
              {DRIFT_SIGNAL_LABELS[lang][kind as keyof typeof DRIFT_SIGNAL_LABELS[typeof lang]] ?? kind} ×{String(count)}
            </Tag>
          ))
          : "-";
      },
    },
    {
      title: zh ? "重训提案" : "Proposal", key: "proposal", width: 110,
      render: (_: unknown, row: DriftReport) => (row.proposal_at
        ? <Tag color="purple">{zh ? "已提交" : "Submitted"}</Tag> : "-"),
    },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 90, fixed: "right" as const,
      render: (_: unknown, row: DriftReport) => (
        <Button size="small" type="link" data-testid={`open-report-${row.id}`} onClick={() => void openDetail(row)}>
          {zh ? "明细" : "Detail"}
        </Button>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="algo" navKey="drift_monitor" testId="v2-drift-monitor">
        <PageHeading
          section="algo"
          navKey="drift_monitor"
          desc={zh
            ? "独立漂移监控：运行态部署的特征级分布与训练基线比对（PSI），缺失与集中异常一并检查；严重级自动通知，处置由人工评估。"
            : "Feature-level drift reports for running deployments; severe drift notifies, disposal stays manual."}
          actions={(
            <Space wrap>
              <Select
                aria-label={zh ? "选择项目" : "Select project"} style={{ minWidth: 170 }}
                placeholder={zh ? "选择项目" : "Project"} value={projectId ?? undefined}
                onChange={(value: string) => { setProjectId(value); setPage(1); setDeploymentFilter(undefined); }}
                options={projects.map((item) => ({ value: item.id, label: item.name }))}
              />
              <Select
                aria-label={zh ? "部署筛选" : "Deployment filter"} allowClear style={{ minWidth: 180 }}
                placeholder={zh ? "全部部署" : "All deployments"} value={deploymentFilter}
                onChange={(value: string | undefined) => { setDeploymentFilter(value); setPage(1); }}
                options={deployments.map((item) => ({ value: item.id, label: item.name }))}
              />
              {canManage && (
                <Button icon={<ThunderboltOutlined />} loading={scanBusy} onClick={() => void scan()} data-testid="drift-scan">
                  {zh ? "立即扫描" : "Scan now"}
                </Button>
              )}
              <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>{zh ? "刷新" : "Refresh"}</Button>
            </Space>
          )}
        />
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title={zh ? "运行态部署" : "Running deployments"} value={deployments.length}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title={zh ? "最严重状态" : "Worst level"}
                formatter={() => (worstLevel
                  ? <Tag color={DRIFT_LEVEL_COLOR[worstLevel]}>{DRIFT_LEVEL_LABELS[lang][worstLevel]}</Tag>
                  : "-")}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title={zh ? "有基线" : "With baseline"} value={deployments.filter((item) => item.has_baseline).length} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title={zh ? "报告总数" : "Reports"} value={total} />
            </Card>
          </Col>
        </Row>
        {deployments.some((item) => !item.has_baseline) && (
          <Typography.Paragraph type="secondary" data-testid="drift-no-baseline-note" style={{ marginBottom: 12 }}>
            {zh
              ? "标注「无基线」的部署缺少训练数据血缘（如外部导入模型），做不了特征级漂移检测，只有样本计数。"
              : "Deployments without a training-data lineage cannot run feature-level drift checks."}
          </Typography.Paragraph>
        )}
        <Card>
          <Table
            rowKey="id" loading={loading} columns={reportColumns} dataSource={reports} scroll={{ x: 900 }}
            pagination={{
              current: page, pageSize, total, showSizeChanger: true,
              onChange: (nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); },
            }}
            locale={{ emptyText: <Empty description={zh ? "还没有漂移报告：定时扫描（默认每 5 分钟）产出后在此可见，也可点「立即扫描」" : "No drift reports yet"} /> }}
          />
        </Card>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }} data-testid="drift-footnote">
          {zh
            ? "口径：特征级 PSI = Σ(实际占比 − 训练占比)·ln(实际/训练)，按训练分布的等概率十分位箱计算；分级 严重 ≥ 0.25 / 关注 ≥ 0.10（可配）；窗口默认 24 小时、最小样本 200。数据质量检查：缺失率 > 5%、取值全部集中在训练分布的同一个分箱内。漂移是触发信号，平台不自动重训或回滚。"
            : "Feature PSI against the training distribution's deciles; severe ≥ 0.25 / watch ≥ 0.10; 24h window, min 200 samples. Drift is a trigger, never an automatic action."}
        </Typography.Paragraph>
        <Modal
          open={Boolean(detail)} destroyOnClose width={860}
          onCancel={() => setDetail(null)}
          footer={canManage && detail?.level !== "insufficient" && !detail?.proposal_at ? [
            <Button key="close" onClick={() => setDetail(null)}>{zh ? "关闭" : "Close"}</Button>,
            <Button key="propose" type="primary" data-testid="propose-retrain" onClick={() => void propose()}>
              {zh ? "转重训提案" : "Propose retrain"}
            </Button>,
          ] : undefined}
          title={detail ? (
            <Space wrap>
              <span>{zh ? "漂移报告明细" : "Drift report"}</span>
              <Tag color={DRIFT_LEVEL_COLOR[detail.level]}>{DRIFT_LEVEL_LABELS[lang][detail.level]}</Tag>
              <Typography.Text type="secondary">{detail.deployment_name}</Typography.Text>
            </Space>
          ) : null}
        >
          {detail && (
            <>
              <Row gutter={16} style={{ marginBottom: 12 }}>
                <Col span={6}><Statistic title={zh ? "样本数" : "Samples"} value={detail.sample_count} /></Col>
                <Col span={9}><Statistic title={zh ? "窗口起" : "Window from"} formatter={() => formatLocalTime(detail.started_at)} /></Col>
                <Col span={9}><Statistic title={zh ? "窗口止" : "Window to"} formatter={() => formatLocalTime(detail.ended_at)} /></Col>
              </Row>
              {detail.proposal_at && (
                <Typography.Paragraph>
                  <Tag color="purple">{zh ? `重训提案已于 ${formatLocalTime(detail.proposal_at)} 提交` : `Proposal submitted ${detail.proposal_at}`}</Tag>
                </Typography.Paragraph>
              )}
              {(detail.summary?.notes as string[] | undefined)?.length ? (
                <Typography.Paragraph type="secondary">{(detail.summary?.notes as string[]).join("；")}</Typography.Paragraph>
              ) : null}
              <Table
                rowKey={(row) => `${row.signal_kind}-${row.feature_name}`}
                size="small" pagination={false}
                dataSource={detail.features}
                data-testid="drift-features"
                columns={[
                  { title: zh ? "特征" : "Feature", dataIndex: "feature_name" },
                  {
                    title: zh ? "信号" : "Signal", dataIndex: "signal_kind", width: 180,
                    render: (value: keyof typeof DRIFT_SIGNAL_LABELS[typeof lang]) => DRIFT_SIGNAL_LABELS[lang][value] ?? value,
                  },
                  { title: zh ? "数值" : "Value", dataIndex: "value", width: 100, render: (value: number) => value.toFixed(4) },
                  { title: zh ? "阈值" : "Threshold", dataIndex: "threshold", width: 90, render: (value: number) => value.toFixed(2) },
                  {
                    title: zh ? "级别" : "Level", dataIndex: "level", width: 90,
                    render: (value: string) => <Tag color={value === "severe" ? "red" : value === "watch" ? "gold" : "green"}>{value}</Tag>,
                  },
                  {
                    title: zh ? "实测占比" : "Observed", key: "observed", width: 220,
                    render: (_: unknown, row: DriftReportDetail["features"][number]) => {
                      const shares = (row.detail?.observed_shares ?? []) as number[];
                      return shares.length
                        ? <Typography.Text style={{ fontSize: 12 }} type="secondary">{shares.map((share) => `${(share * 100).toFixed(1)}%`).join(" / ")}</Typography.Text>
                        : (row.detail?.missing != null ? <Typography.Text type="secondary">{String(row.detail.missing)} / {String(row.detail.total)}</Typography.Text> : "-");
                    },
                  },
                ]}
                locale={{ emptyText: zh ? "无信号：窗口内各特征分布与训练基线一致" : "No signals: distributions match the baseline" }}
              />
              {detail.not_wired.length > 0 && (
                /* 如实显示本期未接入的信号，防止被当成已做 */
                <Typography.Paragraph type="secondary" style={{ marginTop: 12 }} data-testid="drift-not-wired">
                  {zh ? "未接入的检测项：" : "Not wired yet: "}
                  {detail.not_wired.map((key) => NOT_WIRED_TEXT[key] ?? key).join("；")}。
                </Typography.Paragraph>
              )}
            </>
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
