import { useState, useEffect } from "react";
import { Card, Table, Tag, Button, Space, Typography, Modal, Descriptions, message } from "antd";
import { PlayCircleOutlined, DeleteOutlined, EyeOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import { apiGet, apiDelete } from "../api/client";

const { Title } = Typography;
const stColor: Record<string, string> = { published: "green", offline: "red", failed: "orange" };
const stName: Record<string, string> = { published: "已发布", offline: "已下线", failed: "发布失败" };

export default function APIMarketplacePage() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [filterType, setFilterType] = useState("");

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    setLoading(true);
    try { const res: any = await apiGet("/api/platform/apis"); setData(res.items || []); }
    finally { setLoading(false); }
  };

  const handleDelete = async (id: string) => {
    await apiDelete("/api/platform/apis/" + id);
    message.success("删除成功"); fetchData();
  };

  const filtered = filterType ? data.filter((a:any) => a.api_type === filterType) : data;

  const columns = [
    { title: "API名称", dataIndex: "name", key: "name" },
    { title: "类型", dataIndex: "api_type", key: "api_type",
      render: (t:string) => <Tag>{t==="model"?"模型API":t==="orchestration"?"编排API":"自定义API"}</Tag> },
    { title: "版本", dataIndex: "version", key: "version", render: (v:string) => <Tag color="blue">{v}</Tag> },
    { title: "状态", dataIndex: "status", key: "status",
      render: (s:string) => <Tag color={stColor[s]||"default"}>{stName[s]||s}</Tag> },
    { title: "调用次数", dataIndex: "total_calls", key: "total_calls" },
    { title: "成功率", key: "rate",
      render: (_:any, r:any) => r.total_calls > 0 ? ((r.success_calls/r.total_calls)*100).toFixed(1)+"%" : "-" },
    { title: "创建时间", dataIndex: "created_at", key: "created_at",
      render: (t:string) => t ? new Date(t).toLocaleDateString() : "-" },
    { title: "操作", key: "actions",
      render: (_:any, r:any) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => { setDetail(r); setShowDetail(true); }}>详情</Button>
          <Button size="small" icon={<PlayCircleOutlined />} onClick={() => message.info("在线测试功能开发中")}>测试</Button>
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(r.id)}>删除</Button>
        </Space>
      )},
  ];

  return (
    <AppLayout>
      <Card><Title level={4}>组件市场 / API管理</Title>
        <Space style={{ marginBottom: 16 }}>
          <Button type={filterType===""?"primary":"default"} onClick={()=>setFilterType("")}>全部</Button>
          <Button type={filterType==="model"?"primary":"default"} onClick={()=>setFilterType("model")}>模型API</Button>
          <Button type={filterType==="orchestration"?"primary":"default"} onClick={()=>setFilterType("orchestration")}>编排API</Button>
          <Button type={filterType==="custom"?"primary":"default"} onClick={()=>setFilterType("custom")}>自定义API</Button>
        </Space>
        <Table dataSource={filtered} columns={columns} rowKey="id" loading={loading} size="small" />
      </Card>
      <Modal open={showDetail} onCancel={()=>setShowDetail(false)} footer={null} width={700} title="API详情">
        {detail && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="名称">{detail.name}</Descriptions.Item>
            <Descriptions.Item label="版本">{detail.version}</Descriptions.Item>
            <Descriptions.Item label="类型">{detail.api_type}</Descriptions.Item>
            <Descriptions.Item label="算法类型">{detail.algorithm_type || "-"}</Descriptions.Item>
            <Descriptions.Item label="端点" span={2}>{detail.endpoint || "-"}</Descriptions.Item>
            <Descriptions.Item label="状态"><Tag color={stColor[detail.status]}>{stName[detail.status]}</Tag></Descriptions.Item>
            <Descriptions.Item label="方法">{detail.method}</Descriptions.Item>
            <Descriptions.Item label="总调用">{detail.total_calls}</Descriptions.Item>
            <Descriptions.Item label="成功">{detail.success_calls}</Descriptions.Item>
            <Descriptions.Item label="失败">{detail.failed_calls}</Descriptions.Item>
            <Descriptions.Item label="公开">{detail.is_public ? "是" : "否"}</Descriptions.Item>
            <Descriptions.Item label="描述" span={2}>{detail.description || "-"}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </AppLayout>
  );
}
