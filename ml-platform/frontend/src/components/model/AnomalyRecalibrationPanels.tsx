import { useEffect, useMemo, useState } from "react";
import {
  Alert, Button, Input, InputNumber, Select, Space, Table, Tag, Typography, message,
} from "antd";
import { formatApiError } from "../../api/client";
import {
  addFleetShard, deriveSupervisedDataset, fetchFleetOverview, labelRecalibrateVersion,
  recalibrateDeviceVersion,
  type DerivedSupervisedDatasetResult, type DeviceRecalibrateResult, type FleetShardCreatePayload,
  type FleetShardResult, type LabelRecalibrateResult,
} from "../../api/modelRegistry";

const { Text } = Typography;

/** 标注/标定数据集候选项：artifact id（后端 labeled_artifact_id / calibration_artifact_id）+ 展示名。 */
export type AnomalyArtifactOption = { id: string; name: string };

/** M6 档 1 门槛错误码（后端 409，见技术方案 §6.2 fail-closed）。 */
const M6_GATE_CODE = "M6_GATE_NOT_UNLOCKED";
/** M6 档 1 门槛：confirmed_fault ≥ 50（且形态簇 ≥ 2）。 */
const M6_MIN_CONFIRMED = 50;

function apiErrorCode(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: { code?: unknown } } } })?.response?.data?.detail;
  return detail && typeof detail.code === "string" ? detail.code : "";
}

/** 从后端门槛错误文案里取当前 confirmed 条数（"…：confirmed 12/50、形态簇 1/2…"）。 */
function confirmedCountFromMessage(error: unknown): number | null {
  const detail = (error as { response?: { data?: { detail?: { message?: unknown } } } })?.response?.data?.detail;
  const text = typeof detail?.message === "string" ? detail.message : "";
  const matched = text.match(/confirmed\s*(\d+)\s*\/\s*\d+/i);
  return matched ? Number(matched[1]) : null;
}

/** M6 错误文案：门槛未达（409）时给出「confirmed_fault ≥50 未达，当前 N 条——继续标注积累」。 */
function m6ErrorText(error: unknown): string {
  const base = formatApiError(error, "M6 操作失败");
  if (apiErrorCode(error) !== M6_GATE_CODE) return base;
  const count = confirmedCountFromMessage(error);
  return `confirmed_fault ≥${M6_MIN_CONFIRMED} 未达，当前 ${count ?? "—"} 条——继续标注积累（${base}）`;
}

/**
 * M6 半监督档 1：标签阈值重标定 + 弱监督派生导出（技术方案 §6.2 / §2.3.3）。
 *
 * 入口条件由调用方保证（模型库版本操作区：approval_status=approved 且
 * output_schema.task=anomaly）。面板本身只做两件事：
 * 1. 在标注数据集（带 feedback 标签的回流集）上重算最优阈值——门槛 fail-closed，
 *    confirmed_fault < 50 时后端返回 409 M6_GATE_NOT_UNLOCKED，界面提示继续标注积累；
 * 2. 把带标签回流行导出为监督数据集（弱监督演进 → 可直接建监督分类任务）。
 *
 * 结果展示：新旧阈值对比 / confirmed 计数 / 误报形态报表（形态簇表）/ 派生版本链接。
 */
