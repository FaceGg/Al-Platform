import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  App as AntApp, Button, Card, Descriptions, Form, Input, InputNumber, Modal, Select, Space,
  Table, Tabs, Tag, Typography,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { listDatasetVersions } from "../api/datasets";
import {
  apiErrorText, createQualitySop, freezeSpcBaseline, getAlertSettings, listQualitySops,
  listSpcBaselines, updateAlertSettings,
} from "../api/qualityAlerts";
import type { AlertSettings, QualitySop, QualitySpcBaseline, ResolvedAlertSettings } from "../api/qualityAlerts";
import { listQualityStations } from "../api/qualityDomain";
import type { QualityStation } from "../api/qualityDomain";
import { useI18n } from "../i18n";
import { formatLocalTime } from "../utils/time";

/** 质量管理 · 配置 / SOP 维护（E07/E08/D14，技术方案 §9.4/§9.8）。
 *
 * 三个页签：SOP 版本（按编号、适用工况、生效时间版本化）/ SPC 基线（冻结与历史）/
 * 预警规则（触发下限与分级阈值、SLA、合并窗口，按场景配置）。
 */

type TabKey = "sops" | "baselines" | "rules";

function lines(value: string | undefined): string[] {
  return (value ?? "").split("\n").map((item) => item.trim()).filter(Boolean);
}

