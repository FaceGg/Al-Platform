import { useEffect, useState } from "react";
import { Descriptions, Drawer, Empty, List, Space, Spin, Table, Tag, Typography } from "antd";
import apiClient from "../../api/client";
import { useI18n } from "../../i18n";

const { Text } = Typography;

interface EntityDetail {
  id: string;
  name: string;
  entity_type: string;
  aliases: string[];
  merged: boolean;
  method: string;
  attributes: { name: string; value: string; evidence?: string; doc_id?: string | null }[];
  doc_ids: string[];
  related: { id: string; name: string; type: string; relation: string; weight: number }[];
}

export default function EntityDetailDrawer({
  kbId,
  entityId,
  open,
  onClose,
  onLocate,
}: {
  kbId: string | null;
  entityId: string | null;
  open: boolean;
  onClose: () => void;
  onLocate?: (entityId: string) => void;
}) {
  const { t, lang } = useI18n();
  const zh = lang === "zh";
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !kbId || !entityId) return;
    setLoading(true);
    apiClient
      .get(`/knowledge/bases/${kbId}/graph/entities/${entityId}`)
      .then((res) => setDetail(res.data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [open, kbId, entityId]);

  return (
    <Drawer
      title={detail?.name || (zh ? "实体详情" : "Entity detail")}
      open={open}
      onClose={onClose}
      width={420}
      destroyOnClose
    >
      {loading ? (
        <Spin style={{ display: "block", margin: "60px auto" }} />
      ) : !detail ? (
        <Empty description={t.common.loading} />
      ) : (
        <Space direction="vertical" style={{ width: "100%" }} size={14}>
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label={zh ? "类型" : "Type"}>
              {detail.entity_type}
            </Descriptions.Item>
            <Descriptions.Item label={zh ? "来源" : "Method"}>
              <Tag color={detail.method === "llm" ? "purple" : detail.method === "rules" ? "blue" : "default"}>
                {detail.method === "llm"
                  ? zh ? "大模型" : "LLM"
                  : detail.method === "rules"
                    ? zh ? "规则" : "Rules"
                    : zh ? "人工" : "Manual"}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label={zh ? "别名" : "Aliases"}>
              {detail.aliases.length ? (
                <Space size={4} wrap>
                  {detail.aliases.map((a) => (
                    <Tag key={a}>{a}</Tag>
                  ))}
                </Space>
              ) : (
                "-"
              )}
            </Descriptions.Item>
            <Descriptions.Item label={zh ? "出处文档" : "Docs"}>
              {detail.doc_ids.length}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Text strong>{zh ? "属性" : "Attributes"}</Text>
            <Table
              size="small"
              style={{ marginTop: 6 }}
              dataSource={detail.attributes}
              rowKey={(_, i) => String(i)}
              pagination={false}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="-" /> }}
              columns={[
                { title: zh ? "名称" : "Name", dataIndex: "name", width: 90 },
                { title: zh ? "值" : "Value", dataIndex: "value" },
                {
                  title: zh ? "原文" : "Evidence",
                  dataIndex: "evidence",
                  ellipsis: true,
                  render: (v: string) =>
                    v ? <Text type="secondary" style={{ fontSize: 11 }}>{v}</Text> : "-",
                },
              ]}
            />
          </div>

          <div>
            <Text strong>{zh ? "关联实体（按关系权重）" : "Related entities"}</Text>
            <List
              size="small"
              style={{ marginTop: 6, maxHeight: 220, overflowY: "auto" }}
              dataSource={detail.related}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="-" /> }}
              renderItem={(item) => (
                <List.Item
                  style={{ cursor: "pointer" }}
                  onClick={() => onLocate?.(item.id)}
                  actions={[<Tag key="r">{item.relation}</Tag>]}
                >
                  <Space>
                    <Text>{item.name}</Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {item.type} · w{item.weight}
                    </Text>
                  </Space>
                </List.Item>
              )}
            />
          </div>
        </Space>
      )}
    </Drawer>
  );
}
