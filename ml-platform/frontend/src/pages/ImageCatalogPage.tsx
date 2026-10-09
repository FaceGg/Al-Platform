import { useCallback, useEffect, useState } from "react";
import { Button, Form, Input, Modal, Select, Space, Table, Tag, Typography } from "antd";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { App as AntApp } from "antd";
import { formatApiError } from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";
import { ContainerImage, listImages, registerImage, updateImage } from "../api/notebooks";

const SCAN_COLORS: Record<string, string> = {
  unknown: "default",
  pending: "processing",
  passed: "success",
  failed: "error",
};

export default function ImageCatalogPage() {
  const { t } = useI18n();
  const { message } = AntApp.useApp();
  const it = (key: string, fallback: string) =>
    (t as unknown as Record<string, Record<string, string>>)?.images?.[key] ?? fallback;

  const [images, setImages] = useState<ContainerImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listImages();
      setImages(data.items);
    } catch (error) {
      message.error(formatApiError(error, it("loadFailed", "加载失败")));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRegister = async () => {
    try {
      const values = await form.validateFields();
      await registerImage(values);
      message.success(it("registerOk", "镜像已登记"));
      setRegisterOpen(false);
      await load();
    } catch (error) {
      message.error(formatApiError(error, it("registerFailed", "登记失败")));
    }
  };

  const handleScanUpdate = async (image: ContainerImage, scanStatus: string) => {
    try {
      await updateImage(image.id, { scan_status: scanStatus as ContainerImage["scan_status"] });
      await load();
    } catch (error) {
      message.error(formatApiError(error, it("updateFailed", "更新失败")));
    }
  };

  const shortDigest = (digest: string) => `${digest.slice(0, 14)}…${digest.slice(-6)}`;

  const columns = [
    { title: it("repository", "仓库"), key: "repo", render: (_: unknown, image: ContainerImage) => `${image.registry}/${image.repository}` },
    {
      title: it("digest", "摘要"),
      dataIndex: "digest",
      key: "digest",
      render: (digest: string) => (
        <Typography.Text code title={digest}>
          {shortDigest(digest)}
        </Typography.Text>
      ),
    },
    {
      title: it("scan", "扫描"),
      dataIndex: "scan_status",
      key: "scan_status",
      render: (status: string, image: ContainerImage) => (
        <Select
          size="small"
          value={status}
          style={{ width: 110 }}
          onChange={(value) => handleScanUpdate(image, value)}
          options={Object.keys(SCAN_COLORS).map((value) => ({ value, label: value }))}
        />
      ),
    },
    {
      title: it("visibility", "可见性"),
      dataIndex: "visibility",
      key: "visibility",
      render: (visibility: string) => <Tag>{visibility}</Tag>,
    },
    { title: it("source", "来源"), dataIndex: "source", key: "source" },
  ];

  return (
    <AppLayout>
      <div style={{ padding: 24 }}>
        <Space style={{ marginBottom: 16 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {it("title", "镜像目录")}
          </Typography.Title>
          <Button icon={<ReloadOutlined />} onClick={load}>
            {it("refresh", "刷新")}
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setRegisterOpen(true)}>
            {it("register", "登记镜像")}
          </Button>
        </Space>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns as never}
          dataSource={images}
          locale={{ emptyText: it("empty", "目录为空") }}
          pagination={{ pageSize: 50, showSizeChanger: false }}
        />
        <Modal
          title={it("register", "登记镜像")}
          open={registerOpen}
          onOk={handleRegister}
          onCancel={() => setRegisterOpen(false)}
          okText={it("save", "保存")}
          cancelText={it("cancel", "取消")}
        >
          <Form form={form} layout="vertical">
            <Form.Item name="registry" label={it("registry", "Registry")} rules={[{ required: true }]}>
              <Input placeholder="registry.local" />
            </Form.Item>
            <Form.Item name="repository" label={it("repository", "仓库路径")} rules={[{ required: true }]}>
              <Input placeholder="w15/notebook-base" />
            </Form.Item>
            <Form.Item
              name="digest"
              label={it("digest", "摘要(sha256,不可变)")}
              rules={[
                { required: true },
                { pattern: /^sha256:[a-f0-9]{64}$/, message: it("digestPattern", "格式:sha256:64 位十六进制") },
              ]}
            >
              <Input placeholder="sha256:…" />
            </Form.Item>
            <Form.Item name="visibility" label={it("visibility", "可见性")} initialValue="project">
              <Select
                options={[
                  { value: "project", label: "project" },
                  { value: "platform", label: "platform" },
                ]}
              />
            </Form.Item>
            <Form.Item name="scan_status" label={it("scan", "扫描状态")} initialValue="unknown">
              <Select
                options={Object.keys(SCAN_COLORS).map((value) => ({ value, label: value }))}
              />
            </Form.Item>
          </Form>
        </Modal>
      </div>
    </AppLayout>
  );
}
