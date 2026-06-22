import { useEffect, useState } from "react";
import {
  Card, Select, Button, InputNumber, Input, Typography, message, Table, Row, Col, Spin, Tag
} from "antd";
import { ThunderboltOutlined, TrophyOutlined } from "@ant-design/icons";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text, Title } = Typography;

export default function AutoMLPage() {
  const { t } = useI18n();
  const [projects, setProjects] = useState<any[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<any[]>([]);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [targetColumn, setTargetColumn] = useState("");
  const [taskType, setTaskType] = useState("classification");
  const [timeBudget, setTimeBudget] = useState(60);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<any>(null);
  const [runId, setRunId] = useState<string | null>(null);

  useEffect(() => {
    apiClient.get("/projects").then((res) => {
      setProjects(res.data.items || res.data || []);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedProject) { setDatasets([]); return; }
    apiClient.get("/projects/" + selectedProject + "/datasets")
      .then((res) => setDatasets(res.data.items || res.data || []))
      .catch(() => {});
  }, [selectedProject]);

  const handleRun = async () => {
    if (!selectedProject || !selectedDataset || !targetColumn) {
      message.warning(t.automl.select_project + " / " + t.automl.select_dataset + " / " + t.automl.target);
      return;
    }
    setRunning(true);
    setResults(null);
    try {
      const res = await apiClient.post("/automl/run", {
        project_id: selectedProject,
        dataset_id: selectedDataset,
        target_column: targetColumn,
        task_type: taskType,
        time_budget: timeBudget,
      });
      const rid = res.data.run_id || res.data.id;
      setRunId(rid);
      // Poll for results
      const poll = setInterval(async () => {
        try {
          const r = await apiClient.get("/automl/runs/" + rid);
          const d = r.data;
          if (d.status === "completed" || d.status === "done" || d.best_model) {
            clearInterval(poll);
            setResults(d);
            setRunning(false);
            message.success(t.common.success);
          } else if (d.status === "failed") {
            clearInterval(poll);
            setRunning(false);
            message.error(t.common.error);
          }
        } catch { /* continue polling */ }
      }, 3000);
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
      setRunning(false);
    }
  };

  const allResults = results?.models || results?.all_results || [];
  const bestModel = results?.best_model || allResults[0];
  const features = results?.feature_importance || results?.features || {};

  const resultColumns = [
    { title: t.knowledge.name, dataIndex: "name", key: "name" },
    { title: t.automl.score, dataIndex: "score", key: "score",
      render: (v: number) => v != null ? Number(v).toFixed(4) : "-" },
    { title: "Task", dataIndex: "task_type", key: "task" },
    { title: "Time", dataIndex: "training_time", key: "time",
      render: (v: number) => v != null ? v.toFixed(1) + "s" : "-" },
  ];

  const featureEntries = Object.entries(features).sort((a: any, b: any) => b[1] - a[1]);
  const maxImp = featureEntries.length > 0 ? (featureEntries[0][1] as number) : 1;

  return (
    <AppLayout>
      <h3>{t.automl.title}</h3>
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col xs={24} sm={6}>
            <Text strong>{t.automl.select_project}</Text>
            <Select
              style={{ width: "100%", marginTop: 4 }}
              placeholder={t.automl.select_project}
              value={selectedProject}
              onChange={setSelectedProject}
              options={projects.map((p: any) => ({ value: p.id, label: p.name }))}
            />
          </Col>
          <Col xs={24} sm={6}>
            <Text strong>{t.automl.select_dataset}</Text>
            <Select
              style={{ width: "100%", marginTop: 4 }}
              placeholder={t.automl.select_dataset}
              value={selectedDataset}
              onChange={setSelectedDataset}
              options={datasets.map((d: any) => ({ value: d.id, label: d.filename || d.name }))}
            />
          </Col>
          <Col xs={24} sm={4}>
            <Text strong>{t.automl.target}</Text>
            <Input
              style={{ marginTop: 4 }}
              placeholder={t.automl.target}
              value={targetColumn}
              onChange={(e) => setTargetColumn(e.target.value)}
            />
          </Col>
          <Col xs={24} sm={4}>
            <Text strong>{t.automl.task}</Text>
            <Select
              style={{ width: "100%", marginTop: 4 }}
              value={taskType}
              onChange={setTaskType}
              options={[
                { value: "classification", label: "Classification" },
                { value: "regression", label: "Regression" },
              ]}
            />
          </Col>
          <Col xs={24} sm={2}>
            <Text strong>{t.automl.budget}</Text>
            <InputNumber
              style={{ width: "100%", marginTop: 4 }}
              min={10} max={3600}
              value={timeBudget}
              onChange={(v) => setTimeBudget(v ?? 60)}
            />
          </Col>
          <Col xs={24} sm={2}>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={handleRun}
              loading={running}
              block
              style={{ marginTop: 22 }}
            >
              {t.automl.run}
            </Button>
          </Col>
        </Row>
      </Card>

      {running && (
        <Card style={{ textAlign: "center", padding: 40 }}>
          <Spin size="large" />
          <p style={{ marginTop: 16 }}>{t.common.loading}</p>
        </Card>
      )}

      {results && (
        <>
          {bestModel && (
            <Card style={{ marginBottom: 16 }}>
              <Row gutter={16}>
                <Col span={12}>
                  <div style={{ textAlign: "center", padding: 24 }}>
                    <TrophyOutlined style={{ fontSize: 48, color: "#faad14" }} />
                    <Title level={4}>{t.automl.best_model}: {bestModel.name}</Title>
                    <Title level={3} style={{ color: "#52c41a" }}>
                      {t.automl.score}: {bestModel.score != null ? Number(bestModel.score).toFixed(4) : "-"}
                    </Title>
                  </div>
                </Col>
                <Col span={12}>
                  <Text strong>{t.automl.all_results}</Text>
                  <Table
                    rowKey="name"
                    dataSource={allResults}
                    columns={resultColumns}
                    size="small"
                    pagination={false}
                    style={{ marginTop: 8 }}
                  />
                </Col>
              </Row>
            </Card>
          )}
          {featureEntries.length > 0 && (
            <Card title={t.operator.feature_importance} style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 600 }}>
                {featureEntries.map(([name, imp]: [string, any]) => (
                  <div key={name} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Text style={{ width: 160, textAlign: "right", fontSize: 12 }} ellipsis>{name}</Text>
                    <div style={{ flex: 1, background: "#f0f0f0", borderRadius: 4, height: 20, overflow: "hidden" }}>
                      <div style={{
                        width: Math.max(((imp as number) / maxImp) * 100, 2) + "%",
                        height: "100%",
                        background: "linear-gradient(90deg, #1890ff, #52c41a)",
                        borderRadius: 4,
                        transition: "width 0.5s",
                      }} />
                    </div>
                    <Text style={{ width: 60, fontSize: 12 }}>{(imp as number).toFixed(4)}</Text>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </AppLayout>
  );
}