export default function QualitySopsPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [searchParams, setSearchParams] = useSearchParams();
  const { projects, projectId, setProjectId, scenes } = useQualityAlertLookups();
  const [tab, setTab] = useState<TabKey>((searchParams.get("tab") as TabKey) || "sops");
  const [sops, setSops] = useState<QualitySop[]>([]);
  const [sopModal, setSopModal] = useState(false);
  const [sopForm] = Form.useForm<{ code: string; title: string; scene_id?: string; condition_value?: string; spec_exceed?: string; spc_exceed?: string; ai_risk?: string }>();
  const [sceneId, setSceneId] = useState<string | undefined>(undefined);
  const [baselines, setBaselines] = useState<QualitySpcBaseline[]>([]);
  const [stations, setStations] = useState<QualityStation[]>([]);
  const [datasetVersions, setDatasetVersions] = useState<Awaited<ReturnType<typeof listDatasetVersions>>>([]);
  const [baselineModal, setBaselineModal] = useState(false);
  const [baselineForm] = Form.useForm<{
    dataset_version_id: string; field: string; station_id?: string; condition_value?: string;
    row_index_from?: number; row_index_to?: number; time_from?: string; time_to?: string;
  }>();
  const [rules, setRules] = useState<{ alert_settings: AlertSettings; resolved: ResolvedAlertSettings } | null>(null);
  const [rulesForm] = Form.useForm<AlertSettings>();
  const [busy, setBusy] = useState(false);

  const selectedScene = useMemo(() => scenes.find((item) => item.id === sceneId), [scenes, sceneId]);

  const loadSops = useCallback(() => {
    if (!projectId) { setSops([]); return; }
    listQualitySops(projectId).then(setSops).catch((e) => message.error(apiErrorText(e)));
  }, [projectId, message]);

  useEffect(() => { loadSops(); }, [loadSops]);

  useEffect(() => {
    if (!projectId) { setDatasetVersions([]); return; }
    listDatasetVersions(projectId).then(setDatasetVersions).catch(() => setDatasetVersions([]));
  }, [projectId]);

  useEffect(() => {
    if (projectId) setSceneId((current) => current ?? scenes[0]?.id);
  }, [projectId, scenes]);

  const loadBaselines = useCallback(() => {
    if (!projectId || !sceneId) { setBaselines([]); return; }
    listSpcBaselines(projectId, sceneId).then(setBaselines).catch((e) => message.error(apiErrorText(e)));
    listQualityStations(projectId, sceneId).then(setStations).catch(() => setStations([]));
  }, [projectId, sceneId, message]);

  const loadRules = useCallback(() => {
    if (!projectId || !sceneId) { setRules(null); return; }
    getAlertSettings(projectId, sceneId).then((data) => {
      setRules(data);
      // 表单只回填显式配置的键；留空的键跟随平台默认
      rulesForm.setFieldsValue(data.alert_settings);
    }).catch((e) => message.error(apiErrorText(e)));
  }, [projectId, sceneId, message, rulesForm]);

  useEffect(() => { if (tab === "baselines") loadBaselines(); }, [tab, loadBaselines]);
  useEffect(() => { if (tab === "rules") loadRules(); }, [tab, loadRules]);

  const run = async (operation: () => Promise<unknown>, successText: string, after?: () => void) => {
    setBusy(true);
    try {
      await operation();
      message.success(successText);
      after?.();
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const sopColumns = [
    { title: zh ? "编号" : "Code", dataIndex: "code", key: "code", width: 140 },
    { title: zh ? "版本" : "Version", dataIndex: "version", key: "version", width: 70 },
    { title: zh ? "标题" : "Title", dataIndex: "title", key: "title" },
    {
      title: zh ? "适用工况" : "Condition", dataIndex: "condition_value", key: "condition_value", width: 120,
      render: (value: string | null) => value || (zh ? "全工况" : "All"),
    },
    {
      title: zh ? "生效时间" : "Effective from", dataIndex: "effective_from", key: "effective_from", width: 170,
      render: (value: string | null) => (value ? formatLocalTime(value) : "-"),
    },
    {
      title: zh ? "状态" : "Status", dataIndex: "is_active", key: "is_active", width: 90,
      render: (value: boolean) => (value ? <Tag color="green">{zh ? "生效中" : "Active"}</Tag> : <Tag>{zh ? "已退役" : "Retired"}</Tag>),
    },
  ];

  const sopExpanded = (row: QualitySop) => (
    <Descriptions size="small" column={1}>
      <Descriptions.Item label={zh ? "规格越限处置指引" : "Spec exceed"}>{row.content.spec_exceed?.join("；") || "-"}</Descriptions.Item>
      <Descriptions.Item label={zh ? "SPC 越限处置指引" : "SPC exceed"}>{row.content.spc_exceed?.join("；") || "-"}</Descriptions.Item>
      <Descriptions.Item label={zh ? "AI 风险处置指引" : "AI risk"}>{row.content.ai_risk?.join("；") || "-"}</Descriptions.Item>
    </Descriptions>
  );

  const baselineColumns = [
    { title: zh ? "字段" : "Field", dataIndex: "field", key: "field" },
    { title: zh ? "版本" : "Version", dataIndex: "version", key: "version", width: 70 },
    {
      title: zh ? "范围" : "Scope", key: "scope", width: 200,
      render: (_: unknown, row: QualitySpcBaseline) => [
        row.station_id ? stations.find((item) => item.id === row.station_id)?.code ?? row.station_id.slice(0, 8) : (zh ? "全工位" : "All stations"),
        row.condition_value ?? (zh ? "全工况" : "All conditions"),
      ].join(" / "),
    },
    {
      title: zh ? "中心 / σ" : "Center / σ", key: "center", width: 160,
      render: (_: unknown, row: QualitySpcBaseline) => `${row.center.toFixed(4)} / ${row.sigma.toFixed(4)}`,
    },
    { title: zh ? "样本数" : "Samples", dataIndex: "sample_count", key: "sample_count", width: 80 },
    {
      title: zh ? "时段" : "Window", key: "window", width: 320,
      render: (_: unknown, row: QualitySpcBaseline) => `${row.window_start ? formatLocalTime(row.window_start) : "-"} ~ ${row.window_end ? formatLocalTime(row.window_end) : "-"}`,
    },
    {
      title: zh ? "状态" : "Status", dataIndex: "is_active", key: "is_active", width: 90,
      render: (value: boolean) => (value ? <Tag color="green">{zh ? "活动中" : "Active"}</Tag> : <Tag>{zh ? "已失效" : "Superseded"}</Tag>),
    },
  ];

  const chosenVersionId = Form.useWatch("dataset_version_id", baselineForm);
  const chosenVersion = datasetVersions.find((item) => item.id === chosenVersionId);

  const submitRules = (values: AlertSettings) => {
    if (!projectId || !sceneId || !rules) return;
    const overrides = Object.fromEntries(
      Object.entries(values).filter(([, value]) => value !== null && value !== undefined && value !== ""),
    ) as AlertSettings;
    // 与后端同一口径：校验的是和平台默认合并后的完整规则
    const resolved = { ...rules.resolved, ...overrides } as ResolvedAlertSettings;
    if (!(resolved.trigger_threshold <= resolved.high_threshold && resolved.high_threshold <= resolved.critical_threshold)) {
      message.error(zh ? "阈值须满足：触发 ≤ 高 ≤ 严重" : "Thresholds must satisfy trigger ≤ high ≤ critical");
      return;
    }
    void run(
      () => updateAlertSettings(projectId, sceneId, overrides),
      zh ? "预警规则已保存" : "Alert rules saved",
      () => { void loadRules(); },
    );
  };

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_sops" testId="v2-quality-sops">
        <PageHeading
          section="quality"
          navKey="quality_sops"
          desc={zh
            ? "处置配置：SOP 按编号、适用工况、生效时间版本化；SPC 基线从稳定时段冻结；预警规则按场景配置。处置单会记录当时生效的 SOP 与基线版本。"
            : "Disposition configuration: versioned SOPs, frozen SPC baselines and per-scene alert rules. Each disposition record freezes the SOP and baseline versions in force."}
          actions={
            <Select
              aria-label={zh ? "选择项目" : "Select project"}
              style={{ minWidth: 180 }}
              placeholder={zh ? "选择项目" : "Select project"}
              value={projectId ?? undefined}
              onChange={(value: string) => { setProjectId(value); setSceneId(undefined); }}
              options={projects.map((p) => ({ value: p.id, label: p.name }))}
            />
          }
        />
        <Card>
          <Tabs
            activeKey={tab}
            onChange={(key) => {
              setTab(key as TabKey);
              const next = new URLSearchParams(searchParams);
              if (key === "sops") next.delete("tab"); else next.set("tab", key);
              setSearchParams(next, { replace: true });
            }}
            items={[
              {
                key: "sops",
                label: zh ? "SOP 版本" : "SOP versions",
                children: (
                  <>
                    <Space style={{ marginBottom: 12 }} wrap>
                      <Button
                        type="primary" icon={<PlusOutlined />} data-testid="new-sop"
                        onClick={() => { sopForm.resetFields(); setSopModal(true); }}
                      >
                        {zh ? "新建 SOP 版本" : "New SOP version"}
                      </Button>
                      <Typography.Text type="secondary">
                        {zh ? "同一编号与工况再次创建即产生新版本，旧版本退役但保留可查。" : "Creating the same code and condition again produces a new version; old versions are retired but kept."}
                      </Typography.Text>
                    </Space>
                    <Table
                      rowKey="id" size="small" columns={sopColumns} dataSource={sops} pagination={false}
                      expandable={{ expandedRowRender: sopExpanded }}
                      locale={{ emptyText: zh ? "暂无 SOP：点击「新建 SOP 版本」创建第一条" : "No SOPs yet" }}
                    />
                  </>
                ),
              },
              {
                key: "baselines",
                label: zh ? "SPC 基线" : "SPC baselines",
                children: (
                  <>
                    <Space style={{ marginBottom: 8 }} wrap>
                      <Select
                        aria-label={zh ? "基线场景" : "Baseline scene"}
                        style={{ minWidth: 220 }}
                        placeholder={zh ? "选择场景" : "Select scene"}
                        value={sceneId}
                        onChange={setSceneId}
                        options={scenes.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))}
                      />
                      <Button
                        type="primary" icon={<PlusOutlined />} data-testid="freeze-baseline"
                        disabled={!sceneId}
                        onClick={() => { baselineForm.resetFields(); setBaselineModal(true); }}
                      >
                        {zh ? "冻结基线" : "Freeze baseline"}
                      </Button>
                    </Space>
                    <Typography.Paragraph type="secondary">
                      {zh
                        ? "从数据集版本里选一段已结束的稳定时段冻结基线（I-MR 口径：中心 = 均值，σ = 平均移动极差 / 1.128；20–500 个样本，时段内恒定会被拒绝）。重新冻结生成新版本，旧版本失效但保留可查；没有冻结基线的工位不产生 σ 类判据。"
                        : "Freeze a finished, stable window of a dataset version (I-MR: center = mean, σ = mean moving range / 1.128; 20–500 samples, constant windows rejected). Refreezing creates a new version."}
                    </Typography.Paragraph>
                    <Table
                      rowKey="id" size="small" columns={baselineColumns} dataSource={baselines} pagination={false}
                      locale={{ emptyText: zh ? "该场景暂无基线" : "No baselines for this scene" }}
                    />
                  </>
                ),
              },
              {
                key: "rules",
                label: zh ? "预警规则" : "Alert rules",
                children: (
                  <>
                    <Select
                      aria-label={zh ? "规则场景" : "Rules scene"}
                      style={{ minWidth: 220, marginBottom: 12 }}
                      placeholder={zh ? "选择场景" : "Select scene"}
                      value={sceneId}
                      onChange={setSceneId}
                      options={scenes.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))}
                    />
                    {rules && selectedScene && (
                      <Form form={rulesForm} layout="vertical" style={{ maxWidth: 860 }} onFinish={submitRules} data-testid="rules-form">
                        <Typography.Paragraph type="secondary" data-testid="rules-defaults">
                          {zh
                            ? `平台默认：触发 ${rules.resolved.trigger_threshold} / 高 ${rules.resolved.high_threshold} / 严重 ${rules.resolved.critical_threshold}；SLA ${rules.resolved.sla_hours} 小时；合并窗口 ${rules.resolved.merge_window_minutes} 分钟。留空即跟随平台默认。`
                            : `Platform defaults: trigger ${rules.resolved.trigger_threshold} / high ${rules.resolved.high_threshold} / critical ${rules.resolved.critical_threshold}; SLA ${rules.resolved.sla_hours} h; merge window ${rules.resolved.merge_window_minutes} min.`}
                        </Typography.Paragraph>
                        <Space wrap size="middle" align="start">
                          <Form.Item name="trigger_threshold" label={zh ? "触发下限（≥ 即预警）" : "Trigger threshold"} extra={zh ? "独立于分级阈值" : "Independent of severity"}>
                            <InputNumber min={0} max={1} step={0.05} style={{ width: 150 }} />
                          </Form.Item>
                          <Form.Item name="high_threshold" label={zh ? "高风险阈值" : "High threshold"}>
                            <InputNumber min={0} max={1} step={0.05} style={{ width: 150 }} />
                          </Form.Item>
                          <Form.Item name="critical_threshold" label={zh ? "严重阈值" : "Critical threshold"}>
                            <InputNumber min={0} max={1} step={0.05} style={{ width: 150 }} />
                          </Form.Item>
                          <Form.Item name="sla_hours" label={zh ? "SLA 时长（小时）" : "SLA (hours)"}>
                            <InputNumber min={1} max={720} style={{ width: 150 }} />
                          </Form.Item>
                          <Form.Item name="merge_window_minutes" label={zh ? "同因合并窗口（分钟）" : "Merge window (min)"}>
                            <InputNumber min={1} max={1440} style={{ width: 150 }} />
                          </Form.Item>
                        </Space>
                        <Button type="primary" htmlType="submit" loading={busy} data-testid="save-rules">
                          {zh ? "保存规则" : "Save rules"}
                        </Button>
                      </Form>
                    )}
                  </>
                ),
              },
            ]}
          />
        </Card>

        <Modal
          open={sopModal} destroyOnClose
          title={zh ? "新建 SOP 版本" : "New SOP version"}
          okText={zh ? "创建" : "Create"} confirmLoading={busy}
          onCancel={() => setSopModal(false)} onOk={() => sopForm.submit()}
        >
          <Form
            form={sopForm} layout="vertical" data-testid="sop-form"
            onFinish={(values) => void run(
              () => createQualitySop(projectId!, {
                code: values.code.trim(), title: values.title.trim(),
                scene_id: values.scene_id ?? null, condition_value: values.condition_value?.trim() || null,
                content: {
                  spec_exceed: lines(values.spec_exceed), spc_exceed: lines(values.spc_exceed),
                  ai_risk: lines(values.ai_risk),
                },
              }),
              zh ? "SOP 版本已创建" : "SOP version created",
              () => { setSopModal(false); loadSops(); },
            )}
          >
            <Form.Item name="code" label={zh ? "编号" : "Code"} rules={[{ required: true }]}>
              <Input maxLength={64} placeholder="SOP-A" />
            </Form.Item>
            <Form.Item name="title" label={zh ? "标题" : "Title"} rules={[{ required: true }]}>
              <Input maxLength={256} />
            </Form.Item>
            <Form.Item name="scene_id" label={zh ? "适用场景（留空 = 项目级）" : "Scene (blank = project-wide)"}>
              <Select allowClear options={scenes.map((s) => ({ value: s.id, label: `${s.name}（${s.code}）` }))} />
            </Form.Item>
            <Form.Item name="condition_value" label={zh ? "适用工况（留空 = 全工况）" : "Condition (blank = all)"}>
              <Input maxLength={128} />
            </Form.Item>
            <Form.Item name="spec_exceed" label={zh ? "规格越限处置指引（每行一步）" : "Spec exceed guidance (one step per line)"}>
              <Input.TextArea rows={3} />
            </Form.Item>
            <Form.Item name="spc_exceed" label={zh ? "SPC 越限处置指引（每行一步）" : "SPC exceed guidance (one step per line)"}>
              <Input.TextArea rows={3} />
            </Form.Item>
            <Form.Item name="ai_risk" label={zh ? "AI 风险处置指引（每行一步）" : "AI risk guidance (one step per line)"}>
              <Input.TextArea rows={3} />
            </Form.Item>
          </Form>
        </Modal>

        <Modal
          open={baselineModal} destroyOnClose
          title={zh ? "冻结 SPC 基线" : "Freeze SPC baseline"}
          okText={zh ? "冻结" : "Freeze"} confirmLoading={busy}
          onCancel={() => setBaselineModal(false)} onOk={() => baselineForm.submit()}
        >
          <Form
            form={baselineForm} layout="vertical" data-testid="baseline-form"
            onFinish={(values) => void run(
              () => freezeSpcBaseline(projectId!, sceneId!, {
                dataset_version_id: values.dataset_version_id, field: values.field,
                station_id: values.station_id ?? null,
                condition_value: values.condition_value?.trim() || null,
                row_index_from: values.row_index_from ?? undefined,
                row_index_to: values.row_index_to ?? undefined,
                time_from: values.time_from?.trim() || undefined,
                time_to: values.time_to?.trim() || undefined,
              }),
              zh ? "基线已冻结" : "Baseline frozen",
              () => { setBaselineModal(false); loadBaselines(); },
            )}
          >
            <Form.Item name="dataset_version_id" label={zh ? "数据集版本" : "Dataset version"} rules={[{ required: true }]}>
              <Select
                showSearch optionFilterProp="label"
                options={datasetVersions.map((version) => ({
                  value: version.id,
                  label: `v${version.version} · ${version.source_name ?? ""} · ${version.row_count} ${zh ? "行" : "rows"}`,
                }))}
                onChange={() => baselineForm.setFieldValue("field", undefined)}
              />
            </Form.Item>
            <Form.Item name="field" label={zh ? "过程参数（字段）" : "Field"} rules={[{ required: true }]}>
              <Select
                showSearch optionFilterProp="value"
                options={(chosenVersion?.columns ?? []).map((column) => ({ value: column.name, label: `${column.name}（${column.dtype}）` }))}
              />
            </Form.Item>
            <Form.Item name="station_id" label={zh ? "工位（留空 = 场景级）" : "Station (blank = scene-wide)"}>
              <Select allowClear options={stations.map((station) => ({ value: station.id, label: `${station.name}（${station.code}）` }))} />
            </Form.Item>
            <Form.Item
              name="condition_value" label={zh ? "工况值（留空 = 全工况）" : "Condition (blank = all)"}
              extra={selectedScene?.condition_column
                ? (zh ? `按场景工况列「${selectedScene.condition_column}」匹配` : `Matched against condition column "${selectedScene.condition_column}"`)
                : (zh ? "场景未声明工况列：不做工况过滤" : "Scene has no condition column: no condition filter")}
            >
              <Input maxLength={128} />
            </Form.Item>
            <Space size="large">
              <Form.Item name="row_index_from" label={zh ? "起始行号" : "Row from"}>
                <InputNumber min={0} style={{ width: 150 }} />
              </Form.Item>
              <Form.Item name="row_index_to" label={zh ? "结束行号" : "Row to"}>
                <InputNumber min={0} style={{ width: 150 }} />
              </Form.Item>
            </Space>
            <Space size="large">
              <Form.Item name="time_from" label={zh ? "起始时间" : "Time from"} extra="2026-11-01T00:00:00">
                <Input style={{ width: 210 }} />
              </Form.Item>
              <Form.Item name="time_to" label={zh ? "结束时间" : "Time to"} extra="2026-11-01T08:00:00">
                <Input style={{ width: 210 }} />
              </Form.Item>
            </Space>
          </Form>
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
