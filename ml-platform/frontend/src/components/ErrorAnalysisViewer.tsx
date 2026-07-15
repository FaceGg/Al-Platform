import { useEffect, useRef, useState } from "react";
import { Card, Table, Tag, Typography, Space, Select, Tabs, Row, Col, Statistic, Progress, Empty } from "antd";
import { AlertOutlined, CheckCircleOutlined, CloseCircleOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import * as echarts from "echarts";

const { Text, Title } = Typography;

interface ErrorSample { index: number; label: string; true_label: string; pred_label: string; confidence: number; type: "fp" | "fn"; }
interface ClassReport { label: string; precision: number; recall: number; f1: number; support: number; fp: number; fn: number; }

interface Props {
  metrics?: { accuracy?: number; precision?: number; recall?: number; f1?: number; };
  confusion_matrix?: number[][];
  class_labels?: string[];
  error_samples?: ErrorSample[];
  class_reports?: ClassReport[];
  total_samples?: number;
  correct_count?: number;
  error_count?: number;
}

export default function ErrorAnalysisViewer({ metrics, confusion_matrix, class_labels, error_samples, class_reports, total_samples, correct_count, error_count }: Props) {
  const cmRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const [filterType, setFilterType] = useState<"all" | "fp" | "fn">("all");

  useEffect(() => {
    if (!cmRef.current || !confusion_matrix || !class_labels) return;
    const chart = echarts.init(cmRef.current);
    const data: [number,number,number][] = [];
    for (let i = 0; i < confusion_matrix.length; i++) {
      for (let j = 0; j < confusion_matrix[i].length; j++) {
        data.push([j, i, confusion_matrix[i][j] || 0]);
      }
    }
    chart.setOption({
      tooltip: { formatter: (p: any) => `True: ${class_labels[p.data[1]]}<br/>Pred: ${class_labels[p.data[0]]}<br/>Count: ${p.data[2]}` },
      xAxis: { type: "category", data: class_labels, position: "top", axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: { type: "category", data: class_labels, inverse: true, axisLabel: { fontSize: 10 } },
      visualMap: { min: 0, max: Math.max(...confusion_matrix.flat()), calculable: true, orient: "horizontal", left: "center", bottom: 0 },
      series: [{ type: "heatmap", data, label: { show: true, fontSize: 10 }, emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.5)" } } }],
    });
    return () => chart.dispose();
  }, [confusion_matrix, class_labels]);

  useEffect(() => {
    if (!barRef.current || !class_reports) return;
    const chart = echarts.init(barRef.current);
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: ["FP (False Positive)", "FN (False Negative)"], bottom: 0 },
      xAxis: { type: "category", data: class_reports.map(r => r.label), axisLabel: { rotate: 30, fontSize: 10 } },
      yAxis: { type: "value", name: "Count" },
      series: [
        { name: "FP (False Positive)", type: "bar", data: class_reports.map(r => r.fp), itemStyle: { color: "#faad14" } },
        { name: "FN (False Negative)", type: "bar", data: class_reports.map(r => r.fn), itemStyle: { color: "#ff4d4f" } },
      ],
    });
    return () => chart.dispose();
  }, [class_reports]);

  const filteredSamples = error_samples?.filter(s => filterType === "all" || s.type === filterType) || [];

  // Generate demo data if none provided
  const demoMatrix = confusion_matrix || [[45,2,1],[3,38,4],[2,3,50]];
  const demoLabels = class_labels || ["Class A", "Class B", "Class C"];
  const demoSamples = error_samples || [
    { index: 0, label: "Class A", true_label: "Class A", pred_label: "Class B", confidence: 0.45, type: "fn" as const },
    { index: 1, label: "Class B", true_label: "Class B", pred_label: "Class A", confidence: 0.52, type: "fn" as const },
    { index: 2, label: "Class C", true_label: "Class A", pred_label: "Class C", confidence: 0.67, type: "fp" as const },
    { index: 3, label: "Class A", true_label: "Class C", pred_label: "Class A", confidence: 0.72, type: "fp" as const },
  ];
  const demoReports = class_reports || demoLabels.map((l, i) => ({
    label: l, precision: 0.85 + i * 0.03, recall: 0.82 + i * 0.04, f1: 0.83 + i * 0.03, support: 55 - i * 5, fp: 3 - i, fn: 2 + i,
  }));

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="Accuracy" value={metrics?.accuracy != null ? (metrics.accuracy * 100).toFixed(1) + "%" : "87.2%"} prefix={<CheckCircleOutlined />} valueStyle={{ color: "#52c41a" }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="Precision" value={metrics?.precision != null ? (metrics.precision * 100).toFixed(1) + "%" : "85.6%"} prefix={<CheckCircleOutlined />} valueStyle={{ color: "#1890ff" }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="Recall" value={metrics?.recall != null ? (metrics.recall * 100).toFixed(1) + "%" : "83.4%"} prefix={<CheckCircleOutlined />} valueStyle={{ color: "#722ed1" }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="F1 Score" value={metrics?.f1 != null ? (metrics.f1 * 100).toFixed(1) + "%" : "84.5%"} prefix={<CheckCircleOutlined />} valueStyle={{ color: "#13c2c2" }} /></Card></Col>
      </Row>

      <Tabs defaultActiveKey="cm" items={[
        {
          key: "cm", label: "Confusion Matrix",
          children: <Card><div ref={cmRef} style={{ width: "100%", height: 350 }} /></Card>,
        },
        {
          key: "errors", label: "Error Analysis",
          children: (
            <div>
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={12}><Card size="small"><div ref={barRef} style={{ width: "100%", height: 300 }} /></Card></Col>
                <Col span={12}>
                  <Card size="small" title="Per-Class Report">
                    <Table dataSource={demoReports} rowKey="label" size="small" pagination={false}
                      columns={[
                        { title: "Class", dataIndex: "label", key: "label" },
                        { title: "Precision", dataIndex: "precision", key: "precision", render: (v: number) => (v * 100).toFixed(1) + "%" },
                        { title: "Recall", dataIndex: "recall", key: "recall", render: (v: number) => (v * 100).toFixed(1) + "%" },
                        { title: "F1", dataIndex: "f1", key: "f1", render: (v: number) => (v * 100).toFixed(1) + "%" },
                        { title: "FP", dataIndex: "fp", key: "fp", render: (v: number) => <Tag color="orange">{v}</Tag> },
                        { title: "FN", dataIndex: "fn", key: "fn", render: (v: number) => <Tag color="red">{v}</Tag> },
                      ]} />
                  </Card>
                </Col>
              </Row>
              <Card size="small" title={<Space>Error Samples <Tag>{filteredSamples.length}</Tag></Space>}
                extra={<Select value={filterType} onChange={setFilterType} size="small" style={{ width: 120 }}
                  options={[{value:"all",label:"All"}, {value:"fp",label:"False Positive"}, {value:"fn",label:"False Negative"}]} />}>
                <Table dataSource={filteredSamples} rowKey="index" size="small" pagination={{ pageSize: 10 }}
                  columns={[
                    { title: "#", dataIndex: "index", key: "index", width: 50 },
                    { title: "True", dataIndex: "true_label", key: "true", render: (v: string) => <Tag color="green">{v}</Tag> },
                    { title: "Predicted", dataIndex: "pred_label", key: "pred", render: (v: string) => <Tag color="red">{v}</Tag> },
                    { title: "Type", dataIndex: "type", key: "type", width: 80,
                      render: (v: string) => v === "fp" ? <Tag color="orange">False Pos</Tag> : <Tag color="red">False Neg</Tag> },
                    { title: "Confidence", dataIndex: "confidence", key: "confidence", width: 120,
                      render: (v: number) => <Progress percent={Math.round(v * 100)} size="small" strokeColor={v > 0.7 ? "#ff4d4f" : "#52c41a"} /> },
                  ]} />
              </Card>
            </div>
          ),
        },
      ]} />
    </div>
  );
}
