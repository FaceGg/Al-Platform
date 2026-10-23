import { useEffect, useState } from "react";
import { Button, Card, Input, message, Modal, Popconfirm, Select, Space, Table, Tag } from "antd";
import { CopyOutlined, DeleteOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { useI18n } from "../i18n";
import AppLayout from "../components/AppLayout";
import {
  PROMPT_STAGES,
  type PromptTemplate,
  createPromptTemplate,
  deletePromptTemplate,
  listPromptTemplates,
  usePromptTemplate,
} from "../api/promptTemplates";
import { formatApiError } from "../api/client";

/**
 * 提示词模板页（§11.4）：向导中「存为模板」沉淀的提示词在此管理——
 * 与经验库刻意分离（经验=系统蒸馏的客观教训；模板=用户主观意图）。
 */

export default function PromptTemplatesPage() {
  const { t } = useI18n();
  const text = t.ptpl;
  const [items, setItems] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [stageFilter, setStageFilter] = useState<string | undefined>(undefined);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");
  const [stage, setStage] = useState<string>("analysis");
  const [content, setContent] = useState("");

  const load = () => {
    setLoading(true);
    listPromptTemplates(stageFilter ? { stage: stageFilter } : undefined)
      .then(setItems)
      .catch((error) => message.error(formatApiError(error, text.loadFailed)))
      .finally(() => setLoading(false));
  };

  useEffect(load, [stageFilter]);

  const submit = async () => {
    if (!name.trim() || !content.trim()) return;
    setSaving(true);
    try {
      await createPromptTemplate({ name: name.trim(), stage, content: content.trim() });
      message.success(text.createOk);
      setModalOpen(false);
      setName("");
      setContent("");
      load();
    } catch (error) {
      message.error(formatApiError(error, text.createFailed));
    } finally {
      setSaving(false);
    }
  };

  const use = async (template: PromptTemplate) => {
    try {
      await usePromptTemplate(template.id);
      try {
        await navigator.clipboard.writeText(template.content);
        message.success(text.useOk);
      } catch {
        message.info(text.copyFailFallback);
      }
      load();
    } catch (error) {
      message.error(formatApiError(error, text.useFailed));
    }
  };

  const remove = async (template: PromptTemplate) => {
    try {
      await deletePromptTemplate(template.id);
      message.success(text.deleteOk);
      load();
    } catch {
      message.error(text.loadFailed);
    }
  };

  const columns = [
    { title: text.colName, dataIndex: "name" },
    {
      title: text.colStage,
      dataIndex: "stage",
      render: (value: string) => <Tag>{value}</Tag>,
    },
    {
      title: text.colContent,
      dataIndex: "content",
      ellipsis: true,
    },
    { title: text.colUsage, dataIndex: "usage_count", width: 110 },
    {
      title: text.colActions,
      width: 200,
      render: (_: unknown, record: PromptTemplate) => (
        <Space>
          <Button size="small" icon={<CopyOutlined />} onClick={() => void use(record)}>
            {text.use}
          </Button>
          <Popconfirm title={text.deleteConfirm} onConfirm={() => void remove(record)}>
            <Button size="small" danger icon={<DeleteOutlined />}>
              {text.del}
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <Card
        title={text.title}
        extra={
          <Space>
            <Select
              allowClear
              placeholder={text.colStage}
              style={{ width: 140 }}
              value={stageFilter}
              onChange={setStageFilter}
              options={PROMPT_STAGES.map((value) => ({ value, label: value }))}
            />
            <Button icon={<ReloadOutlined />} onClick={load}>
              {text.refresh}
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
              {text.create}
            </Button>
          </Space>
        }
      >
        <Table rowKey="id" columns={columns as never} dataSource={items} loading={loading} pagination={{ pageSize: 10 }} />
      </Card>
      <Modal
        title={text.create}
        open={modalOpen}
        onOk={() => void submit()}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        okText={text.save}
        cancelText={text.cancel}
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Input placeholder={text.namePlaceholder} value={name} onChange={(event) => setName(event.target.value)} />
          <Select
            style={{ width: "100%" }}
            value={stage}
            onChange={setStage}
            options={PROMPT_STAGES.map((value) => ({ value, label: value }))}
          />
          <Input.TextArea
            rows={4}
            placeholder={text.contentPlaceholder}
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        </Space>
      </Modal>
    </AppLayout>
  );
}
