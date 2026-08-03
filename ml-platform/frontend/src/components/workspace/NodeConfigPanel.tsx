import { Input, InputNumber, Select, Switch, Form, Divider, Button, Drawer, message, Upload, Typography } from "antd";
import { DownloadOutlined, MinusCircleOutlined, PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { useI18n } from "../../i18n";
import { downloadDatasetArtifact, listDatasets } from "../../api/datasets";
import { useWorkflowStore } from "../../stores/workflowStore";
import { extractColumnsFromResult, isColumnParam } from "./CustomNode";
import { useEffect, useState, useMemo } from "react";
import apiClient from "../../api/client";
import { isWorkflowExportOperator } from "./workflowExport";

const { Text } = Typography;

const RESULT_JSON_LIMIT = 5000;
const RESULT_TABLE_LIMIT = 20;

type ResultRecord = Record<string, any>;
type DatasetArtifactOption = {
  id?: string;
  artifact_id?: string;
  name?: string;
  filename?: string;
  format?: string;
  row_count?: number;
};
function isResultRecord(value: unknown): value is ResultRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function formatBoundedResultJson(value: unknown, maxLength = RESULT_JSON_LIMIT): string {
  const seen = new WeakSet<object>();
  let serialized: string;
  try {
    serialized = JSON.stringify(value, (_key, nested) => {
      if (nested && typeof nested === "object") {
        if (seen.has(nested)) return "[Circular]";
        seen.add(nested);
      }
      return nested;
    }, 2) ?? String(value);
  } catch {
    serialized = String(value);
  }
  return serialized.length > maxLength ? `${serialized.slice(0, maxLength)}...` : serialized;
}

function chartImageSource(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) {
    const trimmed = value.trim();
    return trimmed.startsWith("data:image/")
      ? trimmed
      : `data:image/png;base64,${trimmed}`;
  }
  if (isResultRecord(value)) {
    const base64 = value.base64 ?? value.data ?? value.content;
    if (typeof base64 === "string" && base64.trim()) {
      const mime = String(value.mime_type ?? value.mimeType ?? "image/png");
      return base64.startsWith("data:image/") ? base64 : `data:${mime};base64,${base64}`;
    }
  }
  return null;
}

function resultRows(value: unknown): Array<ResultRecord> | null {
  const source = isResultRecord(value) && Array.isArray(value.data) ? value.data : value;
  if (!Array.isArray(source)) return null;
  if (source.length === 0) return [];
  if (source.every((row) => isResultRecord(row))) return source as Array<ResultRecord>;
  if (source.every((row) => Array.isArray(row))) {
    return source.map((row) => Object.fromEntries((row as unknown[]).map((cell, index) => [`column_${index + 1}`, cell])));
  }
  return source.map((row, index) => ({ index, value: row }));
}

function isChartOutput(name: string, value: unknown): boolean {
  return name.toLowerCase().includes("chart") && chartImageSource(value) !== null;
}

function renderResultCell(value: unknown): string {
  if (value == null) return "-";
  if (typeof value === "object") return formatBoundedResultJson(value, 400);
  return String(value);
}

function ResultTable({ value }: { value: unknown }) {
  const rows = resultRows(value);
  if (!rows) return null;
  const visibleRows = rows.slice(0, RESULT_TABLE_LIMIT);
  const columns = [...new Set(visibleRows.flatMap((row) => Object.keys(row)))];
  return (
    <div className="node-result-panel__table-wrap" data-testid="node-result-table">
      {columns.length ? (
        <table className="node-result-panel__table">
          <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
          <tbody>
            {visibleRows.map((row, rowIndex) => (
              <tr key={rowIndex}>{columns.map((column) => <td key={column}>{renderResultCell(row[column])}</td>)}</tr>
            ))}
          </tbody>
        </table>
      ) : (
        <span className="node-result-panel__empty">No rows</span>
      )}
      {rows.length > RESULT_TABLE_LIMIT && (
        <span className="node-result-panel__limit">Showing first {RESULT_TABLE_LIMIT} rows of {rows.length}</span>
      )}
    </div>
  );
}