export function LabelRecalibratePanel({ versionId, labeledArtifacts, defaultArtifactId, projectId }: {
  versionId: string | null;
  labeledArtifacts: AnomalyArtifactOption[];
  defaultArtifactId?: string | null;
  /** 所在项目（可选）：派生链接带 projectId 才能直达该项目的数据管理页。 */
  projectId?: string | null;
}): JSX.Element | null {
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<LabelRecalibrateResult | null>(null);
  const [derived, setDerived] = useState<DerivedSupervisedDatasetResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const options = useMemo(
    () => labeledArtifacts.map((item) => ({ value: item.id, label: item.name })),
    [labeledArtifacts],
  );

  // 默认选中：显式选择 > defaultArtifactId（命中候选项时）> 空（用户自选）。
  const selectedArtifactId = useMemo(() => {
    if (artifactId) return artifactId;
    if (defaultArtifactId && labeledArtifacts.some((item) => item.id === defaultArtifactId)) {
      return defaultArtifactId;
    }
    return null;
  }, [artifactId, defaultArtifactId, labeledArtifacts]);

  const runLabelRecalibrate = async () => {
    if (!versionId || busy) return;
    if (!selectedArtifactId) {
      setError("请选择标注数据集（带 confirmed/false_alarm 标签的回流集）");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await labelRecalibrateVersion(versionId, { labeled_artifact_id: selectedArtifactId }));
      message.success("M6 档 1 阈值重标定完成，新版本待审批后挂载");
    } catch (err) {
      setError(m6ErrorText(err));
    } finally {
      setBusy(false);
    }
  };

  const runDeriveSupervised = async () => {
    if (!versionId || busy) return;
    if (!selectedArtifactId) {
      setError("请选择标注数据集（带 confirmed/false_alarm 标签的回流集）");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setDerived(await deriveSupervisedDataset(versionId, { labeled_artifact_id: selectedArtifactId }));
      message.success("派生监督数据集已生成（数据管理可见）");
    } catch (err) {
      setError(formatApiError(err, "M6 操作失败"));
    } finally {
      setBusy(false);
    }
  };

  if (!versionId) return null;

  return (
    <div
      data-testid="label-recalibrate-panel"
      style={{ border: "1px solid var(--v2-line, #eee)", borderRadius: 8, padding: "8px 12px" }}
    >
      <Space direction="vertical" size="small" style={{ width: "100%" }}>
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <Text strong style={{ fontSize: 13 }}>M6 半监督档 1：标签阈值重标定 + 派生监督数据集</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>源版本 {versionId}</Text>
        </Space>
        <Space wrap size={8}>
          <Select
            aria-label="标注数据集"
            style={{ width: 260 }}
            size="small"
            placeholder="标注数据集"
            value={selectedArtifactId ?? undefined}
            options={options}
            onChange={(value) => setArtifactId(String(value))}
          />
          <Button size="small" type="primary" loading={busy} onClick={() => void runLabelRecalibrate()}>
            M6 档 1 阈值重标定（confirmed≥50）
          </Button>
          <Button size="small" loading={busy} onClick={() => void runDeriveSupervised()}>
            派生监督数据集
          </Button>
        </Space>
        {labeledArtifacts.length === 0 && (
          <Alert type="info" showIcon message="暂无可选标注数据集：请先在数据管理上传带标签的回流数据集" />
        )}
        {error && <Alert type="warning" showIcon message={error} />}
        {result && (
          <Alert
            type="success"
            showIcon
            message={(
              <span>
                M6 重标定完成：阈值 {result.old_threshold ?? "—"} → <Text strong>{result.new_threshold}</Text>
                （loss {result.loss}，confirmed {result.confirmed_count} / 误报 {result.false_alarm_count}），
                新版本 {result.registered_model_name}（{result.version_id}，待审批后挂载）
              </span>
            )}
            description={(
              <Space direction="vertical" size={4} style={{ width: "100%" }}>
                {/* 误报形态报表（技术方案 §3.2 结果展示项）：按形态簇给出样本数与
                    密集特征（feature + mean_z），供误标质量诊断 */}
                <Text strong style={{ fontSize: 12 }}>
                  误报形态报表（样本 {result.false_alarm_report?.sample_count ?? 0}）
                </Text>
                <Table
                  size="small"
                  pagination={false}
                  rowKey={(row) => String(row.cluster)}
                  dataSource={result.false_alarm_report?.clusters ?? []}
                  locale={{ emptyText: "无误报形态簇" }}
                  columns={[
                    { title: "形态簇", dataIndex: "cluster", width: 72 },
                    { title: "样本数", dataIndex: "sample_count", width: 72 },
                    {
                      title: "密集特征（mean_z）",
                      key: "dense_features",
                      render: (_value: unknown, row) => (
                        <Space size={4} wrap>
                          {(row.dense_features ?? []).length === 0
                            ? <Text type="secondary">—</Text>
                            : row.dense_features.map((item) => (
                              <Tag key={item.feature} style={{ fontSize: 11 }}>
                                {item.feature} {item.mean_z}
                              </Tag>
                            ))}
                        </Space>
                      ),
                    },
                  ]}
                />
                <Text style={{ fontSize: 12 }}>
                  派生版本：
                  <a href={projectId ? `/models?projectId=${projectId}` : "/models"}>
                    {result.registered_model_name}（{result.version_id}）
                  </a>
                </Text>
              </Space>
            )}
          />
        )}
        {derived && (
          <Alert
            type="info"
            showIcon
            message={(
              <span>
                派生监督数据集已生成（{derived.positives} 正 / {derived.negatives} 负），
                可在数据管理中查看并创建监督分类任务（弱监督演进）
              </span>
            )}
            description={(
              <a href={projectId ? `/data?projectId=${projectId}` : "/data"}>
                {derived.dataset_name}（artifact {derived.dataset_artifact_id}，{derived.rows} 行，标签列 {derived.label_column}）
              </a>
            )}
          />
        )}
      </Space>
    </div>
  );
}

