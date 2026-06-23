import { useEffect, useState } from "react";
import { Card, Row, Col, Statistic, List, Tag, Spin, Typography, Space, Button, Progress } from "antd";
import {
  ProjectOutlined, ApiOutlined, DatabaseOutlined, AppstoreOutlined,
  ThunderboltOutlined, ExperimentOutlined, TeamOutlined, TrophyOutlined,
  CloudUploadOutlined, SettingOutlined, PlayCircleOutlined
} from "@ant-design/icons";
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
  const [recent, setRecent] = useState<any>(null);

  useEffect(() => {
    Promise.all([
      apiGet("/dashboard/stats").catch(() => null),
      apiGet("/projects").catch(() => null),
      apiGet("/dashboard/recent-activity").catch(() => null),
    ]).then(([stats, proj, act]) => {
      setDashStats(stats);
      setProjects(proj?.items || []);
      setRecent(act);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <AppLayout><Spin size="large" style={{ display:"block", margin:"100px auto" }} /></AppLayout>;

  const assets = dashStats?.core_assets || {};
  const biz = dashStats?.business_stats || {};
  const modelSt = dashStats?.model_status || {};
  const algoCov = dashStats?.algorithm_coverage || [];

  // Algorithm coverage pie chart
  const pieOption = {
    tooltip: { trigger: "item" },
    legend: { bottom: 0 },
    series: [{
      type: "pie", radius: ["40%", "70%"], center: ["50%", "45%"],
      data: algoCov.map((a: any) => ({ name: a.category, value: a.count })),
      label: { formatter: "{b}\n{d}%" },
    }],
  };

  // Model status bar chart
  const barOption = {
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: ["训练中", "已完成", "已发布"] },
    yAxis: { type: "value" },
    series: [{
      type: "bar", data: [modelSt.training||0, modelSt.completed||0, modelSt.published||0],
      itemStyle: { color: (p:any) => ["#faad14","#52c41a","#1890ff"][p.dataIndex] },
    }],
  };

  const quickActions = [
    { icon: <CloudUploadOutlined />, label: "新建数据集", path: "/data" },
    { icon: <ThunderboltOutlined />, label: "自动化建模", path: "/automl" },
    { icon: <ExperimentOutlined />, label: "模型训练", path: "/training" },
    { icon: <ApiOutlined />, label: "API管理", path: "/api-marketplace" },
    { icon: <SettingOutlined />, label: "计算资源", path: "/compute" },
    { icon: <PlayCircleOutlined />, label: "新建项目", path: "/projects" },
  ];

  return (
    <AppLayout>
      <Title level={4} style={{ marginBottom: 16 }}>数据驾驶舱</Title>

      {/* Row 1: Core Asset Stats */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8} md={4}>
          <Card><Statistic title="内置算法" value={assets.total_algorithms || 0} prefix={<AppstoreOutlined />} valueStyle={{ color: "#1890ff" }} /></Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card><Statistic title="数据集" value={assets.total_datasets || 0} prefix={<DatabaseOutlined />} valueStyle={{ color: "#52c41a" }} /></Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card><Statistic title="模型总数" value={assets.total_models || 0} prefix={<TrophyOutlined />} valueStyle={{ color: "#722ed1" }} /></Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card><Statistic title="API总数" value={assets.total_apis || 0} prefix={<ApiOutlined />} valueStyle={{ color: "#fa8c16" }} /></Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card><Statistic title="样本总量" value={assets.total_samples || 0} prefix={<DatabaseOutlined />} valueStyle={{ color: "#eb2f96" }} /></Card>
        </Col>
        <Col xs={12} sm={8} md={4}>
          <Card><Statistic title="API调用" value={biz.total_api_calls || 0} prefix={<ApiOutlined />} valueStyle={{ color: "#13c2c2" }} /></Card>
        </Col>
      </Row>

      {/* Row 2: Business stats */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={8} sm={4}>
          <Card><Statistic title="项目数" value={biz.total_projects || 0} prefix={<ProjectOutlined />} /></Card>
        </Col>
        <Col xs={8} sm={4}>
          <Card><Statistic title="用户数" value={biz.total_users || 0} prefix={<TeamOutlined />} /></Card>
        </Col>
        <Col xs={8} sm={4}>
          <Card><Statistic title="训练任务" value={biz.total_training_jobs || 0} prefix={<ExperimentOutlined />} /></Card>
        </Col>
        <Col xs={8} sm={4}>
          <Card><Statistic title="成功率" value={biz.total_api_calls > 0 ? ((biz.successful_api_calls/biz.total_api_calls)*100).toFixed(1) : 0} suffix="%" prefix={<PlayCircleOutlined />} valueStyle={{ color: "#52c41a" }} /></Card>
        </Col>
        <Col xs={16} sm={8}>
          <Card title="模型状态分布" size="small">
            <Space>
              <Tag color="gold">训练中: {modelSt.training||0}</Tag>
              <Tag color="green">已完成: {modelSt.completed||0}</Tag>
              <Tag color="blue">已发布: {modelSt.published||0}</Tag>
            </Space>
            <Progress percent={modelSt.completed > 0 ? Math.round((modelSt.completed/((modelSt.training||0)+(modelSt.completed||0)+(modelSt.published||0)||1))*100) : 0} size="small" />
          </Card>
        </Col>
      </Row>

      {/* Row 3: Charts */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} md={12}>
          <Card title="算法覆盖分布" size="small">
            {algoCov.length > 0 ? <ReactECharts option={pieOption} style={{ height: 260 }} /> : <Text type="secondary">暂无数据</Text>}
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="模型状态统计" size="small">
            <ReactECharts option={barOption} style={{ height: 260 }} />
          </Card>
        </Col>
      </Row>

      {/* Row 4: Quick Actions + Recent */}
      <Row gutter={[16, 16]}>
        <Col xs={24} md={10}>
          <Card title="快捷功能" size="small">
            <Row gutter={[8, 8]}>
              {quickActions.map((a, i) => (
                <Col span={8} key={i}>
                  <Button block icon={a.icon} onClick={() => navigate(a.path)} style={{ height: 52 }}>
                    {a.label}
                  </Button>
                </Col>
              ))}
            </Row>
          </Card>
        </Col>
        <Col xs={24} md={14}>
          <Card title="最近项目" size="small">
            <List
              dataSource={projects.slice(0, 5)}
              renderItem={(item: any) => (
                <List.Item actions={[<a onClick={() => navigate("/projects/" + item.id)}>进入</a>]}>
                  <List.Item.Meta title={item.name} description={item.description || "无描述"} />
                </List.Item>
              )}
              locale={{ emptyText: "暂无项目" }}
            />
          </Card>
        </Col>
      </Row>
    </AppLayout>
  );
}
