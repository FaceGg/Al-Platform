import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, SendOutlined } from "@ant-design/icons";
import {
  notificationsApi,
  type NotificationEndpoint,
  type NotificationEndpointInput,
  type NotificationEndpointKind,
  type NotificationSeverity,
  type NotificationSubscription,
  type NotificationSubscriptionInput,
  type ProjectAuditEvent,
  type ProjectMember,
  type ProjectNotificationRecipient,
  type ProjectRole,
} from "../api/securityNotifications";
import { useI18n } from "../i18n";

interface ProjectGovernanceTabsProps {
  projectId: string;
  projectRole?: ProjectRole | null;
  isPlatformAdmin?: boolean;
}

interface EndpointFormValues {
  name: string;
  kind?: NotificationEndpointKind;
  recipient_user_ids?: string[];
  to?: string;
  cc?: string;
  url?: string;
  headers?: string;
  signature_mode?: "none" | "hmac-sha256";
  signing_secret?: string;
}

interface SubscriptionFormValues {
  endpoint_id: string;
  event_types: string;
  minimum_severity: NotificationSeverity;
  recipient_roles: ProjectRole[];
  recipient_user_ids?: string[];
  enabled: boolean;
}

const PAGE_SIZE = 50;

function commaSeparated(value: string | undefined): string[] {
  return (value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function localTime(value: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toLocaleString();
}

function endpointPayload(values: EndpointFormValues): NotificationEndpointInput {
  const kind = values.kind || "webhook";
  let config: Record<string, unknown>;
  if (kind === "in_app") {
    config = { recipient_user_ids: values.recipient_user_ids || [] };
  } else if (kind === "email") {
    config = { to: commaSeparated(values.to), cc: commaSeparated(values.cc) };
  } else if (values.kind === "wecom") {
    config = { url: values.url || "" };
  } else {
    let headers: Record<string, string> = {};
    if (values.headers?.trim()) {
      let parsed: unknown;
      try {
        parsed = JSON.parse(values.headers);
      } catch {
        throw new Error("headers");
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("headers");
      headers = Object.fromEntries(
        Object.entries(parsed as Record<string, unknown>).map(([key, value]) => [key, String(value)]),
      );
    }
    config = {
      url: values.url || "",
      headers,
      signature_mode: values.signature_mode || "none",
      ...(values.signature_mode === "hmac-sha256" ? { signing_secret: values.signing_secret || "" } : {}),
    };
  }
  return { kind, name: values.name.trim(), config };
}

function stateLabel(labels: Record<string, string>, value: string): string {
  return labels[value] || value;
}

function OwnerOnly({ message: text }: { message: string }) {
  return <Alert type="info" showIcon message={text} />;
}

function MembersPanel({ projectId, isOwner }: { projectId: string; isOwner: boolean }) {
  const { t } = useI18n();
  const copy = t.projectGovernance;
  const [items, setItems] = useState<ProjectMember[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!isOwner) return;
    let active = true;
    setLoading(true);
    setError(false);
    void notificationsApi.listProjectMembers(projectId)
      .then((result) => { if (active) setItems(result.items); })
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [isOwner, projectId]);

  if (!isOwner) return <OwnerOnly message={copy.ownerOnly} />;
  if (loading) return <div style={{ textAlign: "center", padding: 20 }}><Spin aria-label={copy.loading} /></div>;
  if (error) return <Alert type="error" showIcon message={copy.loadFailed} />;
  if (items.length === 0) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={copy.noMembers} />;

  return <Table<ProjectMember>
    rowKey="user_id"
    size="small"
    pagination={false}
    dataSource={items}
    columns={[
      { title: copy.username, dataIndex: "username" },
      { title: copy.role, dataIndex: "role", render: (role: ProjectRole) => <Tag>{t.modelRegistry[role]}</Tag> },
      { title: copy.createdAt, dataIndex: "created_at", render: (value: string | null) => localTime(value) },
    ]}
  />;
}

function AuditPanel({ projectId, isOwner }: { projectId: string; isOwner: boolean }) {
  const { t } = useI18n();
  const copy = t.projectGovernance;
  const [items, setItems] = useState<ProjectAuditEvent[]>([]);
  const [page, setPage] = useState({ total: 0, offset: 0, limit: PAGE_SIZE });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const loadPage = useCallback(async (offset = 0, limit = PAGE_SIZE) => {
    if (!isOwner) return;
    setLoading(true);
    setError(false);
    try {
      const result = await notificationsApi.listProjectAuditEvents(projectId, { offset, limit });
      setItems(result.items);
      setPage({
        total: result.total,
        offset: result.offset ?? offset,
        limit: result.limit ?? limit,
      });
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [isOwner, projectId]);

  useEffect(() => {
    void loadPage();
  }, [loadPage]);

  if (!isOwner) return <OwnerOnly message={copy.ownerOnly} />;
  if (loading) return <div style={{ textAlign: "center", padding: 20 }}><Spin aria-label={copy.loading} /></div>;
  if (error) return <Alert type="error" showIcon message={copy.loadFailed} />;
  if (items.length === 0) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={copy.noAuditEvents} />;

  return <Table<ProjectAuditEvent>
    rowKey="id"
    size="small"
    pagination={{
      current: Math.floor(page.offset / page.limit) + 1,
      pageSize: page.limit,
      total: page.total,
      showSizeChanger: false,
      onChange: (nextPage, pageSize) => void loadPage((nextPage - 1) * pageSize, pageSize),
    }}
    dataSource={items}
    columns={[
      { title: copy.action, dataIndex: "action" },
      { title: copy.actor, dataIndex: "actor_username" },
      { title: copy.resource, dataIndex: "resource_type" },
      {
        title: copy.result,
        dataIndex: "result",
        render: (result: string) => <Tag color={result === "success" ? "green" : result === "denied" ? "gold" : "red"}>
          {stateLabel(copy.auditResultLabels as Record<string, string>, result)}
        </Tag>,
      },
      { title: copy.createdAt, dataIndex: "created_at", render: (value: string | null) => localTime(value) },
    ]}
  />;
}

function NotificationSettingsPanel({
  projectId,
  canManage,
  isPlatformAdmin,
}: {
  projectId: string;
  canManage: boolean;
  isPlatformAdmin: boolean;
}) {
  const { t } = useI18n();
  const copy = t.securityNotifications;
  const [endpoints, setEndpoints] = useState<NotificationEndpoint[]>([]);
  const [subscriptions, setSubscriptions] = useState<NotificationSubscription[]>([]);
  const [deliveries, setDeliveries] = useState<Awaited<ReturnType<typeof notificationsApi.listNotificationDeliveries>>["items"]>([]);
  const [deliveryPage, setDeliveryPage] = useState({ total: 0, offset: 0, limit: PAGE_SIZE });
  const [recipients, setRecipients] = useState<ProjectNotificationRecipient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [endpointModalOpen, setEndpointModalOpen] = useState(false);
  const [subscriptionModalOpen, setSubscriptionModalOpen] = useState(false);
  const [editingEndpoint, setEditingEndpoint] = useState<NotificationEndpoint | null>(null);
  const [editingSubscription, setEditingSubscription] = useState<NotificationSubscription | null>(null);
  const [endpointForm] = Form.useForm<EndpointFormValues>();
  const [subscriptionForm] = Form.useForm<SubscriptionFormValues>();
  const endpointKind = Form.useWatch("kind", endpointForm) || "webhook";

  const load = useCallback(async (deliveryOffset = 0, deliveryLimit = PAGE_SIZE) => {
    setLoading(true);
    setError(false);
    try {
      const [endpointPage, subscriptionPage, directory, nextDeliveryPage] = await Promise.all([
        notificationsApi.listEndpoints(projectId),
        notificationsApi.listSubscriptions(projectId),
        canManage ? notificationsApi.listProjectNotificationRecipients(projectId) : Promise.resolve([]),
        isPlatformAdmin
          ? notificationsApi.listNotificationDeliveries({ offset: deliveryOffset, limit: deliveryLimit })
          : Promise.resolve(null),
      ]);
      setEndpoints(endpointPage.items);
      setSubscriptions(subscriptionPage.items);
      setRecipients(directory);
      if (nextDeliveryPage) {
        setDeliveries(nextDeliveryPage.items);
        setDeliveryPage({
          total: nextDeliveryPage.total,
          offset: nextDeliveryPage.offset ?? deliveryOffset,
          limit: nextDeliveryPage.limit ?? deliveryLimit,
        });
      }
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [canManage, isPlatformAdmin, projectId]);

  useEffect(() => { void load(); }, [load]);

  const endpointOptions = useMemo(
    () => endpoints.map((endpoint) => ({ value: endpoint.id, label: `${endpoint.name} (${endpoint.kind})` })),
    [endpoints],
  );
  const recipientOptions = useMemo(
    () => recipients.map((recipient) => ({
      value: recipient.user_id,
      label: `${recipient.username} (${t.modelRegistry[recipient.role]})`,
    })),
    [recipients, t.modelRegistry],
  );

  const saveEndpoint = async (values: EndpointFormValues) => {
    try {
      if (editingEndpoint) {
        await notificationsApi.updateEndpoint(projectId, editingEndpoint.id, { name: values.name.trim() });
      } else {
        await notificationsApi.createEndpoint(projectId, endpointPayload(values));
      }
      message.success(copy.configurationSaved);
      setEndpointModalOpen(false);
      setEditingEndpoint(null);
      endpointForm.resetFields();
      await load();
    } catch (error) {
      message.error(error instanceof Error && error.message === "headers" ? copy.invalidHeaders : copy.configurationFailed);
    }
  };

  const saveSubscription = async (values: SubscriptionFormValues) => {
    const payload: NotificationSubscriptionInput = {
      endpoint_id: values.endpoint_id,
      event_types: commaSeparated(values.event_types),
      minimum_severity: values.minimum_severity,
      recipient_roles: values.recipient_roles || [],
      recipient_user_ids: values.recipient_user_ids || [],
      enabled: values.enabled !== false,
    };
    try {
      if (editingSubscription) {
        await notificationsApi.updateSubscription(projectId, editingSubscription.id, payload);
      } else {
        await notificationsApi.createSubscription(projectId, payload);
      }
      message.success(copy.configurationSaved);
      setSubscriptionModalOpen(false);
      setEditingSubscription(null);
      subscriptionForm.resetFields();
      await load();
    } catch {
      message.error(copy.configurationFailed);
    }
  };

  const toggleEndpoint = async (endpoint: NotificationEndpoint, enabled: boolean) => {
    try {
      await notificationsApi.updateEndpoint(projectId, endpoint.id, { enabled });
      await load();
    } catch {
      message.error(copy.configurationFailed);
    }
  };

  const toggleSubscription = async (subscription: NotificationSubscription, enabled: boolean) => {
    try {
      await notificationsApi.updateSubscription(projectId, subscription.id, { enabled });
      await load();
    } catch {
      message.error(copy.configurationFailed);
    }
  };

  const openEndpointCreate = () => {
    setEditingEndpoint(null);
    endpointForm.resetFields();
    setEndpointModalOpen(true);
  };

  const openEndpointEdit = (endpoint: NotificationEndpoint) => {
    setEditingEndpoint(endpoint);
    endpointForm.setFieldsValue({ name: endpoint.name });
    setEndpointModalOpen(true);
  };

  const openSubscriptionCreate = () => {
    setEditingSubscription(null);
    subscriptionForm.resetFields();
    setSubscriptionModalOpen(true);
  };

  const openSubscriptionEdit = (subscription: NotificationSubscription) => {
    setEditingSubscription(subscription);
    subscriptionForm.setFieldsValue({
      endpoint_id: subscription.endpoint_id,
      event_types: subscription.event_types.join(", "),
      minimum_severity: subscription.minimum_severity,
      recipient_roles: subscription.recipient_roles,
      recipient_user_ids: subscription.recipient_user_ids,
      enabled: subscription.enabled,
    });
    setSubscriptionModalOpen(true);
  };

  const testEndpoint = async (endpointId: string) => {
    try {
      const result = await notificationsApi.testEndpoint(projectId, endpointId);
      if (result.status === "sent") message.success(copy.testSent);
      else message.error(result.error_code || copy.testFailed);
    } catch {
      message.error(copy.testFailed);
    }
  };

  const deleteEndpoint = async (endpointId: string) => {
    try {
      await notificationsApi.deleteEndpoint(projectId, endpointId);
      await load();
    } catch {
      message.error(copy.configurationFailed);
    }
  };

  const deleteSubscription = async (subscriptionId: string) => {
    try {
      await notificationsApi.deleteSubscription(projectId, subscriptionId);
      await load();
    } catch {
      message.error(copy.configurationFailed);
    }
  };

  const retryDelivery = async (deliveryId: string) => {
    try {
      await notificationsApi.retryDelivery(deliveryId);
      message.success(copy.deliveryRetryQueued);
      await load();
    } catch {
      message.error(copy.configurationFailed);
    }
  };

  return <>
    {loading ? <div style={{ textAlign: "center", padding: 20 }}><Spin aria-label={copy.loading} /></div> : null}
    {error ? <Alert type="error" showIcon message={copy.loadFailed} /> : null}
    {!loading && !error ? <>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", marginBottom: 12 }}>
        <Typography.Title level={5} style={{ margin: 0 }}>{copy.endpoints}</Typography.Title>
        {canManage ? <Button aria-label={copy.addEndpoint} type="primary" icon={<PlusOutlined />} onClick={openEndpointCreate}>{copy.addEndpoint}</Button> : null}
      </div>
      <Table<NotificationEndpoint>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={endpoints}
        locale={{ emptyText: copy.noEndpoints }}
        columns={[
          { title: copy.endpointName, dataIndex: "name" },
          {
            title: copy.channel,
            dataIndex: "kind",
            render: (kind: NotificationEndpointKind) => <Tag>{
              kind === "in_app" ? copy.inApp : kind === "wecom" ? copy.wecom : kind === "email" ? copy.email : copy.webhook
            }</Tag>,
          },
          { title: copy.destination, dataIndex: "destination_hint" },
          {
            title: copy.status,
            dataIndex: "enabled",
            render: (enabled: boolean, endpoint: NotificationEndpoint) => canManage ? <Switch aria-label={copy.enabled} checked={enabled} onChange={(value) => void toggleEndpoint(endpoint, value)} /> : <Tag color={enabled ? "green" : "default"}>{enabled ? copy.enabled : copy.disabled}</Tag>,
          },
          ...(canManage ? [{
            title: copy.actions,
            render: (_: unknown, endpoint: NotificationEndpoint) => <Space size={0}>
              <Tooltip title={copy.editEndpoint}><Button aria-label={copy.editEndpoint} type="text" icon={<EditOutlined />} onClick={() => openEndpointEdit(endpoint)} /></Tooltip>
              <Tooltip title={copy.testEndpoint}><Button aria-label={copy.testEndpoint} type="text" icon={<SendOutlined />} onClick={() => void testEndpoint(endpoint.id)} /></Tooltip>
              <Popconfirm
                title={copy.deleteEndpoint}
                okText={copy.confirmDelete}
                cancelText={copy.cancel}
                okButtonProps={{ danger: true }}
                onConfirm={() => void deleteEndpoint(endpoint.id)}
              >
                <Tooltip title={copy.deleteEndpoint}><Button aria-label={copy.deleteEndpoint} type="text" danger icon={<DeleteOutlined />} /></Tooltip>
              </Popconfirm>
            </Space>,
          }] : []),
        ]}
      />

      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", margin: "24px 0 12px" }}>
        <Typography.Title level={5} style={{ margin: 0 }}>{copy.subscriptions}</Typography.Title>
        {canManage ? <Button aria-label={copy.addSubscription} icon={<PlusOutlined />} onClick={openSubscriptionCreate}>{copy.addSubscription}</Button> : null}
      </div>
      <Table<NotificationSubscription>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={subscriptions}
        locale={{ emptyText: copy.noSubscriptions }}
        columns={[
          { title: copy.endpointName, dataIndex: "endpoint_id", render: (id: string) => endpoints.find((endpoint) => endpoint.id === id)?.name || id },
          { title: copy.eventTypes, dataIndex: "event_types", render: (types: string[]) => types.join(", ") },
          {
            title: copy.minimumSeverity,
            dataIndex: "minimum_severity",
            render: (severity: string) => <Tag>{stateLabel(copy.severityLabels as Record<string, string>, severity)}</Tag>,
          },
          {
            title: copy.status,
            dataIndex: "enabled",
            render: (enabled: boolean, subscription: NotificationSubscription) => canManage
              ? <Switch aria-label={copy.enabled} checked={enabled} onChange={(value) => void toggleSubscription(subscription, value)} />
              : <Tag color={enabled ? "green" : "default"}>{enabled ? copy.enabled : copy.disabled}</Tag>,
          },
          ...(canManage ? [{
            title: copy.actions,
            render: (_: unknown, subscription: NotificationSubscription) => <Space size={0}>
              <Tooltip title={copy.editSubscription}><Button aria-label={copy.editSubscription} type="text" icon={<EditOutlined />} onClick={() => openSubscriptionEdit(subscription)} /></Tooltip>
              <Popconfirm
                title={copy.deleteSubscription}
                okText={copy.confirmDelete}
                cancelText={copy.cancel}
                okButtonProps={{ danger: true }}
                onConfirm={() => void deleteSubscription(subscription.id)}
              >
                <Tooltip title={copy.deleteSubscription}><Button aria-label={copy.deleteSubscription} type="text" danger icon={<DeleteOutlined />} /></Tooltip>
              </Popconfirm>
            </Space>,
          }] : []),
        ]}
      />

      {isPlatformAdmin ? <>
        <Typography.Title level={5} style={{ margin: "24px 0 12px" }}>{copy.adminDeliveries}</Typography.Title>
        <Table
          rowKey="id"
          size="small"
          pagination={{
            current: Math.floor(deliveryPage.offset / deliveryPage.limit) + 1,
            pageSize: deliveryPage.limit,
            total: deliveryPage.total,
            showSizeChanger: false,
            onChange: (nextPage, pageSize) => void load((nextPage - 1) * pageSize, pageSize),
          }}
          dataSource={deliveries}
          locale={{ emptyText: copy.noDeliveries }}
          columns={[
            { title: copy.destination, dataIndex: "destination_hint" },
            { title: copy.status, dataIndex: "status", render: (status: string) => <Tag>{stateLabel(copy.deliveryStatusLabels as Record<string, string>, status)}</Tag> },
            { title: copy.attempts, dataIndex: "attempts" },
            { title: copy.errorCode, dataIndex: "error_code" },
            { title: copy.nextAttempt, dataIndex: "next_attempt_at", render: (value: string | null) => localTime(value) },
            {
              title: copy.actions,
              render: (_: unknown, delivery: { id: string; status: string }) => ["failed", "dead_letter"].includes(delivery.status) ? <Tooltip title={copy.retry}><Button aria-label={copy.retry} type="text" icon={<ReloadOutlined />} onClick={() => void retryDelivery(delivery.id)} /></Tooltip> : null,
            },
          ]}
        />
      </> : null}
    </> : null}

    <Modal
      title={editingEndpoint ? copy.editEndpoint : copy.addEndpoint}
      open={endpointModalOpen}
      okText={copy.save}
      cancelText={copy.cancel}
      onCancel={() => { setEndpointModalOpen(false); setEditingEndpoint(null); endpointForm.resetFields(); }}
      onOk={() => endpointForm.submit()}
      destroyOnHidden
    >
      <Form<EndpointFormValues> form={endpointForm} layout="vertical" initialValues={{ kind: "webhook", signature_mode: "none" }} onFinish={saveEndpoint}>
        <Form.Item name="name" label={copy.endpointName} rules={[{ required: true }]}><Input /></Form.Item>
        {!editingEndpoint ? <>
          <Form.Item name="kind" label={copy.channel} rules={[{ required: true }]}>
            <Select options={[
              { value: "in_app", label: copy.inApp },
              { value: "wecom", label: copy.wecom },
              { value: "email", label: copy.email },
              { value: "webhook", label: copy.webhook },
            ]} />
          </Form.Item>
          {endpointKind === "in_app" ? <Form.Item name="recipient_user_ids" label={copy.recipientUsers} rules={[{ required: true }]}><Select mode="multiple" options={recipientOptions} /></Form.Item> : null}
          {endpointKind === "email" ? <>
            <Form.Item name="to" label={copy.recipients} rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="cc" label={copy.ccRecipients}><Input /></Form.Item>
          </> : null}
          {endpointKind === "wecom" || endpointKind === "webhook" ? <Form.Item name="url" label={copy.url} rules={[{ required: true, type: "url" }]}><Input /></Form.Item> : null}
          {endpointKind === "webhook" ? <>
            <Form.Item name="headers" label={copy.headers}><Input.TextArea rows={2} /></Form.Item>
            <Form.Item name="signature_mode" label={copy.signatureMode}>
              <Select options={[{ value: "none", label: copy.noSignature }, { value: "hmac-sha256", label: copy.hmacSha256 }]} />
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(previous, current) => previous.signature_mode !== current.signature_mode}>
              {({ getFieldValue }) => getFieldValue("signature_mode") === "hmac-sha256" ? <Form.Item name="signing_secret" label={copy.signingSecret} rules={[{ required: true }]}><Input.Password autoComplete="new-password" /></Form.Item> : null}
            </Form.Item>
          </> : null}
        </> : null}
      </Form>
    </Modal>

    <Modal
      title={editingSubscription ? copy.editSubscription : copy.addSubscription}
      open={subscriptionModalOpen}
      okText={copy.save}
      cancelText={copy.cancel}
      onCancel={() => { setSubscriptionModalOpen(false); setEditingSubscription(null); subscriptionForm.resetFields(); }}
      onOk={() => subscriptionForm.submit()}
      destroyOnHidden
    >
      <Form<SubscriptionFormValues> form={subscriptionForm} layout="vertical" initialValues={{ minimum_severity: "info", recipient_roles: [], enabled: true }} onFinish={saveSubscription}>
        <Form.Item name="endpoint_id" label={copy.endpointName} rules={[{ required: true }]}><Select options={endpointOptions} /></Form.Item>
        <Form.Item name="event_types" label={copy.eventTypes} rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="minimum_severity" label={copy.minimumSeverity}>
          <Select options={[{ value: "info", label: "info" }, { value: "warning", label: "warning" }, { value: "critical", label: "critical" }]} />
        </Form.Item>
        <Form.Item name="recipient_roles" label={copy.recipientRoles}>
          <Select mode="multiple" options={["owner", "editor", "operator", "viewer"].map((role) => ({ value: role, label: t.modelRegistry[role as ProjectRole] }))} />
        </Form.Item>
        <Form.Item name="recipient_user_ids" label={copy.recipientUsers}><Select mode="multiple" options={recipientOptions} /></Form.Item>
        <Form.Item name="enabled" label={copy.enabled} valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Modal>
  </>;
}

export default function ProjectGovernanceTabs({
  projectId,
  projectRole,
  isPlatformAdmin = localStorage.getItem("role") === "admin",
}: ProjectGovernanceTabsProps) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState("members");
  const isOwner = projectRole === "owner";
  const canManageNotifications = isOwner || projectRole === "editor";

  return <section style={{ marginTop: 28 }} aria-label={t.projectGovernance.title}>
    <Typography.Title level={4}>{t.projectGovernance.title}</Typography.Title>
    <Tabs
      activeKey={activeTab}
      onChange={setActiveTab}
      items={[
        { key: "members", label: t.projectGovernance.members },
        { key: "audit", label: t.projectGovernance.audit },
        { key: "notifications", label: t.projectGovernance.notifications },
      ]}
    />
    {activeTab === "members" ? <MembersPanel projectId={projectId} isOwner={isOwner} /> : null}
    {activeTab === "audit" ? <AuditPanel projectId={projectId} isOwner={isOwner} /> : null}
    {activeTab === "notifications" ? <NotificationSettingsPanel projectId={projectId} canManage={canManageNotifications} isPlatformAdmin={isPlatformAdmin} /> : null}
  </section>;
}
