/** 统一四眼审批中心（补齐路线第二批 S1，技术方案 §4.2）。
 *
 * 顶栏全局入口的落地页（帮助按钮旁）：统一队列（批准/驳回/撤销，四眼约束
 * 由后端强制、行内按 can_approve 渲染操作）+ 存量审批（四处存量审批的
 * 只读投影，C4/D10）。无侧栏的独立页框（同帮助中心形制）。
 */
import { ArrowLeftOutlined, CheckOutlined, CloseOutlined } from "@ant-design/icons";
import { useLocation, useNavigate } from "react-router-dom";
import { App as AntApp, Badge, Button, Input, Modal, Select, Table, Tabs, Tag, Tooltip, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApprovalItem,
  ApprovalStatus,
  ApprovalType,
  LegacyApprovalItem,
  approveApproval,
  cancelApproval,
  fetchPendingApprovalCount,
  listApprovals,
  listLegacyApprovals,
  rejectApproval,
} from "../api/approvals";
import { apiErrorText } from "../api/qualityAlerts";
import { useI18n } from "../i18n";

const TYPE_LABELS: Record<ApprovalType, { zh: string; en: string }> = {
  disposition: { zh: "异常处置", en: "Disposition" },
  retrain_proposal: { zh: "发起重训", en: "Retrain proposal" },
  model_release: { zh: "模型发布", en: "Model release" },
  recipe_change: { zh: "工艺配方变更", en: "Recipe change" },
  exemption: { zh: "发布豁免", en: "Release exemption" },
};

const STATUS_COLORS: Record<string, string> = {
  pending: "gold",
  approved: "green",
  rejected: "red",
  expired: "default",
  invalidated: "volcano",
  cancelled: "default",
};

function statusLabel(status: string, zh: boolean): string {
  const labels: Record<string, [string, string]> = {
    pending: ["待审批", "Pending"],
    approved: ["已批准", "Approved"],
    rejected: ["已拒绝", "Rejected"],
    expired: ["已过期", "Expired"],
    invalidated: ["已失效", "Invalidated"],
    cancelled: ["已撤销", "Cancelled"],
  };
  const pair = labels[status] || [status, status];
  return zh ? pair[0] : pair[1];
}

function typeLabel(type: string, zh: boolean): string {
  const known = TYPE_LABELS[type as ApprovalType];
  if (known) return zh ? known.zh : known.en;
  return type;
}

const SOURCE_LABELS: Record<string, [string, string]> = {
  agent_task_review: ["任务审查（存量）", "Agent task review"],
  model_version: ["模型版本（存量）", "Model version"],
  model_card: ["模型卡（存量）", "Model card"],
  skill_revision: ["技能修订（存量）", "Skill revision"],
};

function remainingText(expiresAt: string | null, zh: boolean): string {
  if (!expiresAt) return "-";
  const remaining = new Date(expiresAt.replace("Z", "+00:00")).getTime() - Date.now();
  if (remaining <= 0) return zh ? "已到期" : "expired";
  const hours = Math.floor(remaining / 3600000);
  if (hours >= 24) return `${Math.floor(hours / 24)}d ${hours % 24}h`;
  return `${hours}h`;
}

