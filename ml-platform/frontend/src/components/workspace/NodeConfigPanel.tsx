import { Input, InputNumber, Select, Switch, Form, Divider, Button, message, Upload, Typography } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { useI18n } from "../../i18n";
import { useWorkflowStore } from "../../stores/workflowStore";
import { extractColumnsFromResult, isColumnParam } from "./CustomNode";
import { useEffect, useState, useMemo } from "react";
import apiClient from "../../api/client";

const { Text } = Typography;

function useUpstreamColumns(nodeId: string): string[] {
  const { edges, nodeResults } = useWorkflowStore();
  return useMemo(() => {
    if (!nodeId) return [];
    const incoming = edges.filter(e => e.target === nodeId);
    if (!incoming.length) return [];
    const allCols: string[] = [];
    for (const e of incoming) {
      const srcResult = nodeResults[e.source];
      if (srcResult) allCols.push(...extractColumnsFromResult(srcResult));
    }
    const selfResult = nodeResults[nodeId];
    if (selfResult) allCols.push(...extractColumnsFromResult(selfResult));
    return [...new Set(allCols)];
  }, [nodeId, edges, nodeResults]);
}

function getPortLabel(opId: string, paramName: string): string | null {
  const portMappings: Record<string, Record<string, string>> = {
    join: { left_keys: "Left Key Columns (comma-separated)", right_keys: "Right Key Columns (comma-separated)" },
    pivot: { index: "Index Column", columns: "Column Axis", values: "Values Column" },
    aggregate: { group_by: "Group By Column" },
    sort: { sort_column: "Sort Column" },
  };
  return portMappings[opId]?.[paramName] || null;
}

