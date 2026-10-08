import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Button, Drawer, Progress, Space, Table, Tag, Typography } from "antd";
import { FileTextOutlined, ReloadOutlined, StopOutlined, SyncOutlined } from "@ant-design/icons";
import { App as AntApp } from "antd";
import { formatApiError } from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";
import {
  cancelJobRun,
  getJobRunLogs,
  JobRun,
  JobStatus,
  listJobRuns,
  reconcileJobRun,
} from "../api/kubernetesJobs";

const STATUS_COLORS: Record<JobStatus, string> = {
  queued: "default",
  submitted: "processing",
  running: "processing",
  succeeded: "success",
  failed: "error",
  cancelled: "warning",
  timed_out: "warning",
  orphaned: "error",
};

const TERMINAL_STATUSES: JobStatus[] = ["succeeded", "failed", "cancelled", "timed_out", "orphaned"];

export default function JobRunsPage() {
  const { t } = useI18n();
  const { message } = AntApp.useApp();
  const jt = (key: string, fallback: string) =>
    (t as unknown as Record<string, Record<string, string>>)?.jobRuns?.[key] ?? fallback;

  const [jobs, setJobs] = useState<JobRun[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [logTarget, setLogTarget] = useState<JobRun | null>(null);
  const [logText, setLogText] = useState("");
  const [logCursor, setLogCursor] = useState(0);
  const [logEnd, setLogEnd] = useState(false);
  const [logLoading, setLogLoading] = useState(false);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listJobRuns();
      setJobs(data.items);
      setTotal(data.total);
    } catch (error) {
      message.error(formatApiError(error, jt("loadFailed", "加载失败")));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  const openLogs = async (job: JobRun) => {
    setLogTarget(job);
    setLogText("");
    setLogCursor(0);
    setLogEnd(false);
    setLogLoading(true);
    try {
      const page = await getJobRunLogs(job.id, 0);
      setLogText(page.text);
      setLogCursor(page.next_cursor);
      setLogEnd(page.end_of_stream);
    } catch (error) {
      message.error(formatApiError(error, jt("logFailed", "日志加载失败")));
    } finally {
      setLogLoading(false);
    }
  };

  const loadMoreLogs = async () => {
    if (!logTarget) return;
    setLogLoading(true);
    try {
      const page = await getJobRunLogs(logTarget.id, logCursor);
      setLogText((current) => current + page.text);
      setLogCursor(page.next_cursor);
      setLogEnd(page.end_of_stream);
    } catch (error) {
      message.error(formatApiError(error, jt("logFailed", "日志加载失败")));
    } finally {
      setLogLoading(false);
    }
  };

  const handleCancel = async (job: JobRun) => {
    setCancellingId(job.id);
    try {
      await cancelJobRun(job.id, jt("cancelReason", "user cancelled from console"));
      message.success(jt("cancelOk", "已请求取消"));
      await loadJobs();
    } catch (error) {
      message.error(formatApiError(error, jt("cancelFailed", "取消失败")));
    } finally {
      setCancellingId(null);
    }
  };

  const handleReconcile = async (job: JobRun) => {
    try {
      await reconcileJobRun(job.id);
      message.success(jt("reconcileOk", "对账完成"));
      await loadJobs();
    } catch (error) {
      message.error(formatApiError(error, jt("reconcileFailed", "对账失败")));
    }
  };

  const statusHint = (job: JobRun): string | null => {
    if (job.error_code === "KUBE_JOB_TIMEOUT" || job.status === "timed_out") {
      return jt("timeoutHint", "作业超过 activeDeadline 期限,已按超时终态收口。");
    }
    if (job.error_code === "KUBE_JOB_ORPHANED" || job.status === "orphaned") {
      return jt("orphanedHint", "集群内找不到对应 Job 资源,作业按 orphaned 终态收口。");
    }
    return null;
  };

  const columns = [
    { title: jt("jobName", "作业名"), dataIndex: "job_name", key: "job_name" },
    {
      title: jt("status", "状态"),
      dataIndex: "status",
      key: "status",
      render: (_: unknown, job: JobRun) => {
        const hint = statusHint(job);
        return (
          <Space direction="vertical" size={0}>
            <Tag color={STATUS_COLORS[job.status] ?? "default"}>{job.status}</Tag>
            {hint ? (
              <Typography.Text type="secondary" data-testid={`hint-${job.id}`} style={{ fontSize: 12 }}>
                {hint}
              </Typography.Text>
            ) : null}
          </Space>
        );
      },
    },
    {
      title: jt("progress", "执行进度"),
      key: "progress",
      render: (_: unknown, job: JobRun) => (
        <Space direction="vertical" size={0} style={{ minWidth: 120 }}>
          <span>{job.operation_state ?? "-"}</span>
          <Progress percent={job.operation_progress ?? 0} size="small" />
        </Space>
      ),
    },
    { title: jt("image", "镜像"), dataIndex: "image_ref", key: "image_ref", ellipsis: true },
    { title: jt("namespace", "命名空间"), dataIndex: "namespace", key: "namespace" },
    { title: jt("revision", "代次"), dataIndex: "revision", key: "revision" },
    { title: jt("timeout", "超时(秒)"), dataIndex: "timeout_seconds", key: "timeout_seconds" },
    {
      title: jt("actions", "操作"),
      key: "actions",
      render: (_: unknown, job: JobRun) => {
        const terminal = TERMINAL_STATUSES.includes(job.status);
        return (
          <Space>
            <Button size="small" icon={<FileTextOutlined />} onClick={() => openLogs(job)}>
              {jt("logs", "日志")}
            </Button>
            <TooltipedHint text={terminal ? jt("cancelDisabled", "终态作业不可取消") : null}>
              <Button
                size="small"
                danger
                icon={<StopOutlined />}
                disabled={terminal}
                loading={cancellingId === job.id}
                onClick={() => handleCancel(job)}
              >
                {jt("cancel", "取消")}
              </Button>
            </TooltipedHint>
            <Button size="small" icon={<SyncOutlined />} onClick={() => handleReconcile(job)}>
              {jt("reconcile", "对账")}
            </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <AppLayout>
      <div style={{ padding: 24 }}>
        <Space style={{ marginBottom: 16 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {jt("title", "作业运行")}
          </Typography.Title>
          <Button icon={<ReloadOutlined />} onClick={loadJobs}>
            {jt("refresh", "刷新")}
          </Button>
        </Space>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns as never}
          dataSource={jobs}
          locale={{ emptyText: jt("empty", "暂无作业") }}
          pagination={{ total, pageSize: 50, showSizeChanger: false }}
        />
        <Drawer
          title={`${jt("logTitle", "作业日志")} · ${logTarget?.job_name ?? ""}`}
          open={logTarget !== null}
          width={720}
          onClose={() => setLogTarget(null)}
          footer={
            <Space>
              <Button loading={logLoading} disabled={logEnd} onClick={loadMoreLogs}>
                {jt("loadMore", "加载更多")}
              </Button>
              {logEnd ? (
                <Typography.Text type="secondary" data-testid="end-of-stream">
                  {jt("endOfStream", "已到日志末尾")}
                </Typography.Text>
              ) : null}
            </Space>
          }
        >
          <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-all", fontSize: 12 }}>{logText}</pre>
        </Drawer>
      </div>
    </AppLayout>
  );
}

function TooltipedHint({ text, children }: { text: string | null; children: ReactNode }) {
  if (!text) return <>{children}</>;
  return (
    <span title={text} data-testid="cancel-disabled-hint">
      {children}
    </span>
  );
}