export function NodeResultPanel() {
  const { lang } = useI18n();
  const resultPanelNodeId = useWorkflowStore((state) => state.resultPanelNodeId);
  const closeNodeResult = useWorkflowStore((state) => state.closeNodeResult);
  const node = useWorkflowStore((state) => state.nodes.find((candidate) => candidate.id === state.resultPanelNodeId));
  const result = useWorkflowStore((state) => resultPanelNodeId ? state.nodeResults[resultPanelNodeId] : undefined);

  if (!resultPanelNodeId || !node) return null;

  const labels = lang === "zh"
    ? { title: "可视化结果", outputs: "输出", metrics: "指标", logs: "日志", empty: "暂无结果" }
    : { title: "Visualization result", outputs: "Outputs", metrics: "Metrics", logs: "Logs", empty: "No results" };
  const resultObject = isResultRecord(result) ? result : { value: result };
  const outputs = isResultRecord(resultObject.outputs) ? resultObject.outputs : resultObject;
  const outputEntries = Object.entries(outputs).filter(([name]) => !["outputs", "metrics", "logs"].includes(name));
  const metrics = isResultRecord(resultObject.metrics) ? resultObject.metrics : {};
  const logs = Array.isArray(resultObject.logs) ? resultObject.logs : [];
  const operatorLabel = node.data?.label || node.data?.operatorId || node.id;

  return (
    <Drawer
      title={`${labels.title}: ${operatorLabel}`}
      open
      onClose={closeNodeResult}
      width={560}
      destroyOnClose
    >
      <div className="node-result-panel" data-testid="node-result-panel">
        <section className="node-result-panel__section">
          <h3>{labels.outputs}</h3>
          {outputEntries.length === 0 ? <p className="node-result-panel__empty">{labels.empty}</p> : outputEntries.map(([name, value]) => {
            const image = isChartOutput(name, value) ? chartImageSource(value) : null;
            const rows = resultRows(value);
            return (
              <div className="node-result-panel__output" key={name}>
                <h4>{name}</h4>
                {image ? (
                  <img className="node-result-panel__chart" data-testid="node-result-chart" src={image} alt={name} />
                ) : rows ? (
                  <ResultTable value={value} />
                ) : (
                  <pre className="node-result-panel__json" data-testid="node-result-json">
                    {formatBoundedResultJson(value)}
                  </pre>
                )}
              </div>
            );
          })}
        </section>

        <section className="node-result-panel__section" data-testid="node-result-metrics">
          <h3>{labels.metrics}</h3>
          {Object.keys(metrics).length === 0 ? <p className="node-result-panel__empty">{labels.empty}</p> : (
            <dl className="node-result-panel__metrics">
              {Object.entries(metrics).map(([name, value]) => (
                <div key={name}><dt>{name}</dt><dd>{renderResultCell(value)}</dd></div>
              ))}
            </dl>
          )}
        </section>

        <section className="node-result-panel__section" data-testid="node-result-logs">
          <h3>{labels.logs}</h3>
          {logs.length === 0 ? <p className="node-result-panel__empty">{labels.empty}</p> : logs.map((entry, index) => (
            <pre className="node-result-panel__log" key={index}>
              {typeof entry === "string" ? entry : entry?.message ? String(entry.message) : formatBoundedResultJson(entry, 1000)}
            </pre>
          ))}
        </section>
      </div>
    </Drawer>
  );
}

type JoinKeyPair = { left: string; right: string };

function isParamRequired(
  param: any,
  params: Record<string, any>,
  parameterSpecs: any[] = [],
): boolean {
  if (!param?.required) return false;
  const conditions = param.required_when as Record<string, string | string[]> | undefined;
  if (!conditions) return true;
  return Object.entries(conditions).every(([name, expected]) => {
    const allowed = Array.isArray(expected) ? expected : [expected];
    const controller = parameterSpecs.find((spec) => spec.name === name);
    return allowed.includes(params[name] ?? controller?.default);
  });
}