export default function ApprovalCenterPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const navigate = useNavigate();
  const location = useLocation();
  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [items, setItems] = useState<ApprovalItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<ApprovalStatus | undefined>(undefined);
  const [typeFilter, setTypeFilter] = useState<ApprovalType | undefined>(undefined);
  const [legacy, setLegacy] = useState<LegacyApprovalItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<ApprovalItem | null>(null);
  const [rejectNote, setRejectNote] = useState("");

  useEffect(() => {
    apiClientGetProjects().then((rows) => {
      setProjects(rows);
      if (rows.length > 0) setProjectId((current) => current || rows[0].id);
    });
  }, []);

  const load = useCallback(() => {
    if (!projectId) return;
    setLoading(true);
    listApprovals(projectId, {
      status: statusFilter,
      type: typeFilter,
      offset: (page - 1) * 20,
      limit: 20,
    })
      .then((result) => {
        setItems(result.items);
        setTotal(result.total);
      })
      .catch((error) => message.error(apiErrorText(error)))
      .finally(() => setLoading(false));
  }, [projectId, statusFilter, typeFilter, page, message]);

  useEffect(() => {
    load();
  }, [load]);

  const loadLegacy = useCallback(() => {
    if (!projectId) return;
    listLegacyApprovals(projectId)
      .then((result) => setLegacy(result.items))
      .catch(() => setLegacy([]));
  }, [projectId]);

  const refreshCounts = useCallback(() => {
    fetchPendingApprovalCount().catch(() => undefined);
  }, []);

  const onApprove = (row: ApprovalItem) => {
    approveApproval(row.project_id, row.id)
      .then(() => {
        message.success(zh ? "已批准" : "Approved");
        load();
        loadLegacy();
      })
      .catch((error) => message.error(apiErrorText(error)));
  };

  const onReject = () => {
    if (!rejectTarget) return;
    if (!rejectNote.trim()) {
      message.warning(zh ? "拒绝必须附意见" : "Rejection note is required");
      return;
    }
    rejectApproval(rejectTarget.project_id, rejectTarget.id, rejectNote.trim())
      .then(() => {
        message.success(zh ? "已拒绝" : "Rejected");
        setRejectTarget(null);
        setRejectNote("");
        load();
        loadLegacy();
      })
      .catch((error) => message.error(apiErrorText(error)));
  };

  const onCancel = (row: ApprovalItem) => {
    cancelApproval(row.project_id, row.id)
      .then(() => {
        message.success(zh ? "已撤销" : "Cancelled");
        load();
      })
      .catch((error) => message.error(apiErrorText(error)));
  };

  const columns = useMemo(
    () => [
      {
        title: zh ? "类型" : "Type",
        dataIndex: "type",
        render: (value: string) => typeLabel(value, zh),
      },
      { title: zh ? "标题" : "Title", dataIndex: "title", ellipsis: true },
      { title: zh ? "状态" : "Status", dataIndex: "status", render: (value: string) => (
        <Tag color={STATUS_COLORS[value] || "default"}>{statusLabel(value, zh)}</Tag>
      ) },
      {
        title: zh ? "剩余有效期" : "Expires in",
        dataIndex: "expires_at",
        render: (value: string, row: ApprovalItem) =>
          row.status === "pending" ? remainingText(value, zh) : "-",
      },
      {
        title: zh ? "执行" : "Execution",
        dataIndex: "execution_status",
        render: (value: string, row: ApprovalItem) => {
          if (row.status !== "approved") return "-";
          if (value === "succeeded") return zh ? "已执行" : "done";
          if (value === "failed") {
            return (
              <Tooltip title={row.execution_error}>
                <Tag color="red">{zh ? "执行失败" : "failed"}</Tag>
              </Tooltip>
            );
          }
          return zh ? "待执行" : "pending";
        },
      },
      {
        title: zh ? "操作" : "Actions",
        render: (_: unknown, row: ApprovalItem) => {
          if (row.status !== "pending") return "-";
          if (!row.can_approve) {
            return (
              <Button size="small" onClick={() => onCancel(row)}>
                {zh ? "撤销" : "Cancel"}
              </Button>
            );
          }
          return (
            <span>
              <Button
                size="small"
                type="primary"
                icon={<CheckOutlined />}
                data-testid={`approve-${row.id}`}
                onClick={() => onApprove(row)}
              >
                {zh ? "批准" : "Approve"}
              </Button>
              <Button
                size="small"
                danger
                icon={<CloseOutlined />}
                data-testid={`reject-${row.id}`}
                style={{ marginLeft: 8 }}
                onClick={() => setRejectTarget(row)}
              >
                {zh ? "驳回" : "Reject"}
              </Button>
            </span>
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [zh],
  );

  const legacyColumns = useMemo(
    () => [
      {
        title: zh ? "来源" : "Source",
        dataIndex: "source",
        render: (value: string) => (SOURCE_LABELS[value] ? (zh ? SOURCE_LABELS[value][0] : SOURCE_LABELS[value][1]) : value),
      },
      { title: zh ? "标题" : "Title", dataIndex: "title", ellipsis: true },
      { title: zh ? "原始状态" : "Raw status", dataIndex: "raw_status" },
      {
        title: zh ? "归一状态" : "Mapped",
        dataIndex: "status",
        render: (value: string) => <Tag>{statusLabel(value, zh) === value && !zh ? value : statusLabel(value, zh)}</Tag>,
      },
      {
        title: zh ? "跳转" : "Open",
        dataIndex: "link",
        render: (value: string) => (
          <Button size="small" type="link" onClick={() => navigate(value)}>
            {zh ? "查看" : "Open"}
          </Button>
        ),
      },
      {
        title: zh ? "备注" : "Note",
        dataIndex: "note",
        render: (value: string | null) => value || "-",
      },
    ],
    [zh, navigate],
  );

  return (
    <div className="v2-legacy" data-testid="v2-approval-center" style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <Button
          type="text"
          icon={<ArrowLeftOutlined />}
          aria-label={zh ? "返回" : "Back"}
          onClick={() => navigate(-1)}
        />
        <h2 style={{ margin: 0 }}>{zh ? "审批中心" : "Approval Center"}</h2>
        <span style={{ color: "#888", fontSize: 12 }}>
          {zh
            ? "四眼原则：审批人与发起人必须不同；72h 未处理自动过期回收"
            : "Four-eyes: approver must differ from initiator; pending expires in 72h"}
        </span>
      </div>
      <Tabs
        defaultActiveKey={location.state?.tab === "legacy" ? "legacy" : "queue"}
        onChange={(key) => { if (key === "legacy") loadLegacy(); }}
        items={[
          {
            key: "queue",
            label: zh ? "统一队列" : "Queue",
            children: (
              <>
                <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                  <Select
                    aria-label={zh ? "项目" : "Project"}
                    style={{ minWidth: 200 }}
                    value={projectId || undefined}
                    onChange={(value) => { setProjectId(value); setPage(1); }}
                    options={projects.map((row) => ({ value: row.id, label: row.name }))}
                    placeholder={zh ? "选择项目" : "Project"}
                  />
                  <Select
                    aria-label={zh ? "状态筛选" : "Status"}
                    style={{ minWidth: 140 }}
                    allowClear
                    value={statusFilter}
                    onChange={(value) => { setStatusFilter(value); setPage(1); }}
                    placeholder={zh ? "状态" : "Status"}
                    options={(["pending", "approved", "rejected", "expired", "invalidated", "cancelled"] as ApprovalStatus[]).map(
                      (value) => ({ value, label: statusLabel(value, zh) }),
                    )}
                  />
                  <Select
                    aria-label={zh ? "类型筛选" : "Type"}
                    style={{ minWidth: 160 }}
                    allowClear
                    value={typeFilter}
                    onChange={(value) => { setTypeFilter(value); setPage(1); }}
                    placeholder={zh ? "类型" : "Type"}
                    options={(Object.keys(TYPE_LABELS) as ApprovalType[]).map((value) => ({
                      value,
                      label: typeLabel(value, zh),
                    }))}
                  />
                  <Button onClick={() => { load(); loadLegacy(); }}>
                    {zh ? "刷新" : "Refresh"}
                  </Button>
                </div>
                <Table
                  rowKey="id"
                  size="small"
                  loading={loading}
                  columns={columns}
                  dataSource={items}
                  pagination={{ current: page, total, pageSize: 20, onChange: setPage }}
                />
              </>
            ),
          },
          {
            key: "legacy",
            label: zh ? "存量审批" : "Legacy approvals",
            children: (
              <Table
                rowKey={(row: LegacyApprovalItem) => `${row.source}-${row.ref_id}`}
                size="small"
                columns={legacyColumns}
                dataSource={legacy}
                pagination={{ pageSize: 20 }}
              />
            ),
          },
        ]}
      />
      <Modal
        open={rejectTarget !== null}
        title={zh ? "驳回审批" : "Reject approval"}
        okText={zh ? "驳回" : "Reject"}
        cancelText={zh ? "取消" : "Cancel"}
        onOk={onReject}
        onCancel={() => { setRejectTarget(null); setRejectNote(""); }}
      >
        <div style={{ marginBottom: 8 }}>
          {zh ? "驳回意见（必填）" : "Rejection note (required)"}
        </div>
        <Input.TextArea
          aria-label={zh ? "驳回意见" : "Rejection note"}
          rows={3}
          value={rejectNote}
          onChange={(event) => setRejectNote(event.target.value)}
        />
      </Modal>
    </div>
  );
}

async function apiClientGetProjects(): Promise<Array<{ id: string; name: string }>> {
  const response = await import("../api/client").then((mod) => mod.default.get("/projects"));
  const rows = (response.data ?? {}) as { items?: Array<{ id: string; name: string }>; projects?: Array<{ id: string; name: string }> };
  return rows.items || rows.projects || [];
}