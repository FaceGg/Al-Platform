import { useState, useEffect } from "react";
import { Card, Table, Tag, Input, Select, Space, Typography } from "antd";
import { SearchOutlined, ApiOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import { apiGet } from "../api/client";

const { Title } = Typography;

const categoryColors: Record<string, string> = {
  computer_vision: "blue", ocr: "cyan", speech: "purple",
  nlp: "geekblue", ml: "green", composite: "orange",
};

const categoryNames: Record<string, string> = {
  computer_vision: "计算机视觉", ocr: "OCR文字识别", speech: "语音",
  nlp: "自然语言处理", ml: "机器学习", composite: "复合算法",
};

export default function AlgorithmCatalogPage() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    setLoading(true);
    try { const res: any = await apiGet("/api/algorithms"); setData(res.items || []); }
    finally { setLoading(false); }
  };

  const filtered = data.filter((a: any) => {
    if (search && !a.name.toLowerCase().includes(search.toLowerCase())
        && !(a.display_name || "").includes(search)) return false;
    if (category && a.category !== category) return false;
    return true;
  });

  const columns = [
    { title: "算法名称", dataIndex: "name", key: "name",
      render: (t: string, r: any) => <Space><ApiOutlined /><span>{r.display_name || t}</span></Space> },
    { title: "类别", dataIndex: "category", key: "category",
      render: (c: string) => <Tag color={categoryColors[c] || "default"}>{categoryNames[c] || c}</Tag> },
    { title: "子类别", dataIndex: "sub_category", key: "sub_category" },
    { title: "框架", dataIndex: "framework", key: "framework", render: (f: string) => <Tag>{f}</Tag> },
    { title: "骨干网络", dataIndex: "backbone", key: "backbone", ellipsis: true },
    { title: "基准mAP", dataIndex: "benchmark_mAP", key: "benchmark_mAP",
      render: (v: number) => v ? v.toFixed(1) + "%" : "-" },
    { title: "推理速度(ms)", dataIndex: "benchmark_speed", key: "benchmark_speed",
      render: (v: number) => v ? v.toFixed(1) : "-" },
    { title: "标签", dataIndex: "tags", key: "tags",
      render: (ts: string[]) => <>{(ts||[]).map((t:string) => <Tag key={t} style={{marginBottom:2}}>{t}</Tag>)}</> },
  ];

  return (
    <AppLayout>
      <Card><Title level={4}>算法目录</Title>
        <Space style={{ marginBottom: 16 }} wrap>
          <Input placeholder="搜索算法..." prefix={<SearchOutlined />} value={search}
            onChange={e => setSearch(e.target.value)} style={{ width: 250 }} allowClear />
          <Select placeholder="筛选类别" value={category || undefined}
            onChange={v => setCategory(v || "")} allowClear style={{ width: 180 }}
            options={Object.entries(categoryNames).map(([k,v]) => ({value:k, label:v}))} />
        </Space>
        <Table dataSource={filtered} columns={columns} rowKey="id" loading={loading}
          pagination={{ pageSize: 15 }} size="small" scroll={{ x: 1000 }} />
      </Card>
    </AppLayout>
  );
}
