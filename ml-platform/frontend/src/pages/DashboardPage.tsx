import { useEffect, useState } from "react";
import { Card, Row, Col, Statistic, List, Tag, Spin, Typography, Space, Button, Progress } from "antd";
import { ProjectOutlined, ApiOutlined, DatabaseOutlined, AppstoreOutlined, ThunderboltOutlined, ExperimentOutlined, TeamOutlined, TrophyOutlined, CloudUploadOutlined, PlayCircleOutlined, ArrowRightOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import AppLayout from "../components/AppLayout";
import { apiGet } from "../api/client";

const { Title, Text } = Typography;

export default function DashboardPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [dashStats, setDashStats] = useState<any>(null);
  const [projects, setProjects] = useState<any[]>([]);

  useEffect(() => {
    Promise.all([
      apiGet("/dashboard/stats").catch(() => null),
      apiGet("/projects").catch(() => null),
    ]).then(([stats, proj]) => {
      setDashStats(stats);
      setProjects((proj?.items || []).slice(0, 6));
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <AppLayout><Spin size="large" style={{ display: "block", margin: "120px auto" }} /></AppLayout>;

  const assets = dashStats?.core_assets || {};
  const modelSt = dashStats?.model_status || {};
  const totalModels = (modelSt.training || 0) + (modelSt.completed || 0) + (modelSt.published || 0);
  const completePct = totalModels > 0 ? Math.round(((modelSt.completed || 0) / totalModels) * 100) : 0;

  const statCards = [
    { title: "内置算法", value: assets.total_algorithms || 70, icon: <AppstoreOutlined />, color: "#58A6FF", bg: "rgba(88,166,255,0.1)" },
    { title: "数据集", value: assets.total_datasets || 0, icon: <DatabaseOutlined />, color: "#3FB950", bg: "rgba(63,185,80,0.1)" },
    { title: "模型总数", value: assets.total_models || 0, icon: <TrophyOutlined />, color: "#A371F7", bg: "rgba(163,113,247,0.1)" },
    { title: "API总数", value: assets.total_apis || 0, icon: <ApiOutlined />, color: "#F0883E", bg: "rgba(240,136,62,0.1)" },
  ];

  const pieOption = {
    tooltip: { trigger: "item" as const },
    series: [{ type: "pie" as const, radius: ["55%", "80%"], center: ["50%", "50%"], itemStyle: { borderRadius: 4, borderColor: "#0D1117", borderWidth: 3 }, label: { show: false },
      data: [
        { value: 25, name: "图像分类", itemStyle: { color: "#58A6FF" } },
        { value: 20, name: "目标检测", itemStyle: { color: "#3FB950" } },
        { value: 10, name: "语义分割", itemStyle: { color: "#A371F7" } },
        { value: 8, name: "OCR文本", itemStyle: { color: "#F0883E" } },
        { value: 7, name: "机器学习", itemStyle: { color: "#D29922" } },
        { value: 5, name: "语音识别", itemStyle: { color: "#F85149" } },
      ],
    }],
  };

  const barOption = {
    grid: { top: 10, right: 10, bottom: 20, left: 40 },
    xAxis: { type: "category" as const, data: ["训练中", "已完成", "已发布"], axisLabel: { color: "#8B949E" }, axisLine: { lineStyle: { color: "#30363D" } } },
    yAxis: { type: "value" as const, axisLabel: { color: "#8B949E" }, splitLine: { lineStyle: { color: "#21262D" } } },
    series: [{ type: "bar" as const, barWidth: 32,
      data: [
        { value: modelSt.training || 0, itemStyle: { color: "#D29922", borderRadius: [6, 6, 0, 0] } },
        { value: modelSt.completed || 0, itemStyle: { color: "#3FB950", borderRadius: [6, 6, 0, 0] } },
        { value: modelSt.published || 0, itemStyle: { color: "#58A6FF", borderRadius: [6, 6, 0, 0] } },
      ],
      label: { show: true, position: "top" as const, color: "#E6EDF3", fontWeight: 600 },
    }],
  };

  const algoTags = [
    { name: "图像分类", color: "#58A6FF" }, { name: "目标检测", color: "#3FB950" },
    { name: "语义分割", color: "#A371F7" }, { name: "OCR文本", color: "#F0883E" },
    { name: "机器学习", color: "#D29922" }, { name: "语音识别", color: "#F85149" },
  ];

  return (
    <AppLayout>
      <div className="page-header">
        <div>
          <Title level={3} style={{ margin: 0 }}>数据驾驶舱</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>AI模型训练编排平台 &middot; 总览面板</Text>
        </div>
        <Space>
          <Tag color="blue" style={{ borderRadius: 12, padding: "2px 12px" }}>
            <AppstoreOutlined /> {(assets.total_algorithms || 70)}+ 算法
          </Tag>
          <Button type="primary" icon={<ArrowRightOutlined />} onClick={() => navigate("/projects")}>进入项目</Button>
        </Space>
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        {statCards.map((card, i) => (
          <Col xs={12} sm={12} md={6} key={i}>
            <Card className="stat-card-accent fade-in" styles={{ body: { padding: "20px 24px" } }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <Text type="secondary" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: "0.5px" }}>{card.title}</Text>
                  <Title level={2} style={{ margin: "4px 0 0", color: card.color, fontSize: 32, fontWeight: 800 }}>
                    {typeof card.value === "number" ? card.value.toLocaleString() : card.value}
                  </Title>
                </div>
                <div style={{ width: 48, height: 48, borderRadius: 12, background: card.bg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, color: card.color }}>{card.icon}</div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} md={10}>
          <Card title={<Text strong>算法分布</Text>} styles={{ body: { padding: "12px" } }}>
            <ReactECharts option={pieOption} style={{ height: 280 }} />
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "center", marginTop: 8 }}>
              {algoTags.map((t) => <Tag key={t.name} color={t.color} style={{ fontSize: 10 }}>{t.name}</Tag>)}
            </div>
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card title={<Text strong>模型状态</Text>} styles={{ body: { padding: "12px 12px 4px" } }}>
            <ReactECharts option={barOption} style={{ height: 220 }} />
            <Space style={{ justifyContent: "center", width: "100%", marginTop: 8 }}>
              <Progress type="circle" percent={completePct} size={60} strokeColor="#3FB950" />
            </Space>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title={<Text strong>快捷操作</Text>} styles={{ body: { padding: "16px" } }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                { icon: <CloudUploadOutlined />, label: "新建数据集", path: "/data" },
                { icon: <ThunderboltOutlined />, label: "自动化建模", path: "/automl" },
                { icon: <ExperimentOutlined />, label: "模型训练", path: "/training" },
                { icon: <PlayCircleOutlined />, label: "新建项目", path: "/projects" },
              ].map((action, i) => (
                <Button key={i} block size="large" icon={action.icon} onClick={() => navigate(action.path)} style={{ height: 48, textAlign: "left" as any }}>{action.label}</Button>
              ))}
            </div>
          </Card>
        </Col>
      </Row>

      <Card
        title={<Space><ProjectOutlined style={{ color: "#58A6FF" }} /><Text strong>最近项目</Text></Space>}
        extra={<Button type="link" onClick={() => navigate("/projects")}>查看全部 &rarr;</Button>}
      >
        {projects.length > 0 ? (
          <List dataSource={projects} grid={{ gutter: 16, xs: 1, sm: 2, md: 3, lg: 3 }}
            renderItem={(item: any) => (
              <List.Item>
                <Card hoverable className="glow-border" style={{ borderRadius: 10 }} styles={{ body: { padding: "16px 18px" } }} onClick={() => navigate("/projects/" + item.id)}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{ width: 36, height: 36, borderRadius: 8, background: "linear-gradient(135deg, #F0883E, #D29922)", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 14 }}>{(item.name || "P")[0]}</div>
                    <div>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>{item.name}</div>
                      <Text type="secondary" style={{ fontSize: 11 }}>{item.description || "无描述"}</Text>
                    </div>
                  </div>
                </Card>
              </List.Item>
            )}
          />
        ) : (
          <div className="empty-state">
            <ProjectOutlined />
            <div style={{ marginBottom: 16, fontSize: 15 }}>暂无项目</div>
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => navigate("/projects")}>创建第一个项目</Button>
          </div>
        )}
      </Card>
    </AppLayout>
  );
}