function parseJoinKeyPairs(leftValue: unknown, rightValue: unknown): JoinKeyPair[] {
  const leftKeys = String(leftValue || "").split(",").map((key) => key.trim());
  const rightKeys = String(rightValue || "").split(",").map((key) => key.trim());
  const count = Math.max(leftKeys.length, rightKeys.length, 1);
  return Array.from({ length: count }, (_, index) => ({
    left: leftKeys[index] || "",
    right: rightKeys[index] || "",
  }));
}

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

export function getPortLabel(opId: string, paramName: string, lang: "zh" | "en"): string | null {
  const portMappings: Record<string, Record<string, { zh: string; en: string }>> = {
    join: {
      left_keys: { zh: "左侧键列（逗号分隔）", en: "Left Key Columns (comma-separated)" },
      right_keys: { zh: "右侧键列（逗号分隔）", en: "Right Key Columns (comma-separated)" },
    },
    pivot: {
      index: { zh: "索引列", en: "Index Column" },
      columns: { zh: "列轴", en: "Column Axis" },
      values: { zh: "值列", en: "Values Column" },
    },
    aggregate: { group_by: { zh: "分组列", en: "Group By Column" } },
    sort: { sort_column: { zh: "排序列", en: "Sort Column" } },
  };
  return portMappings[opId]?.[paramName]?.[lang] || null;
}

function compatibleDatasetFormats(operatorId?: string): string[] {
  if (operatorId === "csv_import") return ["csv", "xls", "xlsx"];
  return [];
}

function isCompatibleDatasetArtifact(operatorId: string | undefined, dataset: DatasetArtifactOption): boolean {
  const supported = compatibleDatasetFormats(operatorId);
  if (!supported.length) return false;
  const format = String(dataset.format || dataset.name?.split(".").pop() || dataset.filename?.split(".").pop() || "").toLowerCase();
  return supported.includes(format);
}

