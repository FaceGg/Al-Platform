import { useEffect, useState, useRef, useCallback } from "react";
import {
  Select, Button, Form, Input, List, Typography, message, Card, Space, Tag, Empty
} from "antd";
import { PlusOutlined, DeleteOutlined, ReloadOutlined } from "@ant-design/icons";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text } = Typography;

interface GraphNode {
  id: string; label: string; type?: string; x?: number; y?: number;
}
interface GraphEdge {
  source: string; target: string; label?: string; type?: string;
}
interface GraphData {
  nodes: GraphNode[]; edges: GraphEdge[];
}

export default function KnowledgeGraphPage() {
  const { t } = useI18n();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [bases, setBases] = useState<any[]>([]);
  const [selectedKb, setSelectedKb] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();
  const [edgeForm] = Form.useForm();
  const [simNodes, setSimNodes] = useState<Array<GraphNode & { vx: number; vy: number }>>([]);
  const animRef = useRef<number>(0);

  useEffect(() => {
    apiClient.get("/knowledge/bases").then((res) => {
      setBases(res.data.items || res.data || []);
    }).catch(() => {});
  }, []);

  const loadGraph = useCallback(() => {
    if (!selectedKb) return;
    setLoading(true);
    apiClient.get("/knowledge/bases/" + selectedKb + "/graph")
      .then((res) => {
        const data = res.data;
        const nodes = (data.nodes || []).map((n: any, i: number) => ({
          ...n, x: Math.random() * 600 + 50, y: Math.random() * 400 + 50,
        }));
        setGraphData({ nodes, edges: data.edges || [] });
      })
      .catch(() => message.error(t.common.error))
      .finally(() => setLoading(false));
  }, [selectedKb, t]);

  useEffect(() => { loadGraph(); }, [selectedKb]);

  // Simple force-directed layout simulation
  useEffect(() => {
    if (graphData.nodes.length === 0) { setSimNodes([]); return; }
    const nodes = graphData.nodes.map((n) => ({ ...n, vx: 0, vy: 0 }));
    const edges = graphData.edges;
    setSimNodes(nodes);

    let frame = 0;
    const maxFrames = 300;
    const tick = () => {
      frame++;
      if (frame > maxFrames) return;
      setSimNodes((prev) => {
        const next = prev.map((n) => ({ ...n }));
        // Repulsion
        for (let i = 0; i < next.length; i++) {
          for (let j = i + 1; j < next.length; j++) {
            const dx = (next[j].x || 0) - (next[i].x || 0);
            const dy = (next[j].y || 0) - (next[i].y || 0);
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            const repForce = Math.min(2000 / (dist * dist), 20);
            const fx = (dx / dist) * repForce;
            const fy = (dy / dist) * repForce;
            next[i].vx -= fx; next[i].vy -= fy;
            next[j].vx += fx; next[j].vy += fy;
          }
        }
        // Attraction along edges
        for (const e of edges) {
          const si = next.findIndex((n) => n.id === e.source);
          const ti = next.findIndex((n) => n.id === e.target);
          if (si < 0 || ti < 0) continue;
          const dx = (next[ti].x || 0) - (next[si].x || 0);
          const dy = (next[ti].y || 0) - (next[si].y || 0);
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const attrForce = (dist - 150) * 0.005;
          const fx = (dx / dist) * attrForce;
          const fy = (dy / dist) * attrForce;
          next[si].vx += fx; next[si].vy += fy;
          next[ti].vx -= fx; next[ti].vy -= fy;
        }
        // Center gravity
        for (const n of next) {
          n.vx += (300 - (n.x || 0)) * 0.001;
          n.vy += (250 - (n.y || 0)) * 0.001;
        }
        // Apply velocity with damping
        for (const n of next) {
          n.vx *= 0.85; n.vy *= 0.85;
          n.x = Math.max(30, Math.min(770, (n.x || 0) + n.vx));
          n.y = Math.max(30, Math.min(470, (n.y || 0) + n.vy));
        }
        return next;
      });
      if (frame < maxFrames) {
        animRef.current = requestAnimationFrame(tick);
      }
    };
    animRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animRef.current);
  }, [graphData]);

  // Canvas drawing
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || simNodes.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);

    // Draw edges
    for (const e of graphData.edges) {
      const s = simNodes.find((n) => n.id === e.source);
      const t = simNodes.find((n) => n.id === e.target);
      if (!s || !t) continue;
      ctx.beginPath();
      ctx.moveTo(s.x || 0, s.y || 0);
      ctx.lineTo(t.x || 0, t.y || 0);
      ctx.strokeStyle = "#ccc";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      if (e.label) {
        const mx = ((s.x || 0) + (t.x || 0)) / 2;
        const my = ((s.y || 0) + (t.y || 0)) / 2;
        ctx.fillStyle = "#999";
        ctx.font = "10px sans-serif";
        ctx.fillText(e.label, mx, my - 4);
      }
    }

    // Draw nodes
    for (const n of simNodes) {
      ctx.beginPath();
      ctx.arc(n.x || 0, n.y || 0, 18, 0, Math.PI * 2);
      ctx.fillStyle = n.type === "entity" ? "#1890ff" : "#52c41a";
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = "bold 10px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const lbl = n.label.length > 8 ? n.label.slice(0, 7) + ".." : n.label;
      ctx.fillText(lbl, n.x || 0, n.y || 0);
    }
  }, [simNodes, graphData.edges]);

  const addEntity = async (values: any) => {
    try {
      await apiClient.post("/knowledge/bases/" + selectedKb + "/entities", values);
      message.success(t.common.success);
      form.resetFields();
      loadGraph();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const addRelation = async (values: any) => {
    try {
      await apiClient.post("/knowledge/bases/" + selectedKb + "/relations", values);
      message.success(t.common.success);
      edgeForm.resetFields();
      loadGraph();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const deleteEntity = async (id: string) => {
    try {
      await apiClient.delete("/knowledge/bases/" + selectedKb + "/entities/" + id);
      message.success(t.common.success);
      loadGraph();
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  return (
    <AppLayout>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h3>{t.knowledge.graph}</h3>
        <Space>
          <Select
            placeholder={t.knowledge.title}
            style={{ width: 200 }}
            value={selectedKb}
            onChange={setSelectedKb}
            options={bases.map((b: any) => ({ value: b.id, label: b.name }))}
          />
          <Button icon={<ReloadOutlined />} onClick={loadGraph} loading={loading}>
            {t.monitor.refresh}
          </Button>
        </Space>
      </div>
      <div style={{ display: "flex", gap: 16 }}>
        <div style={{ flex: 1 }}>
          <Card
            style={{ height: 500, padding: 0, overflow: "hidden" }}
            bodyStyle={{ height: "100%", padding: 0 }}
          >
            {simNodes.length === 0 && !loading ? (
              <Empty description={t.common.loading} style={{ marginTop: 200 }} />
            ) : (
              <canvas ref={canvasRef} style={{ width: "100%", height: "100%", display: "block" }} />
            )}
          </Card>
        </div>
        <div style={{ width: 320, display: "flex", flexDirection: "column", gap: 12 }}>
          <Card size="small" title={t.knowledge.add_entity}>
            <Form form={form} onFinish={addEntity} layout="vertical" size="small">
              <Form.Item name="name" label={t.knowledge.entity_name} rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="type" label={t.knowledge.entity_type}>
                <Input />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<PlusOutlined />} block>
                {t.knowledge.add_entity}
              </Button>
            </Form>
          </Card>
          <Card size="small" title={t.knowledge.relation}>
            <Form form={edgeForm} onFinish={addRelation} layout="vertical" size="small">
              <Form.Item name="source_id" label="Source ID" rules={[{ required: true }]}>
                <Input placeholder="source entity id" />
              </Form.Item>
              <Form.Item name="target_id" label="Target ID" rules={[{ required: true }]}>
                <Input placeholder="target entity id" />
              </Form.Item>
              <Form.Item name="type" label={t.knowledge.relation_type}>
                <Input />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<PlusOutlined />} block>
                {t.knowledge.relation}
              </Button>
            </Form>
          </Card>
          <Card size="small" title={t.knowledge.entity + " " + t.nav.data}>
            <List
              size="small"
              dataSource={graphData.nodes}
              style={{ maxHeight: 200, overflowY: "auto" }}
              locale={{ emptyText: <Empty description={t.common.loading} /> }}
              renderItem={(node: GraphNode) => (
                <List.Item
                  actions={[
                    <Button type="link" danger size="small" icon={<DeleteOutlined />}
                      onClick={() => deleteEntity(node.id)} />,
                  ]}
                >
                  <Space>
                    <Tag color={node.type === "entity" ? "blue" : "green"}>{node.type || "entity"}</Tag>
                    <Text>{node.label}</Text>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </div>
      </div>
    </AppLayout>
  );
}
