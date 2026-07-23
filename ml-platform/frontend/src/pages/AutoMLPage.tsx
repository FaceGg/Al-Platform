import { useEffect, useState, useRef } from "react";
import { App as AntApp, Card, Select, Button, Input, InputNumber, Typography, Table, Row, Col, Spin, Tag, Tabs, Modal, Form } from "antd";
import { ThunderboltOutlined, TrophyOutlined, BarChartOutlined, RadarChartOutlined } from "@ant-design/icons";
import * as echarts from "echarts";
import apiClient from "../api/client";
import { getDatasetPreview, listDatasets } from "../api/datasets";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text, Title } = Typography;

export default function AutoMLPage() {
  const { t } = useI18n();
  const { message } = AntApp.useApp();
  const [projects, setProjects] = useState<any[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [experiments, setExperiments] = useState<any[]>([]);
  const [selectedExperiment, setSelectedExperiment] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<any[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [datasetColumns, setDatasetColumns] = useState<string[]>([]);
  const [targetColumn, setTargetColumn] = useState("");
  const [taskType, setTaskType] = useState("classification");
  const [timeBudget, setTimeBudget] = useState(60);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [activeTab, setActiveTab] = useState("results");
  const [experimentModalOpen, setExperimentModalOpen] = useState(false);
  const [experimentCreating, setExperimentCreating] = useState(false);
  const [experimentForm] = Form.useForm();
  const barRef = useRef<HTMLDivElement>(null);
  const radarRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    apiClient.get("/projects").then((res) => setProjects(res.data.items || res.data || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedProject) {
      setDatasets([]); setSelectedDataset(null);
      setExperiments([]); setSelectedExperiment(null);
      return;
    }
    listDatasets(selectedProject).then(setDatasets).catch(() => setDatasets([]));
    apiClient.get("/experiments", { params: { project_id: selectedProject } })
      .then((res) => {
        const items = res.data.items || [];
        setExperiments(items);
        setSelectedExperiment(items[0]?.id || null);
      })
      .catch(() => { setExperiments([]); setSelectedExperiment(null); });
  }, [selectedProject]);

  useEffect(() => {
    if (!selectedDataset) { setDatasetColumns([]); setTargetColumn(""); return; }
    getDatasetPreview(selectedDataset)
      .then((data) => {
        const columns = Array.isArray(data.columns) ? data.columns : [];
        setDatasetColumns(columns);
        setTargetColumn((current) => columns.includes(current) ? current : "");
      })
      .catch(() => { setDatasetColumns([]); message.error(t.common.error); });
  }, [selectedDataset, t.common.error, message]);

  const allResults = results?.models || results?.all_results || [];
  const bestModel = results?.best_model || allResults[0];
  const features = results?.feature_importance || results?.features || {};

  useEffect(() => {
    if (!results || allResults.length === 0) return;

    // Bar chart
    if (barRef.current) {
      const chart = echarts.init(barRef.current);
      const names = allResults.map((r: any) => r.name || r.model || "Unknown");
      const scores = allResults.map((r: any) => r.score != null ? Number(r.score) : 0);
      chart.setOption({
        title: { text: t.automl?.all_results || "Model Comparison", left: "center", textStyle: { fontSize: 14 } },
        tooltip: { trigger: "axis" },
        xAxis: { type: "category", data: names, axisLabel: { rotate: 30 } },
        yAxis: { type: "value", name: t.automl?.score || "Score" },
        series: [{
          type: "bar", data: scores.map((v: number, i: number) => ({
            value: v,
            itemStyle: { color: names[i] === (bestModel?.name || bestModel?.model) ? "#52c41a" : "#1890ff" }
          })),
          label: { show: true, position: "top", formatter: (p: any) => p.value.toFixed(4) }
        }],
        grid: { top: 40, bottom: 60 },
      });
      setTimeout(() => chart.resize(), 100);
      return () => chart.dispose();
    }
  }, [results]);

  // Radar chart
  useEffect(() => {
    if (!results || allResults.length < 2) return;
    if (radarRef.current) {
      const chart = echarts.init(radarRef.current);
      const modelNames = allResults.map((r: any) => r.name || r.model || "Unknown");
      const maxScore = Math.max(...allResults.map((r: any) => r.score || 0));
      chart.setOption({
        title: { text: "Model Radar", left: "center", textStyle: { fontSize: 14 } },
        tooltip: {},
        legend: { data: modelNames, bottom: 0 },
        radar: {
          indicator: [
            { name: "Accuracy", max: maxScore || 1 },
            { name: "Precision", max: maxScore || 1 },
            { name: "Recall", max: maxScore || 1 },
            { name: "F1", max: maxScore || 1 },
            { name: "AUC", max: maxScore || 1 },
          ],
        },
        series: [{
          type: "radar",
          data: allResults.map((r: any) => ({
            name: r.name || r.model || "Unknown",
            value: Array(5).fill(Number(r.score || 0)),
          })),
        }],
      });
      setTimeout(() => chart.resize(), 100);
      return () => chart.dispose();
    }
  }, [results]);

  const handleRun = async () => {
    if (!selectedProject || !selectedExperiment || !selectedDataset || !targetColumn) {
      message.warning((t.automl?.select_project || "Project") + " / " + (t.automl?.select_dataset || "Dataset") + " / " + (t.automl?.target || "Target"));
      return;
    }
    setRunning(true);
    setResults(null);
    try {
      const res = await apiClient.post("/training/automl/run", {
        project_id: selectedProject, experiment_id: selectedExperiment,
        dataset_artifact_id: selectedDataset, target_column: targetColumn,
        task: taskType, time_budget: timeBudget,
      });
      const rid = res.data.run_id || res.data.id || res.data.job_id;
      const poll = setInterval(async () => {
        try {
          const r = await apiClient.get("/training/jobs/" + rid);
          const d = r.data;
          if (d.status === "completed" || d.status === "done") {
            clearInterval(poll); setResults(d.metrics || d); setRunning(false); message.success(t.common.success);
          } else if (d.status === "failed") {
            clearInterval(poll); setRunning(false); message.error(t.common.error);
          }
        } catch { /* continue */ }
      }, 3000);
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
      setRunning(false);
    }
  };

  const createExperiment = async (values: { name: string; description?: string }) => {
    if (!selectedProject) return;
    setExperimentCreating(true);
    try {
      const response = await apiClient.post("/experiments", {
        project_id: selectedProject,
        name: values.name,
        description: values.description || "",
      });
      const experiment = response.data;
      setExperiments((items) => [experiment, ...items]);
      setSelectedExperiment(experiment.id);
      experimentForm.resetFields();
      setExperimentModalOpen(false);
      message.success(t.common.success);
    } catch (error: any) {
      message.error(error.response?.data?.detail?.message || error.response?.data?.detail || t.common.error);
    } finally {
      setExperimentCreating(false);
    }
  };

  const resultColumns = [
    { title: t.knowledge?.name || "Name", dataIndex: "name", key: "name" },
    { title: t.automl?.score || "Score", dataIndex: "score", key: "score", render: (v: number) => v != null ? Number(v).toFixed(4) : "-" },
    { title: "Task", dataIndex: "task_type", key: "task" },
    { title: "Time", dataIndex: "training_time", key: "time", render: (v: number) => v != null ? v.toFixed(1) + "s" : "-" },
  ];

  const featureEntries = Object.entries(features).sort((a: any, b: any) => b[1] - a[1]);
  const maxImp = featureEntries.length > 0 ? (featureEntries[0][1] as number) : 1;

  return (
    <AppLayout>
      <h3>{t.automl?.title || "AutoML"}</h3>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col xs={24} sm={6}><Text strong>{t.automl?.select_project || "Project"}</Text>
            <Select style={{ width: "100%", marginTop: 4 }} placeholder={t.automl?.select_project} value={selectedProject} onChange={setSelectedProject}
              options={projects.map((p: any) => ({ value: p.id, label: p.name }))} /></Col>
          <Col xs={24} sm={6}><Text strong>{t.automl?.select_dataset || "Dataset"}</Text>
            <Select style={{ width: "100%", marginTop: 4 }} placeholder={t.automl?.select_dataset} value={selectedDataset} onChange={setSelectedDataset}
              options={datasets.map((d: any) => ({ value: d.id, label: d.name || d.filename }))} /></Col>
          <Col xs={24} sm={4}><Text strong>{t.training?.experiments || "Experiment"}</Text>
            <Select style={{ width: "100%", marginTop: 4 }} value={selectedExperiment || undefined} onChange={setSelectedExperiment}
              disabled={!selectedProject} placeholder={t.training?.experiments || "Experiment"}
              options={experiments.map((item: any) => ({ value: item.id, label: item.name }))} />
            <Button type="link" size="small" style={{ padding: 0, marginTop: 3 }} disabled={!selectedProject}
              onClick={() => setExperimentModalOpen(true)}>
              {t.training?.new_experiment || "New Experiment"}
            </Button>
          </Col>
          <Col xs={24} sm={4}><Text strong>{t.automl?.target || "Target"}</Text>
            <Select style={{ width: "100%", marginTop: 4 }} placeholder={t.automl?.target} value={targetColumn || undefined} onChange={setTargetColumn}
              disabled={!selectedDataset} options={datasetColumns.map((column) => ({ value: column, label: column }))} /></Col>
          <Col xs={24} sm={4}><Text strong>{t.automl?.task || "Task"}</Text>
            <Select style={{ width: "100%", marginTop: 4 }} value={taskType} onChange={setTaskType}
              options={[{ value: "classification", label: "Classification" }, { value: "regression", label: "Regression" }]} /></Col>
          <Col xs={24} sm={2}><Text strong>{t.automl?.budget || "Budget"}</Text>
            <InputNumber style={{ width: "100%", marginTop: 4 }} min={10} max={3600} value={timeBudget} onChange={(v) => setTimeBudget(v ?? 60)} /></Col>
          <Col xs={24} sm={2}><Button type="primary" icon={<ThunderboltOutlined />} onClick={handleRun} loading={running} block style={{ marginTop: 22 }}>{t.automl?.run || "Run"}</Button></Col>
        </Row>
      </Card>

      {running && <Card style={{ textAlign: "center", padding: 40 }}><Spin size="large" /><p style={{ marginTop: 16 }}>{t.common.loading}</p></Card>}

      {results && (
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          { key: "results", label: "Results",
            children: (<>
              {bestModel && (
                <Card style={{ marginBottom: 16 }}>
                  <Row gutter={16}>
                    <Col span={12}>
                      <div style={{ textAlign: "center", padding: 24 }}>
                        <TrophyOutlined style={{ fontSize: 48, color: "#faad14" }} />
                        <Title level={4}>Best: {bestModel.name || bestModel.model}</Title>
                        <Title level={3} style={{ color: "#52c41a" }}>Score: {bestModel.score != null ? Number(bestModel.score).toFixed(4) : "-"}</Title>
                      </div>
                    </Col>
                    <Col span={12}>
                      <Text strong>{t.automl?.all_results || "All Results"}</Text>
                      <Table rowKey="name" dataSource={allResults} columns={resultColumns} size="small" pagination={false} style={{ marginTop: 8 }} />
                    </Col>
                  </Row>
                </Card>
              )}
              {featureEntries.length > 0 && (
                <Card title={<><BarChartOutlined /> Feature Importance</>} style={{ marginBottom: 16 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 600 }}>
                    {featureEntries.map(([name, imp]: [string, any]) => (
                      <div key={name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <Text style={{ width: 160, textAlign: "right", fontSize: 12 }} ellipsis>{name}</Text>
                        <div style={{ flex: 1, background: "#f0f0f0", borderRadius: 4, height: 20, overflow: "hidden" }}>
                          <div style={{ width: Math.max(((imp as number) / maxImp) * 100, 2) + "%", height: "100%", background: "linear-gradient(90deg, #1890ff, #52c41a)", borderRadius: 4 }} /></div>
                        <Text style={{ width: 60, fontSize: 12 }}>{(imp as number).toFixed(4)}</Text>
                      </div>))}
                  </div>
                </Card>
              )}
            </>),
          },
          { key: "compare", label: "Compare",
            children: (
              <Row gutter={16}>
                <Col span={12}><Card><div ref={barRef} style={{ width: "100%", height: 350 }} /></Card></Col>
                <Col span={12}><Card><div ref={radarRef} style={{ width: "100%", height: 350 }} /></Card></Col>
              </Row>
            ),
          },
        ]} />
      )}
      <Modal
        title={t.training?.new_experiment || "New Experiment"}
        open={experimentModalOpen}
        onCancel={() => setExperimentModalOpen(false)}
        onOk={() => experimentForm.submit()}
        confirmLoading={experimentCreating}
      >
        <Form form={experimentForm} layout="vertical" onFinish={createExperiment}>
          <Form.Item name="name" label={t.training?.experiment_name || "Experiment Name"} rules={[{ required: true }]}>
            <Input autoFocus />
          </Form.Item>
          <Form.Item name="description" label={t.training?.description || "Description"}>
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </AppLayout>
  );
}
