import { useCallback, useEffect, useState } from "react";
import { Button, Card, Empty, Radio, Space, Tag, Typography, message } from "antd";
import { CheckOutlined, CloseOutlined, MergeOutlined } from "@ant-design/icons";
import apiClient from "../../api/client";
import { useI18n } from "../../i18n";

const { Text } = Typography;

interface Suggestion {
  id: string;
  type: "merge_entity" | "attribute_conflict";
  status: string;
  method: string;
  similarity: number | null;
  canonical_name: string | null;
  entity_a: { id: string; name: string; type: string } | null;
  entity_b: { id: string; name: string; type: string } | null;
  payload: {
    reason?: string;
    attribute?: string;
    values?: { value: string; doc_ids?: string[]; evidence?: string }[];
    resolved?: { value: string };
  };
}

export default function FusionPanel({
  kbId,
  onChanged,
}: {
  kbId: string | null;
  onChanged?: () => void;
}) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [items, setItems] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [chosen, setChosen] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    if (!kbId) {
      setItems([]);
      return;
    }
    setLoading(true);
    apiClient
      .get(`/knowledge/bases/${kbId}/graph/fusion/suggestions`, {
        params: { status: "pending", limit: 30 },
      })
      .then((res) => setItems(res.data || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [kbId]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (s: Suggestion, accept: boolean) => {
    if (!kbId) return;
    try {
      if (accept) {
        const body: Record<string, unknown> = {};
        if (s.type === "attribute_conflict") {
          const value = chosen[s.id] || s.payload?.values?.[0]?.value || "";
          body["resolved"] = { value };
        }
        await apiClient.post(
          `/knowledge/bases/${kbId}/graph/fusion/suggestions/${s.id}/accept`,
          body,
        );
        message.success(zh ? "已执行合并/裁决" : "Applied");
      } else {
        await apiClient.post(
          `/knowledge/bases/${kbId}/graph/fusion/suggestions/${s.id}/reject`,
        );
        message.info(zh ? "已驳回" : "Rejected");
      }
      load();
      onChanged?.();
    } catch (e: any) {
      message.error(e.response?.data?.detail || (zh ? "操作失败" : "Operation failed"));
    }
  };

  return (
    <Card
      size="small"
      title={
        <Space>
          <MergeOutlined />
          {zh ? "融合审核" : "Fusion review"}
          {items.length > 0 && <Tag color="orange">{items.length}</Tag>}
        </Space>
      }
      extra={
        <Button size="small" type="link" onClick={load} loading={loading}>
          {zh ? "刷新" : "Refresh"}
        </Button>
      }
      data-testid="kg-fusion-panel"
    >
      {items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={zh ? "暂无待审核建议" : "No pending suggestions"}
          style={{ margin: "12px 0" }}
        />
      ) : (
        <div style={{ maxHeight: 260, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((s) => (
            <div
              key={s.id}
              style={{ border: "1px solid #eee", borderRadius: 8, padding: 8, fontSize: 12 }}
              data-testid="kg-fusion-item"
            >
              {s.type === "merge_entity" ? (
                <>
                  <Space size={6} wrap>
                    <Text strong>{s.entity_a?.name}</Text>
                    <Text type="secondary">≈</Text>
                    <Text strong>{s.entity_b?.name}</Text>
                    {s.similarity != null && (
                      <Tag color="purple">{(s.similarity * 100).toFixed(0)}%</Tag>
                    )}
                    <Tag>{s.method === "llm" ? (zh ? "大模型" : "LLM") : zh ? "自动" : "auto"}</Tag>
                  </Space>
                  {s.canonical_name && (
                    <div style={{ color: "#888", marginTop: 2 }}>
                      {zh ? "建议规范名：" : "Canonical: "}
                      {s.canonical_name}
                    </div>
                  )}
                  {s.payload?.reason && (
                    <div style={{ color: "#888", marginTop: 2 }}>{s.payload.reason}</div>
                  )}
                </>
              ) : (
                <>
                  <Space size={6} wrap>
                    <Text strong>{s.entity_a?.name}</Text>
                    <Tag color="gold">
                      {zh ? "属性冲突" : "Conflict"}: {s.payload?.attribute}
                    </Tag>
                  </Space>
                  <div style={{ marginTop: 4 }}>
                    <Radio.Group
                      size="small"
                      value={chosen[s.id] || s.payload?.values?.[0]?.value}
                      onChange={(e) =>
                        setChosen((prev) => ({ ...prev, [s.id]: e.target.value }))
                      }
                      data-testid="kg-conflict-radio"
                    >
                      {(s.payload?.values || []).map((v, i) => (
                        <Radio key={i} value={v.value}>
                          {v.value}
                          {v.doc_ids?.length ? (
                            <Text type="secondary" style={{ marginLeft: 4, fontSize: 11 }}>
                              ({zh ? "文档" : "doc"} {v.doc_ids.filter(Boolean).length})
                            </Text>
                          ) : null}
                        </Radio>
                      ))}
                    </Radio.Group>
                  </div>
                </>
              )}
              <Space style={{ marginTop: 6 }}>
                <Button
                  size="small"
                  type="primary"
                  icon={<CheckOutlined />}
                  onClick={() => decide(s, true)}
                >
                  {zh ? "确认" : "Accept"}
                </Button>
                <Button size="small" icon={<CloseOutlined />} onClick={() => decide(s, false)}>
                  {zh ? "驳回" : "Reject"}
                </Button>
              </Space>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
