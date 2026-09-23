import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Badge, Button, Empty, List, Popover, Spin, Tag, Tooltip, Typography } from "antd";
import { BellOutlined, CheckOutlined, DeleteOutlined } from "@ant-design/icons";
import { notificationsApi, type InAppNotification } from "../api/securityNotifications";
import { useI18n } from "../i18n";

const severityColor: Record<InAppNotification["severity"], string> = {
  info: "blue",
  warning: "gold",
  critical: "red",
};

function formattedTime(value: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toLocaleString();
}

export default function NotificationCenter() {
  const { t } = useI18n();
  const copy = t.securityNotifications;
  const [open, setOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [items, setItems] = useState<InAppNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [workingId, setWorkingId] = useState<string | null>(null);
  const unreadRequest = useRef(false);
  const listRequest = useRef(false);
  const mutationRequest = useRef(false);
  const openRef = useRef(false);
  const generation = useRef(0);
  openRef.current = open;

  const refreshUnreadCount = useCallback(async () => {
    if (unreadRequest.current) return;
    unreadRequest.current = true;
    const request = generation.current;
    try {
      const count = await notificationsApi.getUnreadCount();
      if (request === generation.current) setUnreadCount(count);
    } catch {
      // A failed refresh must not report a false zero unread count.
    } finally {
      unreadRequest.current = false;
    }
  }, []);

  const loadNotifications = useCallback(async () => {
    if (listRequest.current || mutationRequest.current) return;
    const request = generation.current;
    listRequest.current = true;
    setLoading(true);
    setError(null);
    try {
      const result = await notificationsApi.listInAppNotifications();
      if (request === generation.current) setItems(result.items);
    } catch {
      if (request === generation.current) setError(copy.loadFailed);
    } finally {
      listRequest.current = false;
      if (request === generation.current) setLoading(false);
    }
  }, [copy.loadFailed]);

  useEffect(() => {
    void refreshUnreadCount();
    const refresh = () => {
      if (document.visibilityState === "hidden") return;
      void refreshUnreadCount();
      if (openRef.current) void loadNotifications();
    };
    const timer = window.setInterval(refresh, 30_000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      generation.current += 1;
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [loadNotifications, refreshUnreadCount]);

  const onOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (nextOpen) void loadNotifications();
  };

  const markRead = async (notificationId: string) => {
    if (listRequest.current || mutationRequest.current) return;
    mutationRequest.current = true;
    const request = generation.current;
    setWorkingId(notificationId);
    try {
      const result = await notificationsApi.markRead(notificationId);
      if (request !== generation.current) return;
      setItems((current) => current.map((item) => (
        item.id === notificationId ? { ...item, read_at: result.read_at } : item
      )));
      await refreshUnreadCount();
    } catch {
      if (request === generation.current) setError(copy.loadFailed);
    } finally {
      mutationRequest.current = false;
      if (request === generation.current) setWorkingId(null);
    }
  };

  const archive = async (notificationId: string) => {
    if (listRequest.current || mutationRequest.current) return;
    mutationRequest.current = true;
    const request = generation.current;
    setWorkingId(notificationId);
    try {
      await notificationsApi.archive(notificationId);
      if (request !== generation.current) return;
      setItems((current) => current.filter((item) => item.id !== notificationId));
      await refreshUnreadCount();
    } catch {
      if (request === generation.current) setError(copy.loadFailed);
    } finally {
      mutationRequest.current = false;
      if (request === generation.current) setWorkingId(null);
    }
  };

  const triggerLabel = useMemo(
    () => copy.notificationAriaLabel.replace("{count}", String(unreadCount)),
    [copy.notificationAriaLabel, unreadCount],
  );

  const content = (
    <div style={{ width: 360, maxWidth: "calc(100vw - 32px)" }}>
      <Typography.Text strong>{copy.notifications}</Typography.Text>
      <div style={{ marginTop: 12 }}>
        {loading ? <div style={{ textAlign: "center", padding: 20 }}><Spin aria-label={copy.loading} /></div> : null}
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {!loading && !error && items.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={copy.empty} /> : null}
        {items.length > 0 ? (
          <List
            size="small"
            dataSource={items}
            renderItem={(item) => (
              <List.Item
                actions={[
                  !item.read_at ? (
                    <Tooltip key="read" title={copy.markRead}>
                      <Button
                        aria-label={copy.markRead}
                        disabled={loading || workingId !== null}
                        type="text"
                        icon={<CheckOutlined />}
                        loading={workingId === item.id}
                        onClick={() => void markRead(item.id)}
                      />
                    </Tooltip>
                  ) : null,
                  <Tooltip key="archive" title={copy.archive}>
                    <Button
                      aria-label={copy.archive}
                      disabled={loading || workingId !== null}
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      loading={workingId === item.id}
                      onClick={() => void archive(item.id)}
                    />
                  </Tooltip>,
                ].filter(Boolean)}
              >
                <List.Item.Meta
                  title={<span>{!item.read_at ? <Tag color={severityColor[item.severity]}>{copy.unread}</Tag> : null}{item.title}</span>}
                  description={<div><div>{item.body}</div><Typography.Text type="secondary">{formattedTime(item.created_at)}</Typography.Text></div>}
                />
              </List.Item>
            )}
          />
        ) : null}
      </div>
    </div>
  );

  return (
    <Popover content={content} trigger="click" open={open} onOpenChange={onOpenChange}>
      <span style={{ display: "inline-flex", width: 32, height: 32 }}>
        <Badge count={unreadCount} overflowCount={99} offset={[-1, 2]}>
          <Tooltip title={copy.notifications}>
            <Button
              aria-label={triggerLabel}
              type="text"
              icon={<BellOutlined />}
              style={{ color: "var(--text-secondary)", width: 32, height: 32, padding: 0 }}
            />
          </Tooltip>
        </Badge>
      </span>
    </Popover>
  );
}