/**
 * M9 新设备重标定 + 迁移版本挂载（技术方案 §7.2 / §7.1.4，三期 M9）。
 *
 * 现场流程：新设备采一批**纯正常**数据 → 选标定数据集 + 填工况值（设备号/
 * 工位号）→ `recalibrate-device` 只重跑标定层（不动检测器主体）→ fleet_fit
 * 判定：compatible → 可挂载；unfit → §7.2「不硬迁」——版本仍产出但标记 unfit，
 * 界面明确拒挂并提示独立建模。
 *
 * 挂载走 `fleet-shards`：新 stable revision = 既有分片全量复制 + 新分片；工况列
 * 必须与部署一致（服务端 fail-closed），故按部署 fleet-overview 读出后透传。
 */
export function DeviceRecalibratePanel({ deploymentId, sourceVersionId, calibrationArtifact, datasets }: {
  deploymentId: string | null;
  sourceVersionId: string | null;
  calibrationArtifact: AnomalyArtifactOption | null;
  datasets: AnomalyArtifactOption[];
}): JSX.Element | null {
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const [conditionValue, setConditionValue] = useState("");
  const [conditionColumn, setConditionColumn] = useState<string | null>(null);
  const [rows, setRows] = useState<number | null>(null);
  const [totalRows, setTotalRows] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<DeviceRecalibrateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState<FleetShardResult | null>(null);
  const [mountError, setMountError] = useState<string | null>(null);

  // 标定数据集默认取闭环回流的报错数据集（与 M6 面板同一数据源）
  const selectedArtifactId = artifactId ?? calibrationArtifact?.id ?? null;
  const artifactOptions = [
    ...(calibrationArtifact
      ? [{ value: calibrationArtifact.id, label: `${calibrationArtifact.name}（回流报错集）` }]
      : []),
    ...datasets
      .filter((item) => item.id !== calibrationArtifact?.id)
      .map((item) => ({ value: item.id, label: item.name })),
  ];

  // 部署工况列（挂载 fail-closed 校验用）：读不到则不传（服务端按缺省处理）
  useEffect(() => {
    if (!deploymentId) {
      setConditionColumn(null);
      return;
    }
    let cancelled = false;
    fetchFleetOverview(deploymentId)
      .then((data) => { if (!cancelled) setConditionColumn(data?.condition_column ?? null); })
      .catch(() => { if (!cancelled) setConditionColumn(null); });
    return () => { cancelled = true; };
  }, [deploymentId]);

  const runRecalibrate = async () => {
    if (!sourceVersionId || busy) return;
    const artifact = selectedArtifactId;
    const condition = conditionValue.trim();
    if (!artifact || !condition) {
      setError(!artifact ? "请选择标定数据集" : "请填写工况值（设备号/工位号）");
      return;
    }
    setBusy(true);
    setError(null);
    setMounted(null);
    setMountError(null);
    try {
      setResult(await recalibrateDeviceVersion(sourceVersionId, {
        calibration_artifact_id: artifact,
        condition_value: condition,
      }));
      message.success("M9 设备重标定完成");
    } catch (err) {
      setError(formatApiError(err, "M9 设备重标定失败"));
    } finally {
      setBusy(false);
    }
  };

  const runMount = async () => {
    if (!deploymentId || !result || busy) return;
    if (result.unfit_for_fleet || !result.fleet_fit?.compatible) {
      // §7.2「不硬迁」：unfit 版本不得挂载为机群分片——界面层拒绝，不调 API
      const reason = "该迁移版本被判定为机群不适配（unfit），按 §7.2「不硬迁」不可挂载：请为该设备独立建模或补充标定数据后重试";
      setMountError(reason);
      message.error(reason);
      return;
    }
    setBusy(true);
    setMountError(null);
    try {
      const payload: FleetShardCreatePayload = {
        model_version_id: result.version_id,
        condition_value: conditionValue.trim(),
        ...(conditionColumn ? { condition_column: conditionColumn } : {}),
        ...(rows != null && totalRows != null ? { rows, total_rows: totalRows } : {}),
      };
      setMounted(await addFleetShard(deploymentId, payload));
      message.success("迁移版本已挂载为部署分片");
    } catch (err) {
      setMountError(formatApiError(err, "挂载分片失败"));
    } finally {
      setBusy(false);
    }
  };

  if (!sourceVersionId) return null;
  const unfit = result ? (result.unfit_for_fleet || !result.fleet_fit?.compatible) : false;
  const fleetFpr = result?.fleet_fit?.fleet_fpr ?? null;

  return (
    <div
      data-testid="device-recalibrate-panel"
      style={{ border: "1px solid var(--v2-line, #eee)", borderRadius: 8, padding: "8px 12px" }}
    >
      <Space direction="vertical" size="small" style={{ width: "100%" }}>
        <Space style={{ width: "100%", justifyContent: "space-between" }}>
          <Text strong style={{ fontSize: 13 }}>M9 新设备重标定（纯正常数据 → fleet_fit 判定 → 迁移版本）</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>源版本 {sourceVersionId}</Text>
        </Space>
        <Space wrap size={8}>
          <Select
            aria-label="标定数据集"
            style={{ width: 220 }}
            size="small"
            placeholder="标定数据集"
            value={selectedArtifactId ?? undefined}
            options={artifactOptions}
            onChange={(value) => setArtifactId(String(value))}
          />
          <Input
            aria-label="工况值（设备号/工位号）"
            style={{ width: 200 }}
            size="small"
            maxLength={128}
            placeholder="工况值（设备号/工位号）"
            value={conditionValue}
            onChange={(event) => setConditionValue(event.target.value)}
          />
          <Text type="secondary" style={{ fontSize: 12 }}>工况列：{conditionColumn ?? "device_id（缺省）"}</Text>
          <Button size="small" type="primary" loading={busy} onClick={() => void runRecalibrate()}>
            执行 M9 设备重标定
          </Button>
        </Space>
        {error && <Alert type="warning" showIcon message={error} />}
        {result && (
          <Alert
            type={unfit ? "warning" : "success"}
            showIcon
            message={(
              <span>
                M9 设备重标定完成（工况值 {conditionValue.trim()}）：
                {unfit ? <Text strong>机群不适配（unfit）</Text> : <Text strong>机群兼容</Text>}
                （fleet_fpr {fleetFpr == null ? "—" : fleetFpr} / 容差 {result.fleet_fit?.tolerance ?? "—"}），
                迁移版本 <Text strong>{result.registered_model_name}</Text>（{result.version_id}），
                标定阈值 {result.threshold_score}，标定样本 {result.calibration_rows} 行
              </span>
            )}
            description={unfit
              ? "按 §7.2「不硬迁」：版本仍产出但标记 unfit_for_fleet，禁止挂载为机群分片；建议该设备独立建模或补充标定数据后重试。"
              : `迁移版本状态 pending，需先在模型库审批（approve）后再挂载；回测 AUC ${result.backtest?.synthetic_auc ?? "—"}、留出 ${result.backtest?.holdout_rows ?? "—"} 行`}
          />
        )}
        {result && (
          <Space wrap size={8}>
            <InputNumber
              aria-label="新分片行数"
              size="small" min={0} style={{ width: 130 }}
              placeholder="新分片行数" value={rows}
              onChange={(value) => setRows(typeof value === "number" ? value : null)}
            />
            <InputNumber
              aria-label="总分片行数"
              size="small" min={0} style={{ width: 130 }}
              placeholder="总分片行数" value={totalRows}
              onChange={(value) => setTotalRows(typeof value === "number" ? value : null)}
            />
            <Button
              size="small"
              danger={unfit}
              loading={busy}
              disabled={!deploymentId}
              onClick={() => void runMount()}
            >
              {unfit ? "挂载为部署分片（unfit 将被拒绝）" : "挂载为部署分片"}
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>填行数按比例分配权重（§6.3）</Text>
          </Space>
        )}
        {mountError && <Alert type="error" showIcon message={mountError} />}
        {mounted && (
          <Alert
            type="success"
            showIcon
            message={`已挂载为部署分片：revision r${mounted.revision_number}（共 ${mounted.targets.length} 个分片）`}
          />
        )}
      </Space>
    </div>
  );
}
