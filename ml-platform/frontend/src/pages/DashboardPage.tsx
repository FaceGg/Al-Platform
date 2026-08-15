import { useEffect, useState } from "react";
import { Card, Row, Col, List, Tag, Spin, Typography, Space, Button, Progress } from "antd";
import {
  ProjectOutlined, ApiOutlined, DatabaseOutlined, AppstoreOutlined, ThunderboltOutlined,
  ExperimentOutlined, TrophyOutlined, CloudUploadOutlined, PlayCircleOutlined, ArrowRightOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import AppLayout from "../components/AppLayout";
import { apiGet } from "../api/client";
import { useI18n } from "../i18n";
import { useTheme } from "../stores/themeContext";

const { Title, Text } = Typography;

export default function DashboardPage() {
  const navigate = useNavigate();
  const { lang } = useI18n();
  const { theme } = useTheme();
  const text = lang === "zh" ? {
    title: "数据驾驶舱", subtitle: "智擎 · 总览面板",
    algorithms: "内置算子", datasets: "数据集", models: "模型总数", apis: "API 总数",
    enterProjects: "进入项目", algorithmDistribution: "算子分布", modelStatus: "模型状态",
    quickActions: "快捷操作", newDataset: "新建数据集", automl: "自动化建模",
    training: "模型训练", newProject: "新建项目", recentProjects: "最近项目",
    viewAll: "查看全部", noDescription: "无描述", noProjects: "暂无项目", createFirst: "创建第一个项目",
    trainingState: "训练中", completedState: "已完成", publishedState: "已发布",
  } : {
    title: "Data Cockpit", subtitle: "智擎 · Overview",
    algorithms: "Built-in Operators", datasets: "Datasets", models: "Models", apis: "APIs",
    enterProjects: "Open Projects", algorithmDistribution: "Operator Distribution", modelStatus: "Model Status",
    quickActions: "Quick Actions", newDataset: "New Dataset", automl: "AutoML",
    training: "Model Training", newProject: "New Project", recentProjects: "Recent Projects",
    viewAll: "View All", noDescription: "No description", noProjects: "No projects", createFirst: "Create First Project",
    trainingState: "Training", completedState: "Completed", publishedState: "Published",
  };

  const visual = theme === "dark" ? {
    accent: "#2F9BF5",
    accentSoft: "rgba(47, 155, 245, 0.14)",
    success: "#47C3A0",
    successSoft: "rgba(71, 195, 160, 0.14)",
    teal: "#49B8C6",
    tealSoft: "rgba(73, 184, 198, 0.14)",
    warning: "#D9AC52",
    warningSoft: "rgba(217, 172, 82, 0.14)",
    error: "#E66F75",
    muted: "#9BB2BF",
    text: "#EDF6FA",
    line: "rgba(147, 190, 207, 0.18)",
    chartSurface: "#10222C",
  } : {
    accent: "#187FD4",
    accentSoft: "rgba(24, 127, 212, 0.12)",
    success: "#15866E",
    successSoft: "rgba(21, 134, 110, 0.12)",
    teal: "#257D8B",
    tealSoft: "rgba(37, 125, 139, 0.12)",
    warning: "#A66C12",
    warningSoft: "rgba(166, 108, 18, 0.12)",
    error: "#C9535A",
    muted: "#57707B",
    text: "#142A33",
    line: "rgba(45, 102, 119, 0.18)",
    chartSurface: "#FFFFFF",
  };

  const [loading, setLoading] = useState(true);
  const [dashStats, setDashStats] = useState<any>(null);
  const [projects, setProjects] = useState<any[]>([]);

  useEffect(() => {
    const loadDashboard = () => Promise.all([
      apiGet("/dashboard/stats").catch(() => null),
      apiGet("/projects").catch(() => null),
    ]).then(([stats, proj]) => {
      setDashStats(stats);
      setProjects((proj?.items || []).slice(0, 6));
    }).finally(() => setLoading(false));
    loadDashboard();
    const timer = window.setInterval(loadDashboard, 15000);
    return () => window.clearInterval(timer);
  }, []);

  if (loading) {
    return <AppLayout><Spin size="large" style={{ display: "block", margin: "120px auto" }} /></AppLayout>;
  }

  const assets = dashStats?.core_assets || {};
  const modelSt = dashStats?.model_status || {};
  const totalModels = (modelSt.training || 0) + (modelSt.completed || 0) + (modelSt.published || 0);
  const completePct = totalModels > 0 ? Math.round(((modelSt.completed || 0) / totalModels) * 100) : 0;

  const statCards = [
    { title: text.algorithms, value: assets.total_algorithms ?? 0, icon: <AppstoreOutlined />, color: visual.accent, bg: visual.accentSoft },
    { title: text.datasets, value: assets.total_datasets ?? 0, icon: <DatabaseOutlined />, color: visual.success, bg: visual.successSoft },
    { title: text.models, value: assets.total_models ?? 0, icon: <TrophyOutlined />, color: visual.teal, bg: visual.tealSoft },
    { title: text.apis, value: assets.total_apis ?? 0, icon: <ApiOutlined />, color: visual.warning, bg: visual.warningSoft },
  ];

  const categoryNames: Record<string, { zh: string; en: string }> = {
    data_io: { zh: "数据 IO", en: "Data I/O" }, processing: { zh: "数据处理", en: "Processing" },
    blending: { zh: "数据融合", en: "Blending" }, ml: { zh: "传统机器学习", en: "Machine Learning" },
    dl: { zh: "深度学习", en: "Deep Learning" }, evaluation: { zh: "模型评估", en: "Evaluation" },
    visualization: { zh: "可视化", en: "Visualization" }, control: { zh: "流程控制", en: "Control Flow" },
    mechanism: { zh: "机理模型", en: "Mechanism" }, optimization: { zh: "参数优化", en: "Optimization" },
    utility: { zh: "工具", en: "Utilities" },
  };
  const coverageColors = [visual.accent, visual.success, visual.teal, visual.warning, "#638EDC", visual.error, "#5AAFD1", "#7DBD9C"];
  const coverage = (dashStats?.algorithm_coverage || []).map((item: any, index: number) => ({
    name: categoryNames[item.category]?.[lang] || item.category,
    value: item.count || 0,
    color: coverageColors[index % coverageColors.length],
  }));

  const pieOption = {
    tooltip: { trigger: "item" as const },
    series: [{
      type: "pie" as const,
      radius: ["54%", "78%"],
      center: ["50%", "50%"],
      itemStyle: { borderRadius: 10, borderColor: visual.chartSurface, borderWidth: 4 },
      label: { show: false },
      data: coverage.map((item: any) => ({ value: item.value, name: item.name, itemStyle: { color: item.color } })),
    }],
  };

  const barOption = {
    grid: { top: 14, right: 12, bottom: 24, left: 40 },
    xAxis: {
      type: "category" as const,
      data: [text.trainingState, text.completedState, text.publishedState],
      axisLabel: { color: visual.muted },
      axisLine: { lineStyle: { color: visual.line } },
    },
    yAxis: {
      type: "value" as const,
      axisLabel: { color: visual.muted },
      splitLine: { lineStyle: { color: visual.line } },
    },
    series: [{
      type: "bar" as const,
      barWidth: 32,
      data: [
        { value: modelSt.training || 0, itemStyle: { color: visual.warning, borderRadius: [10, 10, 3, 3] } },
        { value: modelSt.completed || 0, itemStyle: { color: visual.success, borderRadius: [10, 10, 3, 3] } },
        { value: modelSt.published || 0, itemStyle: { color: visual.accent, borderRadius: [10, 10, 3, 3] } },
      ],
      label: { show: true, position: "top" as const, color: visual.text, fontWeight: 700 },
    }],
  };

  return (
    <AppLayout>
      <div className="page-header">
        <div>
          <Title level={3} style={{ margin: 0 }}>{text.title}</Title>
          <Text type="secondary" style={{ fontSize: 13 }}>{text.subtitle}</Text>
        </div>
        <Space>
          <Tag color="blue" style={{ padding: "3px 12px" }}>
            <AppstoreOutlined /> {assets.total_algorithms ?? 0} {text.algorithms}
          </Tag>
          <Button type="primary" icon={<ArrowRightOutlined />} onClick={() => navigate("/projects")}>
            {text.enterProjects}
          </Button>
        </Space>
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        {statCards.map((card) => (
          <Col xs={12} sm={12} md={6} key={card.title}>
            <Card className="stat-card-accent fade-in" styles={{ body: { padding: "20px 22px" } }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                <div>
                  <Text type="secondary" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    {card.title}
                  </Text>
                  <Title level={2} style={{ margin: "4px 0 0", color: card.color, fontSize: 32, fontWeight: 800 }}>
                    {typeof card.value === "number" ? card.value.toLocaleString() : card.value}
                  </Title>
                </div>
                <div style={{
                  width: 48, height: 48, borderRadius: 16, background: card.bg, display: "flex",
                  alignItems: "center", justifyContent: "center", fontSize: 22, color: card.color, flexShrink: 0,
                }}>
                  {card.icon}
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} md={10}>
          <Card title={<Text strong>{text.algorithmDistribution}</Text>} styles={{ body: { padding: "14px" } }}>
            <ReactECharts option={pieOption} style={{ height: 280 }} />
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "center", marginTop: 8 }}>
              {coverage.map((item: any) => <Tag key={item.name} color={item.color} style={{ fontSize: 10 }}>{item.name}</Tag>)}
            </div>
          </Card>
        </Col>
        <Col xs={24} md={6}>
          <Card title={<Text strong>{text.modelStatus}</Text>} styles={{ body: { padding: "14px 14px 6px" } }}>
            <ReactECharts option={barOption} style={{ height: 220 }} />
            <Space style={{ justifyContent: "center", width: "100%", marginTop: 8 }}>
              <Progress type="circle" percent={completePct} size={60} strokeColor={visual.success} />
            </Space>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card title={<Text strong>{text.quickActions}</Text>} styles={{ body: { padding: "16px" } }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {[
                { icon: <CloudUploadOutlined />, label: text.newDataset, path: "/data" },
                { icon: <ThunderboltOutlined />, label: text.automl, path: "/automl" },
                { icon: <ExperimentOutlined />, label: text.training, path: "/training" },
                { icon: <PlayCircleOutlined />, label: text.newProject, path: "/projects" },
              ].map((action) => (
                <Button key={action.path} block size="large" icon={action.icon} onClick={() => navigate(action.path)} style={{ height: 48, textAlign: "left" as any }}>
                  {action.label}
                </Button>
              ))}
            </div>
          </Card>
        </Col>
      </Row>

      <Card
        title={<Space><ProjectOutlined style={{ color: visual.accent }} /><Text strong>{text.recentProjects}</Text></Space>}
        extra={<Button type="link" onClick={() => navigate("/projects")}>{text.viewAll} &rarr;</Button>}
      >
        {projects.length > 0 ? (
          <List
            dataSource={projects}
            grid={{ gutter: 16, xs: 1, sm: 2, md: 3, lg: 3 }}
            renderItem={(item: any) => (
              <List.Item>
                <Card hoverable className="glow-border" styles={{ body: { padding: "16px 18px" } }} onClick={() => navigate("/projects/" + item.id)}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{
                      width: 38, height: 38, borderRadius: 13, background: visual.accentSoft, display: "flex",
                      alignItems: "center", justifyContent: "center", color: visual.accent, fontWeight: 800, fontSize: 14,
                    }}>
                      {(item.name || "P")[0]}
                    </div>
                    <div>
                      <div style={{ fontWeight: 650, fontSize: 14 }}>{item.name}</div>
                      <Text type="secondary" style={{ fontSize: 11 }}>{item.description || text.noDescription}</Text>
                    </div>
                  </div>
                </Card>
              </List.Item>
            )}
          />
        ) : (
          <div className="empty-state">
            <ProjectOutlined />
            <div style={{ marginBottom: 16, fontSize: 15 }}>{text.noProjects}</div>
            <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => navigate("/projects")}>{text.createFirst}</Button>
          </div>
        )}
      </Card>
    </AppLayout>
  );
}
