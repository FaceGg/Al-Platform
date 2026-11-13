import { useEffect, useState } from "react";
import { Alert, Table, Tag, Typography } from "antd";
import { fetchFleetOverview, type FleetOverview } from "../../api/modelRegistry";

const { Text } = Typography;

/**
 * 机群分片概览面板（技术方案 §7 三-3，三期 M10）：部署面 per-device
 * 监控——每分片路由工况值/标定阈值/机群兼容性/回测 AUC + PSI 分片明细。
 * 数据来自 /inference-deployments/{id}/fleet-overview；分片为空或加载失败
 * 时静默不渲染（普通部署无此面板）。
 */
export default function FleetShardPanel({ deploymentId }: { deploymentId: string | null }) {
  const [overview, setOverview] = useState<FleetOverview | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!deploymentId) {
      return;
    }
    let cancelled = false;
    fetchFleetOverview(deploymentId)
      .then((data) => {
        if (!cancelled) {
          setOverview(data);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [deploymentId]);

  if (failed) {
    return null;
  }
  // 普通部署（非工况分片）没有 condition_column → 静默不渲染（本面板只对
  // 机群/工况分片部署有意义；此前仅按 shards.length 判空导致普通部署也出面板）。
  if (!overview || !overview.shards.length || !overview.condition_column) {
    return null;
  }
  const psiByValue = new Map(
    (overview.psi_per_shard ?? []).map((item) => [item.condition_value ?? "", item]),
  );
  return (
    <Alert
      type="info"
      showIcon
      message={(
        <span>
          机群分片概览（工况列 <Text strong>{overview.condition_column ?? "—"}</Text>
          ，revision r{overview.revision_number ?? "—"}，{overview.shards.length} 分片）
        </span>
      )}
      description={(
        <Table
          size="small"
          pagination={false}
          rowKey={(item) => item.model_version_id}
          dataSource={overview.shards}
          columns={[
            {
              title: "工况值",
              dataIndex: "condition_value",
              render: (value: string | null) => value ?? "（通配）",
            },
            { title: "版本", dataIndex: "version_number", width: 64 },
            {
              title: "标定阈值",
              dataIndex: "threshold_score",
              render: (value: number | null) => (value === null ? "—" : Number(value.toFixed(4))),
              width: 96,
            },
            {
              title: "机群兼容",
              dataIndex: "fleet_compatible",
              width: 96,
              render: (compatible: boolean | null) =>
                compatible === null || compatible === undefined
                  ? <Tag>—</Tag>
                  : compatible
                    ? <Tag color="green">兼容</Tag>
                    : <Tag color="orange">不适配（勿挂载）</Tag>,
            },
            {
              title: "回测 AUC",
              key: "backtest",
              width: 88,
              render: (_value, record) => {
                const auc = record.backtest?.synthetic_auc;
                return auc === undefined || auc === null ? "—" : Number(Number(auc).toFixed(4));
              },
            },
            {
              // per-device 运行期报警率（M10 per-device fpr 侧）：无标签下以该
              // 设备回流数据的模型报警率为 fpr proxy，与部署级 alert_comparison 同口径。
              title: "运行期报警率",
              key: "running",
              width: 120,
              render: (_value, record) => {
                const running = record.running;
                if (!running || running.rows === 0 || running.alert_rate === null || running.alert_rate === undefined) {
                  return "—";
                }
                const rate = Number(running.alert_rate);
                return (
                  <Tag color={rate > 0.015 ? "orange" : "green"}>
                    {(rate * 100).toFixed(2)}%
                  </Tag>
                );
              },
            },
            {
              title: "PSI（分片）",
              key: "psi",
              width: 120,
              render: (_value, record) => {
                const psi = psiByValue.get(record.condition_value ?? "");
                if (!psi) {
                  return "—";
                }
                return (
                  <Tag color={psi.level === "alert" ? "orange" : psi.level === "watch" ? "gold" : "green"}>
                    {psi.psi}
                  </Tag>
                );
              },
            },
          ]}
        />
      )}
      style={{ marginBottom: 12 }}
    />
  );
}