export default function NodeConfigPanel({ projectId }: { projectId?: string }) {
  const { t, lang } = useI18n();
  const {
    selectedNode,
    operators,
    updateNodeParams,
    nodeStatuses,
    edges,
    nodeResults,
  } = useWorkflowStore();
  const [params, setParams] = useState<Record<string, any>>({});
  const [uploading, setUploading] = useState(false);
  const [datasetArtifacts, setDatasetArtifacts] = useState<DatasetArtifactOption[]>([]);
  const [loadingDatasetArtifacts, setLoadingDatasetArtifacts] = useState(false);
  const [downloadingExport, setDownloadingExport] = useState(false);

  const nodeId = selectedNode?.id || "";
  const operator = operators.find((op: any) => op.id === selectedNode?.data?.operatorId);
  const upstreamColumns = useUpstreamColumns(nodeId);
  const joinPairs = useMemo(
    () => parseJoinKeyPairs(params.left_keys, params.right_keys),
    [params.left_keys, params.right_keys],
  );
  const joinColumnsBySide = useMemo(() => {
    const columns: Record<"left" | "right", string[]> = { left: [], right: [] };
    edges
      .filter((edge) => edge.target === nodeId)
      .forEach((edge, index) => {
        const side = edge.targetHandle?.startsWith("right")
          ? "right"
          : edge.targetHandle?.startsWith("left") || index === 0
            ? "left"
            : "right";
        columns[side].push(...extractColumnsFromResult(nodeResults[edge.source]));
      });
    return {
      left: [...new Set(columns.left.length ? columns.left : upstreamColumns)],
      right: [...new Set(columns.right.length ? columns.right : upstreamColumns)],
    };
  }, [edges, nodeId, nodeResults, upstreamColumns]);

  useEffect(() => {
    if (selectedNode) setParams(selectedNode.data.params || {});
  }, [selectedNode]);

  useEffect(() => {
    const supportsArtifactDataset = Boolean(
      projectId
      && operator?.parameters?.some((param: any) => param.name === "dataset_artifact_id"),
    );
    if (!supportsArtifactDataset) {
      setDatasetArtifacts([]);
      setLoadingDatasetArtifacts(false);
      return;
    }
    let active = true;
    setLoadingDatasetArtifacts(true);
    listDatasets(projectId)
      .then((items) => {
        if (!active) return;
        setDatasetArtifacts((items as DatasetArtifactOption[]).filter((item) => (
          isCompatibleDatasetArtifact(operator?.id, item)
        )));
      })
      .catch(() => { if (active) setDatasetArtifacts([]); })
      .finally(() => { if (active) setLoadingDatasetArtifacts(false); });
    return () => { active = false; };
  }, [projectId, operator?.id, operator?.parameters]);

  if (!selectedNode) {
    return (
      <div className="node-config-panel node-config-panel--empty">
        <Divider>{t.workspace.node_properties}</Divider>
        <p>{t.workspace.select_node_hint}</p>
      </div>
    );
  }

  const status = nodeStatuses[selectedNode.id];
  const isExportOperator = isWorkflowExportOperator(operator?.id);
  const exportArtifacts = Array.isArray(nodeResults[selectedNode.id]?.artifacts)
    ? nodeResults[selectedNode.id].artifacts
    : [];
  const exportArtifact = exportArtifacts.find((artifact: any) => artifact?.artifact_id);
  const isJoinKeyRequired = (name: string) => isParamRequired(
    operator?.parameters?.find((param: any) => param.name === name),
    params,
    operator?.parameters,
  );

  const handleParamChange = (name: string, value: any) => {
    const newParams = { ...params, [name]: value };
    setParams(newParams);
    updateNodeParams(selectedNode.id, newParams);
  };

  const handleJoinPairsChange = (pairs: JoinKeyPair[]) => {
    const newParams = {
      ...params,
      left_keys: pairs.map((pair) => pair.left.trim()).join(","),
      right_keys: pairs.map((pair) => pair.right.trim()).join(","),
    };
    setParams(newParams);
    updateNodeParams(selectedNode.id, newParams);
  };

  const handleJoinPairChange = (index: number, side: "left" | "right", value: string) => {
    const nextPairs = joinPairs.map((pair, pairIndex) => (
      pairIndex === index ? { ...pair, [side]: value } : pair
    ));
    handleJoinPairsChange(nextPairs);
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

  const handleExportDownload = async () => {
    if (!exportArtifact?.artifact_id) return;
    setDownloadingExport(true);
    try {
      await downloadDatasetArtifact(
        String(exportArtifact.artifact_id),
        String(exportArtifact.name || `${operator?.id || "dataset"}.csv`),
      );
    } catch (error: any) {
      message.error(error?.response?.data?.detail || (lang === "zh" ? "下载失败" : "Download failed"));
    } finally {
      setDownloadingExport(false);
    }
  };

  const isCSVImport = operator?.id === "csv_import";
  const sourceValue = params["source"] || "local";

  const renderParamField = (p: any) => {
    const value = params[p.name] ?? p.default;

    if (isCSVImport && p.name === "file_path" && sourceValue !== "local") return null;
    if (isCSVImport && p.name === "dataset_artifact_id" && sourceValue !== "artifact") return null;
    if (isCSVImport && p.name === "url" && sourceValue !== "url") return null;

    if (operator?.id === "join" && (p.name === "left_keys" || p.name === "right_keys")) return null;
    if (isExportOperator && p.name === "file_path") return null;

    const colName = isColumnParam(p.name);
    if (colName && upstreamColumns.length > 0 && (p.type === "str" || p.type === "select")) {
      const portLabel = getPortLabel(operator?.id, p.name, lang) || p.label || p.name;
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

    if (p.type === "file") {
      return (
        <div>
          <Input
            placeholder={isCSVImport ? "E:/data/welding.csv" : undefined}
            value={value || ""}
            onChange={(e) => handleParamChange(p.name, e.target.value)}
            style={{ marginBottom: 4 }}
          />
          <Upload beforeUpload={(f) => handleFileUpload(f, p.name)} showUploadList={false}>
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

    if (p.name === "dataset_artifact_id" && isCSVImport) {
      return (
        <Select
          aria-label={lang === "zh" ? "数据集制品" : "Dataset artifact"}
          style={{ width: "100%" }}
          value={value || undefined}
          onChange={(artifactId) => handleParamChange(p.name, artifactId)}
          placeholder={lang === "zh" ? "选择兼容的数据集制品" : "Select a compatible dataset artifact"}
          loading={loadingDatasetArtifacts}
          disabled={!projectId}
          allowClear
          options={datasetArtifacts.map((dataset) => {
            const artifactId = dataset.artifact_id || dataset.id || "";
            return {
              value: artifactId,
              label: dataset.row_count == null
                ? (dataset.name || dataset.filename || artifactId)
                : `${dataset.name || dataset.filename || artifactId} · ${dataset.row_count} 行`,
            };
          })}
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
            { label: "\u6570\u636e\u96c6\u5236\u54c1", value: "artifact" },
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
        if (isExportOperator && p.name === "format" && Array.isArray(p.options) && p.options.length === 1) {
          return <Input disabled value={String(value ?? p.options[0])} />;
        }
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
    <div className="node-config-panel">
      <Divider plain className="node-config-panel__title">
        {selectedNode.data.label || selectedNode.data.operatorId}
      </Divider>

      {upstreamColumns.length > 0 && (
        <div className="node-config-panel__data-hint">
          {"\u8f93\u5165\u6570\u636e\u5217: " + upstreamColumns.slice(0, 8).join(", ")}
          {upstreamColumns.length > 8 && " ...\u7b49" + upstreamColumns.length + "\u5217"}
        </div>
      )}

      <h4 className="node-config-panel__section-title">
        {t.workspace.params_config}
      </h4>
      {operator?.parameters?.length > 0 ? (
        <Form className="node-config-panel__form" layout="vertical" size="small">
          {operator?.id === "join" && (
            <div className="node-config-panel__join-keys">
              <div className="node-config-panel__join-keys-header">
                <Text strong>{lang === "zh" ? "键列匹配" : "Key column matching"}</Text>
                <Button
                  type="dashed"
                  size="small"
                  icon={<PlusOutlined />}
                  aria-label={lang === "zh" ? "添加键对" : "Add key pair"}
                  onClick={() => handleJoinPairsChange([...joinPairs, { left: "", right: "" }])}
                >
                  {lang === "zh" ? "添加键对" : "Add key pair"}
                </Button>
              </div>
              {joinPairs.map((pair, index) => {
                const leftOptions = joinColumnsBySide.left.map((column) => ({ label: column, value: column }));
                const rightOptions = joinColumnsBySide.right.map((column) => ({ label: column, value: column }));
                return (
                  <div className="node-config-panel__join-key-row" key={`join-key-${index}`}>
                    <span className="node-config-panel__join-key-index">{index + 1}</span>
                    <div className="node-config-panel__join-key-field">
                      <Text>
                        {lang === "zh" ? "左侧键列" : "Left key column"}
                        {isJoinKeyRequired("left_keys") && (
                          <span className="node-config-panel__required" data-testid="required-param-left_keys" aria-label="required">*</span>
                        )}
                      </Text>
                      {leftOptions.length > 0 ? (
                        <Select
                          showSearch
                          allowClear
                          aria-label={lang === "zh" ? "左侧键列" : "Left key column"}
                          style={{ width: "100%" }}
                          value={pair.left || undefined}
                          onChange={(value) => handleJoinPairChange(index, "left", value || "")}
                          placeholder={lang === "zh" ? "选择左侧键列" : "Select left key column"}
                          options={leftOptions}
                        />
                      ) : (
                        <Input
                          aria-label={lang === "zh" ? "左侧键列" : "Left key column"}
                          value={pair.left}
                          onChange={(event) => handleJoinPairChange(index, "left", event.target.value)}
                          placeholder={lang === "zh" ? "输入左侧键列" : "Enter left key column"}
                        />
                      )}
                    </div>
                    <div className="node-config-panel__join-key-field">
                      <Text>
                        {lang === "zh" ? "右侧键列" : "Right key column"}
                        {isJoinKeyRequired("right_keys") && (
                          <span className="node-config-panel__required" data-testid="required-param-right_keys" aria-label="required">*</span>
                        )}
                      </Text>
                      {rightOptions.length > 0 ? (
                        <Select
                          showSearch
                          allowClear
                          aria-label={lang === "zh" ? "右侧键列" : "Right key column"}
                          style={{ width: "100%" }}
                          value={pair.right || undefined}
                          onChange={(value) => handleJoinPairChange(index, "right", value || "")}
                          placeholder={lang === "zh" ? "选择右侧键列" : "Select right key column"}
                          options={rightOptions}
                        />
                      ) : (
                        <Input
                          aria-label={lang === "zh" ? "右侧键列" : "Right key column"}
                          value={pair.right}
                          onChange={(event) => handleJoinPairChange(index, "right", event.target.value)}
                          placeholder={lang === "zh" ? "输入右侧键列" : "Enter right key column"}
                        />
                      )}
                    </div>
                    <Button
                      type="text"
                      danger
                      icon={<MinusCircleOutlined />}
                      aria-label={lang === "zh" ? `删除第${index + 1}组键对` : `Remove key pair ${index + 1}`}
                      title={lang === "zh" ? "删除键对" : "Remove key pair"}
                      onClick={() => handleJoinPairsChange(
                        joinPairs.length > 1
                          ? joinPairs.filter((_, pairIndex) => pairIndex !== index)
                          : [{ left: "", right: "" }],
                      )}
                    />
                  </div>
                );
              })}
            </div>
          )}
          {operator.parameters.map((p: any) => {
            const field = renderParamField(p);
            if (!field) return null;
            const required = isParamRequired(p, params, operator?.parameters);
            return (
              <Form.Item
                key={p.name}
                label={<span style={{ fontSize: 12 }}>{p.name === "dataset_artifact_id"
                  ? (lang === "zh" ? "数据集制品" : "Dataset artifact")
                  : (p.label || p.name)}{required && (
                  <span className="node-config-panel__required" data-testid={`required-param-${p.name}`} aria-label="required">*</span>
                )}</span>}
                style={{ marginBottom: 12 }}
              >
                {field}
              </Form.Item>
            );
          })}
        </Form>
      ) : (
        <p className="node-config-panel__empty-copy">{t.workspace.no_params}</p>
      )}

      {/* Execution status only - NO result preview */}
      {status && (
        <>
          <Divider plain style={{ margin: "12px 0" }}>
            {t.workspace.execution_status}
          </Divider>
          <div className={`node-config-panel__status node-config-panel__status--${status}`}>
            {t.workspace.status}{" "}
            <span>
              {status === "completed" ? "\u6210\u529f" :
               status === "running" ? "\u8fd0\u884c\u4e2d" :
               status === "failed" ? "\u5931\u8d25" : "\u5f85\u8fd0\u884c"}
            </span>
          </div>
          {isExportOperator && status === "completed" && exportArtifact && (
            <Button
              block
              icon={<DownloadOutlined />}
              loading={downloadingExport}
              onClick={handleExportDownload}
              aria-label={lang === "zh" ? "下载导出文件" : "Download exported file"}
              style={{ marginTop: 10 }}
            >
              {lang === "zh" ? "下载" : "Download"}
            </Button>
          )}
        </>
      )}
    </div>
  );
}