export default function NodeConfigPanel() {
  const { t } = useI18n();
  const { selectedNode, operators, updateNodeParams, nodeStatuses } = useWorkflowStore();
  const [params, setParams] = useState<Record<string, any>>({});
  const [uploading, setUploading] = useState(false);

  const nodeId = selectedNode?.id || "";
  const upstreamColumns = useUpstreamColumns(nodeId);

  useEffect(() => {
    if (selectedNode) setParams(selectedNode.data.params || {});
  }, [selectedNode]);

  if (!selectedNode) {
    return (
      <div style={{ padding: 16, color: "#999" }}>
        <Divider>{t.workspace.node_properties}</Divider>
        <p style={{ textAlign: "center", marginTop: 40 }}>{t.workspace.select_node_hint}</p>
      </div>
    );
  }

  const operator = operators.find((op: any) => op.id === selectedNode.data.operatorId);
  const status = nodeStatuses[selectedNode.id];

  const handleParamChange = (name: string, value: any) => {
    const newParams = { ...params, [name]: value };
    setParams(newParams);
    updateNodeParams(selectedNode.id, newParams);
  };

  const handleFileUpload = async (file: File, paramName: string) => {
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await apiClient.post("/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      handleParamChange(paramName, res.data.file_path);
      message.success("\u5df2\u4e0a\u4f20 " + file.name);
    } catch (e: any) {
      message.error(e.response?.data?.detail || "\u4e0a\u4f20\u5931\u8d25");
    } finally {
      setUploading(false);
    }
    return false;
  };

  const isCSVImport = operator?.id === "csv_import";
  const sourceValue = params["source"] || "local";

  const renderParamField = (p: any) => {
    const value = params[p.name] ?? p.default;

    if (isCSVImport && p.name === "file_path" && sourceValue !== "local") return null;
    if (isCSVImport && p.name === "url" && sourceValue !== "url") return null;

    const colName = isColumnParam(p.name);
    if (colName && upstreamColumns.length > 0 && (p.type === "str" || p.type === "select")) {
      const portLabel = getPortLabel(operator?.id, p.name) || p.label || p.name;
      return (
        <Select
          style={{ width: "100%" }}
          value={value || undefined}
          onChange={(v) => handleParamChange(p.name, v)}
          placeholder={"\u9009\u62e9" + portLabel}
          allowClear
          options={upstreamColumns.map((c) => ({ label: c, value: c }))}
        />
      );
    }

    if (p.name === "file_path" && isCSVImport) {
      return (
        <div>
          <Input
            placeholder="E:/data/welding.csv"
            value={value || ""}
            onChange={(e) => handleParamChange("file_path", e.target.value)}
            style={{ marginBottom: 4 }}
          />
          <Upload beforeUpload={(f) => handleFileUpload(f, "file_path")} showUploadList={false}>
            <Button icon={<UploadOutlined />} loading={uploading} size="small" block>
              {"\u6d4f\u89c8\u672c\u5730\u6587\u4ef6"}
            </Button>
          </Upload>
        </div>
      );
    }

    if (p.name === "url" && isCSVImport) {
      return (
        <Input
          placeholder="https://example.com/data.csv"
          value={value || ""}
          onChange={(e) => handleParamChange("url", e.target.value)}
        />
      );
    }

    // --- CSV import source selector (local vs url) ---
    if (p.name === "source" && isCSVImport) {
      return (
        <Select
          style={{ width: "100%" }}
          value={value || "local"}
          onChange={(v) => handleParamChange("source", v)}
          options={[
            { label: "\u672c\u5730\u6587\u4ef6", value: "local" },
            { label: "URL", value: "url" },
          ]}
        />
      );
    }

    switch (p.type) {
      case "int":
        return (
          <InputNumber
            style={{ width: "100%" }}
            value={value ?? p.default}
            onChange={(v) => handleParamChange(p.name, v ?? p.default)}
            min={p.range_min}
            max={p.range_max}
          />
        );
      case "float":
        return (
          <InputNumber
            style={{ width: "100%" }}
            value={value ?? p.default}
            onChange={(v) => handleParamChange(p.name, v ?? p.default)}
            step={0.01}
          />
        );
      case "boolean":
        return (
          <Switch
            checked={!!value}
            onChange={(v) => handleParamChange(p.name, v)}
          />
        );
      case "select":
        return (
          <Select
            style={{ width: "100%" }}
            value={value || undefined}
            onChange={(v) => handleParamChange(p.name, v)}
            options={(p.options || []).map((o: string) => ({ label: o, value: o }))}
          />
        );
      default:
        return (
          <Input
            value={value || ""}
            onChange={(e) => handleParamChange(p.name, e.target.value)}
          />
        );
    }
  };

  return (
    <div style={{ padding: 12, overflow: "auto", height: "100%" }}>
      <Divider plain style={{ margin: "8px 0 12px" }}>
        {selectedNode.data.label || selectedNode.data.operatorId}
      </Divider>

      {upstreamColumns.length > 0 && (
        <div style={{
          marginBottom: 10, padding: "6px 8px",
          background: "#f0f5ff", borderRadius: 6, fontSize: 11,
          color: "#1d39c4", border: "1px solid #d6e4ff",
        }}>
          {"\u8f93\u5165\u6570\u636e\u5217: " + upstreamColumns.slice(0, 8).join(", ")}
          {upstreamColumns.length > 8 && " ...\u7b49" + upstreamColumns.length + "\u5217"}
        </div>
      )}

      <h4 style={{ marginBottom: 8, fontSize: 13, fontWeight: 600 }}>
        {t.workspace.params_config}
      </h4>
      {operator?.parameters?.length > 0 ? (
        <Form layout="vertical" size="small">
          {operator.parameters.map((p: any) => {
            const field = renderParamField(p);
            if (!field) return null;
            return (
              <Form.Item
                key={p.name}
                label={<span style={{ fontSize: 12 }}>{p.label || p.name}</span>}
                style={{ marginBottom: 12 }}
              >
                {field}
              </Form.Item>
            );
          })}
        </Form>
      ) : (
        <p style={{ color: "#999", fontSize: 12 }}>{t.workspace.no_params}</p>
      )}

      {/* Execution status only - NO result preview */}
      {status && (
        <>
          <Divider plain style={{ margin: "12px 0" }}>
            {t.workspace.execution_status}
          </Divider>
          <div style={{
            fontSize: 13, padding: "6px 10px", borderRadius: 6,
            background:
              status === "completed" ? "#f6ffed" :
              status === "running" ? "#e6f7ff" :
              status === "failed" ? "#fff2f0" : "#fafafa",
          }}>
            {t.workspace.status}{" "}
            <span style={{
              fontWeight: 600,
              color:
                status === "completed" ? "#52c41a" :
                status === "running" ? "#1890ff" :
                status === "failed" ? "#ff4d4f" : "#999",
            }}>
              {status === "completed" ? "\u6210\u529f" :
               status === "running" ? "\u8fd0\u884c\u4e2d" :
               status === "failed" ? "\u5931\u8d25" : "\u5f85\u8fd0\u884c"}
            </span>
          </div>
        </>
      )}
    </div>
  );
}