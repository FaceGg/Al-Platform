import { useCallback, useEffect, useMemo, useState } from "react";
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

  const refreshUnreadCount = useCallback(async () => {
    try {
      setUnreadCount(await notificationsApi.getUnreadCount());
    } catch {
      setUnreadCount(0);
    }
  }, []);

  const loadNotifications = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await notificationsApi.listInAppNotifications();
      setItems(result.items);
    } catch {
      setError(copy.loadFailed);
    } finally {
      setLoading(false);
    }
  }, [copy.loadFailed]);

  useEffect(() => {
    void refreshUnreadCount();
  }, [refreshUnreadCount]);

  const onOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (nextOpen) void loadNotifications();
  };

  const markRead = async (notificationId: string) => {
    setWorkingId(notificationId);
    try {
      const result = await notificationsApi.markRead(notificationId);
      setItems((current) => current.map((item) => (
        item.id === notificationId ? { ...item, read_at: result.read_at } : item
      )));
      await refreshUnreadCount();
    } catch {
      setError(copy.loadFailed);
    } finally {
      setWorkingId(null);
    }
  };

  const archive = async (notificationId: string) => {
    setWorkingId(notificationId);
    try {
      await notificationsApi.archive(notificationId);
      setItems((current) => current.filter((item) => item.id !== notificationId));
      await refreshUnreadCount();
    } catch {
      setError(copy.loadFailed);
    } finally {
      setWorkingId(null);
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
        {!loading && !error && items.length > 0 ? (
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
