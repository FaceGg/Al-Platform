import { useCallback, useEffect, useState } from "react";
import {
  App as AntApp, Button, Card, Descriptions, Form, Input, Modal, Select, Space, Table, Typography,
} from "antd";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { useQualityAlertLookups } from "../hooks/useQualityAlertLookups";
import { apiErrorText } from "../api/qualityAlerts";
import { createKnowledge, listKnowledge, searchBySymptom } from "../api/qms";
import type { QmsKnowledgeEntry, QmsSymptomHit } from "../api/qms";
import { useI18n } from "../i18n";

/** 质量管理 · 质量体系 / 质量知识库（B3-10）：缺陷代码/现象/根因/措施/有效性 +
 * 关键词/缺陷代码/设备筛选 + 症状查询 Top5（关键词相关度，向量检索挂 RAG 基建）。 */

export default function QualityKnowledgePage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const { projects, projectId, setProjectId } = useQualityAlertLookups();
  const [rows, setRows] = useState<QmsKnowledgeEntry[]>([]);
  const [defectCode, setDefectCode] = useState("");
  const [keyword, setKeyword] = useState("");
  const [deviceRef, setDeviceRef] = useState("");
  const [symptom, setSymptom] = useState("");
  const [hits, setHits] = useState<QmsSymptomHit[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [detail, setDetail] = useState<QmsKnowledgeEntry | null>(null);
  const [form] = Form.useForm<{
    defect_code: string; symptom: string; root_cause?: string;
    action?: string; effectiveness?: string; device_ref?: string;
  }>();
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setRows([]); return; }
    listKnowledge(projectId, {
      defect_code: defectCode.trim() || undefined,
      keyword: keyword.trim() || undefined,
      device_ref: deviceRef.trim() || undefined,
    }).then(setRows).catch((e) => message.error(apiErrorText(e)));
  }, [projectId, defectCode, keyword, deviceRef, message]);

  useEffect(() => { load(); }, [load]);

  const runSymptomSearch = async () => {
    if (!projectId || !symptom.trim()) return;
    try {
      setHits(await searchBySymptom(projectId, symptom.trim()));
    } catch (e) {
      message.error(apiErrorText(e));
    }
  };

  const columns = [
    { title: zh ? "缺陷代码" : "Defect code", dataIndex: "defect_code", key: "code", width: 140 },
    { title: zh ? "现象" : "Symptom", dataIndex: "symptom", key: "symptom" },
    { title: zh ? "根因" : "Root cause", dataIndex: "root_cause", key: "root_cause", ellipsis: true },
    {
      title: zh ? "操作" : "Actions", key: "actions", width: 90,
      render: (_: unknown, row: QmsKnowledgeEntry) => (
        <Button size="small" onClick={() => setDetail(row)}>{zh ? "详情" : "Detail"}</Button>
      ),
    },
  ];

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_knowledge" testId="v2-quality-knowledge">
        <PageHeading
          section="quality"
          navKey="quality_knowledge"
          desc={zh
            ? "质量知识库：缺陷代码 / 现象 / 根因 / 措施 / 有效性结论；支持关键词、缺陷代码与设备筛选；症状查询返回 Top5 相似条目并给出匹配原因（向量检索挂 RAG 基建，本批先关键词相关度）。"
            : "Quality knowledge base with filtering and Top-5 symptom search."}
          actions={
            <Space>
              <Select
                aria-label={zh ? "选择项目" : "Select project"}
                style={{ minWidth: 180 }}
                placeholder={zh ? "选择项目" : "Select project"}
                value={projectId ?? undefined}
                onChange={(value: string) => setProjectId(value)}
                options={projects.map((item) => ({ value: item.id, label: item.name }))}
              />
              <Button type="primary" icon={<PlusOutlined />} data-testid="new-knowledge"
                onClick={() => { form.resetFields(); setCreateOpen(true); }}>
                {zh ? "新增条目" : "New entry"}
              </Button>
            </Space>
          }
        />
        <Card title={zh ? "知识条目" : "Entries"}>
          <Space style={{ marginBottom: 12 }} wrap>
            <Input allowClear placeholder={zh ? "缺陷代码" : "Defect code"} style={{ width: 160 }}
              value={defectCode} onChange={(e) => setDefectCode(e.target.value)} />
            <Input allowClear placeholder={zh ? "关键词" : "Keyword"} style={{ width: 200 }}
              value={keyword} onChange={(e) => setKeyword(e.target.value)} />
            <Input allowClear placeholder={zh ? "设备" : "Device"} style={{ width: 160 }}
              value={deviceRef} onChange={(e) => setDeviceRef(e.target.value)} />
          </Space>
          <Table
            rowKey="id" size="small" columns={columns} dataSource={rows} pagination={false}
            locale={{ emptyText: zh ? "暂无知识条目：点击「新增条目」沉淀第一条（现象 / 根因 / 措施）" : "No entries yet" }}
          />
        </Card>
        <Card title={zh ? "症状查询（Top5 相似）" : "Symptom search (Top 5)"} style={{ marginTop: 16 }}>
          <Space style={{ marginBottom: 12 }} wrap>
            <Input
              allowClear style={{ width: 420 }} placeholder={zh ? "描述现象，如：飞溅增大 电压波动" : "Describe the symptom"}
              value={symptom} onChange={(e) => setSymptom(e.target.value)}
              onPressEnter={() => void runSymptomSearch()}
            />
            <Button type="primary" icon={<SearchOutlined />} data-testid="symptom-search"
              onClick={() => void runSymptomSearch()}>
              {zh ? "查询" : "Search"}
            </Button>
          </Space>
          {hits.length === 0 ? (
            <Typography.Text type="secondary">
              {zh ? "无命中：症状查询按关键词相关度返回 Top5，向量检索挂点已登记（走 RAG 基建）。" : "No hits yet."}
            </Typography.Text>
          ) : (
            hits.map((hit, index) => (
              <Descriptions key={index} size="small" column={1} style={{ marginBottom: 8 }}>
                <Descriptions.Item label={zh ? "匹配" : "Match"}>
                  <Typography.Text strong>{hit.defect_code}</Typography.Text>
                  <Typography.Text type="secondary"> · {hit.match_reason}</Typography.Text>
                </Descriptions.Item>
                <Descriptions.Item label={zh ? "根因" : "Root cause"}>{hit.root_cause ?? "-"}</Descriptions.Item>
              </Descriptions>
            ))
          )}
        </Card>

        <Modal open={createOpen} destroyOnClose title={zh ? "新增知识条目" : "New entry"}
          okText={zh ? "创建" : "Create"} confirmLoading={busy}
          onCancel={() => setCreateOpen(false)} onOk={() => form.submit()}>
          <Form form={form} layout="vertical" data-testid="knowledge-form"
            onFinish={(values) => {
              setBusy(true);
              createKnowledge(projectId!, {
                defect_code: values.defect_code.trim(), symptom: values.symptom.trim(),
                root_cause: values.root_cause?.trim() || null,
                action: values.action?.trim() || null,
                effectiveness: values.effectiveness?.trim() || null,
                device_ref: values.device_ref?.trim() || null,
              }).then(() => {
                message.success(zh ? "条目已创建" : "Entry created");
                setCreateOpen(false);
                load();
              }).catch((e) => message.error(apiErrorText(e)))
                .finally(() => setBusy(false));
            }}>
            <Form.Item name="defect_code" label={zh ? "缺陷代码" : "Defect code"} rules={[{ required: true }]}>
              <Input maxLength={64} placeholder="D-001" />
            </Form.Item>
            <Form.Item name="symptom" label={zh ? "现象" : "Symptom"} rules={[{ required: true }]}>
              <Input.TextArea rows={2} />
            </Form.Item>
            <Form.Item name="root_cause" label={zh ? "根因" : "Root cause"}>
              <Input.TextArea rows={2} />
            </Form.Item>
            <Form.Item name="action" label={zh ? "措施" : "Action"}>
              <Input.TextArea rows={2} />
            </Form.Item>
            <Form.Item name="effectiveness" label={zh ? "有效性结论" : "Effectiveness"}>
              <Input.TextArea rows={2} />
            </Form.Item>
            <Form.Item name="device_ref" label={zh ? "设备（可选）" : "Device (optional)"}>
              <Input maxLength={128} />
            </Form.Item>
          </Form>
        </Modal>

        <Modal open={detail !== null} footer={null} onCancel={() => setDetail(null)}
          title={detail?.defect_code ?? ""} width={640}>
          {detail && (
            <Descriptions size="small" column={1}>
              <Descriptions.Item label={zh ? "现象" : "Symptom"}>{detail.symptom}</Descriptions.Item>
              <Descriptions.Item label={zh ? "根因" : "Root cause"}>{detail.root_cause ?? "-"}</Descriptions.Item>
            </Descriptions>
          )}
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
