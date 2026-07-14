import { useEffect, useState } from "react";
import {
  Card, Table, Button, Upload, Select, Space, message, Modal, Typography, Row, Col, Tag
} from "antd";
import {
  UploadOutlined, DownloadOutlined, DeleteOutlined, EyeOutlined, ImportOutlined, ExportOutlined
} from "@ant-design/icons";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text } = Typography;

export default function DataManagePage() {
  const { t } = useI18n();
  const [projects, setProjects] = useState<any[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [previewData, setPreviewData] = useState<{ columns: string[]; rows: any[][] } | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  useEffect(() => {
    apiClient.get("/projects").then((res) => {
      setProjects(res.data.items || res.data || []);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedProject) { setDatasets([]); return; }
    setLoading(true);
    apiClient.get("/projects/" + selectedProject + "/datasets")
      .then((res) => setDatasets(res.data.items || res.data || []))
      .catch(() => message.error(t.common.error))
      .finally(() => setLoading(false));
  }, [selectedProject, t]);

  const handleUpload = async (file: File) => {
    if (!selectedProject) { message.warning(t.automl.select_project); return false; }
    const formData = new FormData();
    formData.append("file", file);
    try {
      await apiClient.post("/projects/" + selectedProject + "/datasets/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      message.success(t.common.success);
      // reload
      apiClient.get("/projects/" + selectedProject + "/datasets")
        .then((res) => setDatasets(res.data.items || res.data || []));
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
    return false;
  };

  const handleDelete = (dsId: string) => {
    Modal.confirm({
      title: t.data.delete_file + "?",
      okType: "danger",
      cancelText: t.common.cancel,
      onOk: async () => {
        try {
          await apiClient.delete("/projects/" + selectedProject + "/datasets/" + dsId);
          message.success(t.common.success);
          setDatasets((prev) => prev.filter((d) => d.id !== dsId));
        } catch (e: any) {
          message.error(e.response?.data?.detail || t.common.error);
        }
      },
    });
  };

  const handlePreview = async (dsId: string) => {
    try {
      const res = await apiClient.get("/projects/" + selectedProject + "/datasets/" + dsId + "/preview");
      setPreviewData(res.data);
      setPreviewOpen(true);
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const handleDownload = (dsId: string) => {
    const token = localStorage.getItem("token");
    const url = "/api/projects/" + selectedProject + "/datasets/" + dsId + "/download";
    const a = document.createElement("a");
    a.href = url + "?token=" + token;
    a.click();
  };

  const handleExport = async () => {
    if (!selectedProject) return;
    try {
      await apiClient.post("/projects/" + selectedProject + "/datasets/export");
      message.success(t.common.success);
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const columns = [
    { title: t.data.filename, dataIndex: "filename", key: "filename", ellipsis: true },
    { title: t.data.format, dataIndex: "format", key: "format", width: 80,
      render: (v: string) => <Tag>{v || "csv"}</Tag> },
    { title: t.data.size, dataIndex: "size_bytes", key: "size",
      render: (v: number) => v ? (v / 1024).toFixed(1) + " KB" : "-" },
    { title: t.data.rows, dataIndex: "row_count", key: "rows", width: 80 },
    { title: t.model.created, dataIndex: "created_at", key: "created_at", width: 160 },
    {
      title: t.model.actions, key: "actions", width: 200,
      render: (_: any, record: any) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />}
            onClick={() => handlePreview(record.id)}>{t.data.preview}</Button>
          <Button type="link" size="small" icon={<DownloadOutlined />}
            onClick={() => handleDownload(record.id)}>{t.data.download}</Button>
          <Button type="link" size="small" danger icon={<DeleteOutlined />}
            onClick={() => handleDelete(record.id)}>{t.common.delete}</Button>
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16, alignItems: "center" }}>
        <h3>{t.data.title}</h3>
        <Space>
          <Select
            placeholder={t.automl.select_project}
            style={{ width: 200 }}
            value={selectedProject}
            onChange={setSelectedProject}
            options={projects.map((p: any) => ({ value: p.id, label: p.name }))}
            allowClear
          />
          <Upload beforeUpload={(file) => { handleUpload(file); return false; }} accept=".csv,.xlsx,.json,.parquet" maxCount={1} showUploadList={false}>
            <Button icon={<UploadOutlined />}>{t.data.upload_file}</Button>
          </Upload>
          <Button icon={<ExportOutlined />} onClick={handleExport}>{t.data.export}</Button>
          <Upload beforeUpload={(file) => { handleUpload(file); return false; }} accept=".csv,.xlsx" maxCount={99} showUploadList={false} multiple>
            <Button icon={<ImportOutlined />}>{t.data.batch}</Button>
          </Upload>
        </Space>
      </div>
      <Card>
        <Table
          rowKey="id"
          dataSource={datasets}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 15 }}
          locale={{ emptyText: t.automl.select_project }}
        />
      </Card>
      <Modal
        title={t.data.preview}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={800}
      >
        {previewData && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
              <thead>
                <tr>
                  {previewData.columns.map((col: string, i: number) => (
                    <th key={i} style={{ border: "1px solid #f0f0f0", padding: "6px 8px", background: "#fafafa", textAlign: "left" }}>
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewData.rows.slice(0, 10).map((row: any[], ri: number) => (
                  <tr key={ri}>
                    {row.map((cell: any, ci: number) => (
                      <td key={ci} style={{ border: "1px solid #f0f0f0", padding: "4px 8px", maxWidth: 200, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
                        {String(cell ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Modal>
    </AppLayout>
  );
}
