import { useEffect, useState } from "react";
import {
  App as AntApp, Card, Table, Button, Upload, Select, Space, Modal, Tooltip, Typography, Row, Col, Tag
} from "antd";
import {
  UploadOutlined, DownloadOutlined, DeleteOutlined, EyeOutlined, ImportOutlined, ExportOutlined
} from "@ant-design/icons";
import apiClient from "../api/client";
import { getDatasetPreview, listDatasets } from "../api/datasets";
import AppLayout from "../components/AppLayout";
import { useI18n } from "../i18n";

const { Text } = Typography;

export default function DataManagePage() {
  const { message } = AntApp.useApp();
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

  const loadDatasets = (projectId: string | null) => {
    setLoading(true);
    listDatasets(projectId || undefined)
      .then(setDatasets)
      .catch(() => message.error(t.common.error))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadDatasets(selectedProject);
  }, [selectedProject]);

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
      loadDatasets(selectedProject);
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
          await apiClient.delete("/datasets/" + dsId);
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
      const data = await getDatasetPreview(dsId);
      const columns = data.columns || [];
      const rows = Array.isArray(data.preview)
        ? data.preview.map((row: Record<string, unknown>) => columns.map((column: string) => row[column]))
        : data.rows || [];
      setPreviewData({ columns, rows });
      setPreviewOpen(true);
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const handleDownload = async (dsId: string) => {
    try {
      const response = await apiClient.get("/datasets/" + dsId + "/export", { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "dataset.csv";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const handleExport = async () => {
    if (!selectedProject) return;
    try {
      const response = await apiClient.get("/projects/" + selectedProject + "/datasets/export", { responseType: "blob" });
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "datasets.zip";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      message.error(e.response?.data?.detail || t.common.error);
    }
  };

  const columns = [
    { title: t.data.filename, dataIndex: "name", key: "name", ellipsis: true },
    { title: t.data.project, dataIndex: "project_name", key: "project_name", ellipsis: true,
      render: (value: string | null) => value || "-" },
    { title: t.data.format, dataIndex: "format", key: "format", width: 80,
      render: (v: string) => <Tag>{v || "csv"}</Tag> },
    { title: t.data.size, dataIndex: "file_size", key: "size",
      render: (v: number) => v ? (v / 1024).toFixed(1) + " KB" : "-" },
    { title: t.data.rows, dataIndex: "row_count", key: "rows", width: 80 },
    { title: t.model.created, dataIndex: "created_at", key: "created_at", width: 160 },
    {
      title: t.model.actions, key: "actions", width: 132, fixed: "right" as const, align: "center" as const,
      render: (_: any, record: any) => (
        <Space className="dataset-table-actions" size={2} wrap={false}>
          <Tooltip title={`${t.data.preview} ${record.name}`}><Button type="text" size="small" icon={<EyeOutlined />} aria-label={`${t.data.preview} ${record.name}`} onClick={() => handlePreview(record.id)} /></Tooltip>
          <Tooltip title={`${t.data.download} ${record.name}`}><Button type="text" size="small" icon={<DownloadOutlined />} aria-label={`${t.data.download} ${record.name}`} onClick={() => handleDownload(record.id)} /></Tooltip>
          <Tooltip title={`${t.common.delete} ${record.name}`}><Button type="text" size="small" danger icon={<DeleteOutlined />} aria-label={`${t.common.delete} ${record.name}`} onClick={() => handleDelete(record.id)} /></Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <AppLayout>
      <div className="page-shell fade-in">
        <div className="page-header">
          <div className="page-header-copy">
            <h3 className="page-title">{t.data.title}</h3>
          </div>
          <Space className="page-actions" wrap>
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
        <Card className="table-surface" variant="borderless">
          <Table
            rowKey="id"
            dataSource={datasets}
            columns={columns}
            loading={loading}
            pagination={{ pageSize: 15 }}
            locale={{ emptyText: selectedProject ? t.common.no_data : t.common.no_data }}
            scroll={{ x: "max-content" }}
          />
        </Card>
      </div>
      <Modal
        title={t.data.preview}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={800}
      >
        {previewData && (
          <div style={{ overflowX: "auto" }}>
            <table className="dataset-preview-table" style={{ borderCollapse: "collapse", width: "100%", fontSize: 13 }}>
              <thead>
                <tr>
                  {previewData.columns.map((col: string, i: number) => (
                    <th key={i} style={{ padding: "6px 8px", textAlign: "left" }}>
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {previewData.rows.slice(0, 10).map((row: any[], ri: number) => (
                  <tr key={ri}>
                    {row.map((cell: any, ci: number) => (
                      <td key={ci} style={{ padding: "4px 8px", maxWidth: 200, overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
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
