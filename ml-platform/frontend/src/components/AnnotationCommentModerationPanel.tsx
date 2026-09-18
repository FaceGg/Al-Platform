import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Input, List, Modal, Select, Space, Spin, Tag, Tooltip } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import {
  AnnotationComment,
  listAnnotationComments,
  updateAnnotationCommentStatus,
} from "../api/annotationComments";
import { formatApiError } from "../api/client";

export default function AnnotationCommentModerationPanel({
  taskId,
  open,
  onClose,
}: {
  taskId: string;
  open: boolean;
  onClose: () => void;
}) {
  const [items, setItems] = useState<AnnotationComment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState<string | null>(null);
  const [status, setStatus] = useState<"open" | "resolved" | undefined>();
  const [sampleId, setSampleId] = useState("");
  const [thread, setThread] = useState<"all" | "roots" | "replies">("all");
  const [cursor, setCursor] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const generation = useRef(0);
  const mutation = useRef(0);

  const load = useCallback(async (next?: string) => {
    const request = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const result = await listAnnotationComments(taskId, { status, sample_id: sampleId || undefined, thread, cursor: next });
      if (request !== generation.current) return;
      setItems((current) => next
        ? [...current, ...result.items.filter((item) => !current.some((existing) => existing.id === item.id))]
        : result.items);
      setCursor(result.next_cursor);
      setTotal(result.total);
    } catch (err) {
      if (request === generation.current) setError(formatApiError(err, "批注加载失败"));
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [taskId, status, sampleId, thread]);

  useEffect(() => {
    setItems([]);
    setCursor(null);
    setTotal(0);
    setSaving(null);
    if (open) void load();
    return () => { generation.current += 1; mutation.current += 1; };
  }, [open, load]);

  async function changeStatus(item: AnnotationComment) {
    setSaving(item.id);
    setError("");
    const request = generation.current;
    const operation = ++mutation.current;
    try {
      const updated = await updateAnnotationCommentStatus(
        item.id,
        item.status === "resolved" ? "open" : "resolved",
      );
      if (request !== generation.current) return;
      if (status && updated.status !== status) {
        // A status filter may remove the cursor row; restart from the first page.
        await load();
      } else {
        setItems((current) => current.map((candidate) => candidate.id === updated.id ? { ...candidate, ...updated } : candidate));
      }
    } catch (err) {
      if (request === generation.current) setError(formatApiError(err, "批注状态更新失败"));
    } finally {
      if (operation === mutation.current) setSaving(null);
    }
  }

  return (
    <Modal title="批注管理" open={open} onCancel={onClose} footer={null} width={720}>
      <Space wrap style={{ marginBottom: 12 }}>
        <Select<"all" | "open" | "resolved">
          aria-label="批注状态"
          value={status ?? "all"}
          disabled={saving !== null}
          onChange={(value) => setStatus(value === "all" ? undefined : value)}
          options={[{ value: "all", label: "全部状态" }, { value: "open", label: "待处理" }, { value: "resolved", label: "已解决" }]}
          style={{ width: 130 }}
        />
        <Input.Search placeholder="样本 ID" allowClear onSearch={(value) => setSampleId(value.trim())} disabled={saving !== null} />
        <Select<"all" | "roots" | "replies">
          aria-label="批注线程"
          value={thread}
          disabled={saving !== null}
          onChange={setThread}
          options={[
            { value: "all", label: "全部线程" },
            { value: "roots", label: "仅主批注" },
            { value: "replies", label: "仅回复" },
          ]}
          style={{ width: 130 }}
        />
        <Tooltip title="刷新批注">
          <Button aria-label="刷新批注" icon={<ReloadOutlined />} disabled={loading || saving !== null} onClick={() => { void load(); }} />
        </Tooltip>
        <span>共 {total} 条</span>
      </Space>
      {error && <Alert type="error" showIcon message={error} />}
      {loading && items.length === 0 ? <Spin /> : (
        <List
          locale={{ emptyText: "暂无批注" }}
          dataSource={items}
          renderItem={(item) => (
            <List.Item
              actions={[
                <button
                  type="button"
                  className="ant-btn ant-btn-sm"
                  key="status"
                  disabled={saving !== null || loading}
                  onClick={() => { void changeStatus(item); }}
                >
                  {item.status === "resolved" ? "重新打开" : "标记已解决"}
                </button>,
              ]}
            >
              <List.Item.Meta
                title={<span>{item.sample_id ? `样本 ${item.sample_id}` : "任务批注"} <Tag color={item.status === "resolved" ? "success" : "warning"}>{item.status === "resolved" ? "已解决" : "待处理"}</Tag></span>}
                description={<>{item.content}{item.parent_id ? <span className="muted"> · 回复</span> : null}</>}
              />
            </List.Item>
          )}
        />
      )}
      {cursor && <Button loading={loading} disabled={saving !== null} onClick={() => { void load(cursor); }}>加载更多</Button>}
    </Modal>
  );
}
