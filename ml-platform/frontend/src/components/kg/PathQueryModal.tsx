import { useState } from "react";
import { AutoComplete, Button, Empty, Modal, Space, Spin, Tag, Typography, message } from "antd";
import { NodeIndexOutlined } from "@ant-design/icons";
import apiClient from "../../api/client";
import { useI18n } from "../../i18n";

const { Text } = Typography;

interface PathResult {
  nodes: { id: string; name: string; type: string }[];
  relations: { source?: string; target?: string; type: string; weight?: number }[];
}

export default function PathQueryModal({
  kbId,
  nodes,
  open,
  onClose,
  onLocate,
}: {
  kbId: string | null;
  nodes: { id: string; label: string }[];
  open: boolean;
  onClose: () => void;
  onLocate?: (entityId: string) => void;
}) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [fromId, setFromId] = useState<string | null>(null);
  const [toId, setToId] = useState<string | null>(null);
  const [result, setResult] = useState<PathResult | null>(null);
  const [loading, setLoading] = useState(false);

  const options = nodes.map((n) => ({ value: n.label, id: n.id }));
  const pickByLabel = (label: string): string | null =>
    nodes.find((n) => n.label === label)?.id || null;

  const query = async () => {
    if (!kbId || !fromId || !toId) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await apiClient.get(`/knowledge/bases/${kbId}/graph/query/path`, {
        params: { from_id: fromId, to_id: toId },
      });
      const data: PathResult = res.data;
      if (!data.nodes?.length) {
        message.info(zh ? "两实体间无可达路径（≤6 跳）" : "No path within 6 hops");
      }
      setResult(data);
    } catch (e: any) {
      message.error(e.response?.data?.detail || (zh ? "查询失败" : "Query failed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={
        <Space>
          <NodeIndexOutlined />
          {zh ? "路径查询（最短路径 ≤6 跳）" : "Path query (shortest, ≤6 hops)"}
        </Space>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={520}
    >
      <Space direction="vertical" style={{ width: "100%" }} size={10}>
        <Space wrap>
          <AutoComplete
            style={{ width: 180 }}
            options={options}
            placeholder={zh ? "起点实体" : "From entity"}
            filterOption={(input, option) =>
              (option?.value || "").toLowerCase().includes(input.toLowerCase())}
            onSelect={(v: string) => setFromId(pickByLabel(v))}
          />
          <Text type="secondary">→</Text>
          <AutoComplete
            style={{ width: 180 }}
            options={options}
            placeholder={zh ? "终点实体" : "To entity"}
            filterOption={(input, option) =>
              (option?.value || "").toLowerCase().includes(input.toLowerCase())}
            onSelect={(v: string) => setToId(pickByLabel(v))}
          />
          <Button type="primary" onClick={query} disabled={!fromId || !toId} loading={loading}>
            {zh ? "查询" : "Query"}
          </Button>
        </Space>
        {loading && <Spin style={{ display: "block", margin: "20px auto" }} />}
        {!loading && result && (
          result.nodes.length ? (
            <Space size={6} wrap style={{ marginTop: 4 }} data-testid="kg-path-result">
              {result.nodes.map((n, i) => (
                <Space key={n.id} size={6}>
                  <Tag
                    color={i === 0 || i === result.nodes.length - 1 ? "purple" : "default"}
                    style={{ cursor: "pointer" }}
                    onClick={() => onLocate?.(n.id)}
                  >
                    {n.name}
                  </Tag>
                  {i < result.nodes.length - 1 && (
                    <Text type="secondary">
                      -[{result.relations[i]?.type || "相关"}]-&gt;
                    </Text>
                  )}
                </Space>
              ))}
            </Space>
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={zh ? "无路径" : "No path"} />
          )
        )}
      </Space>
    </Modal>
  );
}
