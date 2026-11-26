/** 动作审计页（补齐路线第二批 S1，技术方案 §4.3/D15/D17）。
 *
 * 系统管理板块：LLM/Agent 调用明细（筛选 + 分页 + CSV 导出）与
 * 两张审计表的哈希链完整性校验卡（E10）。
 */
import { SafetyCertificateOutlined, DownloadOutlined } from "@ant-design/icons";
import { App as AntApp, Button, Card, Select, Table, Tag, Tooltip, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import apiClient from "../api/client";
import { apiErrorText } from "../api/qualityAlerts";
import { useI18n } from "../i18n";

interface ActionRow {
  id: string;
  created_at: string | null;
  agent_type: string;
  tool_name: string | null;
  status: "success" | "error" | "timeout";
  error_code: string | null;
  duration_ms: number | null;
  project_id: string | null;
  trace_id: string | null;
  idempotency_key: string | null;
  repeat_count: number;
  usage: Record<string, unknown> | null;
  model_profile: string | null;
  request_payload: Record<string, unknown> | null;
  response_payload: Record<string, unknown> | null;
}

interface ChainReport {
  [table: string]: {
    chained: number;
    unchained: number;
    complete: boolean;
    first_break: { seq: number; id: string; reason: string } | null;
  };
}

const STATUS_COLORS: Record<string, string> = {
  success: "green",
  error: "red",
  timeout: "orange",
};

export default function AgentActionAuditPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [rows, setRows] = useState<ActionRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [agentType, setAgentType] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [chain, setChain] = useState<ChainReport | null>(null);
  const [verifying, setVerifying] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    apiClient
      .get("/admin/agent-actions", {
        params: {
          agent_type: agentType,
          status,
          offset: (page - 1) * 20,
          limit: 20,
        },
      })
      .then((response) => {
        const body = response.data as { items: ActionRow[]; total: number };
        setRows(body.items || []);
        setTotal(body.total || 0);
      })
      .catch((error) => message.error(apiErrorText(error)))
      .finally(() => setLoading(false));
  }, [agentType, status, page, message]);

  useEffect(() => {
    load();
  }, [load]);

  const verifyChain = () => {
    setVerifying(true);
    apiClient
      .get("/admin/audit-chain/verify")
      .then((response) => setChain(response.data as ChainReport))
      .catch((error) => message.error(apiErrorText(error)))
      .finally(() => setVerifying(false));
  };

  const exportCsv = () => {
    const query = new URLSearchParams();
    if (agentType) query.set("agent_type", agentType);
    if (status) query.set("status", status);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    apiClient
      .get(`/admin/agent-actions/export.csv${suffix}`, { responseType: "blob" })
      .then((response) => {
        const url = URL.createObjectURL(response.data as Blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = "agent-action-audit.csv";
        anchor.click();
        URL.revokeObjectURL(url);
      })
      .catch((error) => message.error(apiErrorText(error)));
  };

  const columns = useMemo(
    () => [
      {
        title: zh ? "时间" : "Time",
        dataIndex: "created_at",
        render: (value: string | null) => (value ? value.replace("T", " ").slice(0, 19) : "-"),
      },
      { title: zh ? "智能体" : "Agent", dataIndex: "agent_type" },
      { title: zh ? "工具" : "Tool", dataIndex: "tool_name", render: (v: string | null) => v || "-" },
      {
        title: zh ? "状态" : "Status",
        dataIndex: "status",
        render: (value: string, row: ActionRow) => (
          <Tooltip title={row.error_code}>
            <Tag color={STATUS_COLORS[value] || "default"}>{value}</Tag>
          </Tooltip>
        ),
      },
      {
        title: zh ? "耗时" : "Duration",
        dataIndex: "duration_ms",
        render: (value: number | null) => (value === null ? "-" : `${value} ms`),
      },
      {
        title: zh ? "用量" : "Usage",
        dataIndex: "usage",
        render: (value: Record<string, unknown> | null) =>
          value && value.total_tokens !== undefined ? `${value.total_tokens} tok` : "-",
      },
      { title: zh ? "档案" : "Profile", dataIndex: "model_profile", render: (v: string | null) => v || "-" },
      {
        title: zh ? "重复" : "Repeats",
        dataIndex: "repeat_count",
        render: (value: number) => (value > 0 ? `×${value + 1}` : "-"),
      },
    ],
    [zh],
  );

  return (
    <div className="v2-legacy" data-testid="v2-agent-audit" style={{ padding: 16 }}>
      <h2 style={{ marginTop: 0 }}>{zh ? "动作审计" : "Agent action audit"}</h2>
      <Card size="small" style={{ marginBottom: 12 }} title={zh ? "审计链完整性校验（E10）" : "Audit chain verification"}>
        <Button
          icon={<SafetyCertificateOutlined />}
          loading={verifying}
          onClick={verifyChain}
          data-testid="verify-chain"
        >
          {zh ? "校验两表哈希链" : "Verify both chains"}
        </Button>
        {chain && (
          <div style={{ marginTop: 8 }} data-testid="chain-result">
            {Object.entries(chain).map(([table, report]) => (
              <div key={table}>
                <Tag color={report.complete ? "green" : "red"}>{table}</Tag>
                <span>
                  {zh ? "已入链" : "chained"}: {report.chained} · {zh ? "链前史" : "pre-chain"}: {report.unchained}
                  {report.first_break && (
                    <Tag color="red" style={{ marginLeft: 8 }}>
                      {zh ? "断点" : "break"}: seq={report.first_break.seq} ({report.first_break.reason})
                    </Tag>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <Select
          aria-label={zh ? "智能体类型" : "Agent type"}
          style={{ minWidth: 160 }}
          allowClear
          value={agentType}
          onChange={(value) => { setAgentType(value); setPage(1); }}
          placeholder={zh ? "智能体类型" : "Agent type"}
          options={["chat", "chat_tool", "agent_pipeline", "kg_extract", "audit_qa", "other"].map((value) => ({
            value, label: value,
          }))}
        />
        <Select
          aria-label={zh ? "成败" : "Status"}
          style={{ minWidth: 140 }}
          allowClear
          value={status}
          onChange={(value) => { setStatus(value); setPage(1); }}
          placeholder={zh ? "成败" : "Status"}
          options={["success", "error", "timeout"].map((value) => ({ value, label: value }))}
        />
        <Button icon={<DownloadOutlined />} onClick={exportCsv}>
          {zh ? "导出 CSV" : "Export CSV"}
        </Button>
        <Button onClick={load}>{zh ? "刷新" : "Refresh"}</Button>
      </div>
      <Table
        rowKey="id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={{ current: page, total, pageSize: 20, onChange: setPage }}
      />
    </div>
  );
}
