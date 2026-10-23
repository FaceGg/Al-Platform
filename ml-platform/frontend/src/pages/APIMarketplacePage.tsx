import { useState, useEffect, useRef } from "react";
import { Alert, Card, Table, Tag, Button, Space, Typography, Modal, Descriptions, message, Select, Input, Form, Row, Col, Statistic } from "antd";
import { PlayCircleOutlined, EyeOutlined, SendOutlined, CopyOutlined, PlusOutlined, EditOutlined, KeyOutlined, PauseCircleOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient, { apiGet, apiPost, apiPut, apiDelete, formatApiError } from "../api/client";
import { useI18n } from "../i18n";
import { notifyDashboardStatsChanged } from "../events/dashboardStats";
import DeleteConfirmation from "../components/DeleteConfirmation";

const { Title, Text } = Typography;
const { TextArea } = Input;
const stColor: Record<string, string> = { published: "green", offline: "red", failed: "orange" };

// [key, zh, en] response-field reference per API type.
const RESPONSE_FIELD_DOCS: Record<string, Array<[string, string, string]>> = {
  model: [
    ["runtime_key", "推理运行时路由键", "Inference runtime routing key"],
    ["deployment_id", "部署 ID", "Deployment ID"],
    ["revision_id", "部署修订 ID（当前服务的模型版本修订）", "Deployment revision ID"],
    ["model_version_id", "模型版本 ID", "Model version ID"],
    ["version_number", "模型版本号", "Model version number"],
    ["predictions", "预测结果数组（与输入 records 一一对应）", "Prediction array (one per input record)"],
    ["duration_ms", "推理耗时（毫秒）", "Inference duration (ms)"],
    ["probabilities", "各类别概率（分类模型才返回）", "Class probabilities (classification models)"],
  ],
  orchestration: [
    ["api_id", "API 条目 ID", "API entry ID"],
    ["workflow_version", "实际执行的工作流版本", "Workflow version served"],
    ["output_node", "输出节点 ID（拓扑序最后节点）", "Output node ID (last node)"],
    ["branch", "记录命中的条件分支（true/false，无条件节点为 null）", "Condition branch taken (null if none)"],
    ["records", "输出节点的输出行（内容取决于服务图最后一个算子）", "Output rows of the final node"],
    ["invoked_at", "服务端处理时间（UTC）", "Server processing time (UTC)"],
  ],
  chat: [
    ["api_id", "API 条目 ID", "API entry ID"],
    ["reply", "模型回答（[n] 对应 sources 序号）", "Model answer ([n] cites sources)"],
    ["sources", "引用来源（命中的知识库片段）", "Citations (matched KB chunks)"],
    ["kb", "绑定的知识库", "Bound knowledge base"],
    ["kb_warning", "检索未命中等提示", "Retrieval warning"],
    ["usage", "token 用量（prompt 输入 / completion 输出）", "Token usage"],
    ["invoked_at", "服务端处理时间（UTC）", "Server processing time (UTC)"],
  ],
};

export default function APIMarketplacePage() {
  const { t, lang } = useI18n();
  const tr = t.api_market || {};
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [data, setData] = useState<any[]>([]);
  const [stats, setStats] = useState({ total_apis: 0, published: 0, offline: 0, failed: 0, total_calls: 0 });
  const [detail, setDetail] = useState<any>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [showTest, setShowTest] = useState(false);
  const [testApi, setTestApi] = useState<any>(null);
  const [filterType, setFilterType] = useState("");
  const [testMethod, setTestMethod] = useState("POST");
  const [testUrl, setTestUrl] = useState("/api/");
  const [testBody, setTestBody] = useState('{\n  \n}');
  const [testHeaders, setTestHeaders] = useState('{"Content-Type":"application/json"}');
  const [testResponse, setTestResponse] = useState<any>(null);
  const [testLoading, setTestLoading] = useState(false);
  const [useToken, setUseToken] = useState(false);
  const [testHistory, setTestHistory] = useState<Array<{time:string; method:string; url:string; status:number; body:any}>>([]);
  const [showEditor, setShowEditor] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [form] = Form.useForm();

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    setLoading(true);
    setLoadError("");
    try {
      const [res, summary]: any[] = await Promise.all([
        apiGet("/platform/apis"),
        apiGet("/platform/apis/stats"),
      ]);
      setData(res.items || []);
      setStats({
        total_apis: Number(summary.total_apis || 0),
        published: Number(summary.published || 0),
        offline: Number(summary.offline || 0),
        failed: Number(summary.failed || 0),
        total_calls: Number(summary.total_calls || 0),
      });
    }
    catch (error) {
      setData([]);
      setLoadError(formatApiError(error, "API list loading failed"));
    }
    finally { setLoading(false); }
  };

  const handleDelete = async (id: string) => {
    try {
      await apiDelete("/platform/apis/" + id);
      notifyDashboardStatsChanged();
      message.success(t.common?.success || "Deleted"); fetchData();
    } catch (error) { message.error(formatApiError(error, "Delete failed")); }
  };

  const toggleOnline = async (api: any, online: boolean) => {
    try {
      const res: any = await apiPost(`/platform/apis/${api.id}/${online ? "online" : "offline"}`);
      notifyDashboardStatsChanged();
      message.success(t.common?.success || "OK");
      if (res?.status) {
        setData(prev => prev.map((a: any) => (a.id === api.id ? { ...a, status: res.status } : a)));
      }
    } catch (error) { message.error(formatApiError(error, "Status change failed")); }
  };

  const openEditor = (api?: any) => {
    setEditing(api || null);
    form.setFieldsValue(api ? { ...api } : { api_type: "custom", method: "POST", version: "v1", endpoint: "/api/" });
    setShowEditor(true);
  };

  const handleSave = async (values: any) => {
    try {
      if (editing) {
        await apiPut("/platform/apis/" + editing.id, {
          name: values.name,
          endpoint: values.endpoint,
          description: values.description || "",
        });
      } else {
        await apiPost("/platform/apis", {
          name: values.name,
          api_type: "custom",
          source_kind: "custom",
          endpoint: values.endpoint,
          method: values.method || "POST",
          version: values.version || "v1",
          description: values.description || "",
        });
      }
      setShowEditor(false); form.resetFields(); await fetchData(); notifyDashboardStatsChanged();
      message.success(t.common?.success || "Saved");
    } catch (error) { message.error(formatApiError(error, "Save failed")); }
  };

  const buildExampleBody = (api: any) => {
    let body: any = undefined;
    if (api.api_type === "chat") {
      body = { message: lang === "zh" ? "点焊飞溅的主要原因有哪些？" : "What causes weld spatter?", top_k: 4 };
    } else if (api.api_type === "orchestration") {
      const sample = api.request_schema?.record;
      body = { record: sample && typeof sample === "object" && !Array.isArray(sample) ? sample : { feature1: 0, feature2: 0 } };
    } else if (api.api_type === "model") {
      const feats = Array.isArray(api.request_schema?.records) ? api.request_schema.records : [];
      // Feature entries may be plain names or {name, dtype} schema dicts.
      const names = feats
        .map((f: any) => (f && typeof f === "object" ? f.name : f))
        .filter(Boolean);
      body = { records: [Object.fromEntries(names.map((n: string) => [String(n), 0]))] };
    } else if (api.request_schema && Object.keys(api.request_schema).length) {
      body = api.request_schema;
    }
    return body;
  };

  const openTest = (api: any) => {
    setTestApi(api);
    setTestMethod(api.method || "POST");
    setTestUrl(api.endpoint || "/api/");
    // Prefill the Body with a sendable request (real feature names for
    // model/orchestration APIs), not the raw schema metadata.
    const sample = buildExampleBody(api);
    setTestBody(sample ? JSON.stringify(sample, null, 2) : '{\n  \n}');
    setTestResponse(null);
    setUseToken(false);
    setShowTest(true);
  };

  const myToken = () => localStorage.getItem("token") || "";

  const toggleToken = () => {
    if (!useToken && !myToken()) {
      message.warning(tr.token_missing);
      return;
    }
    setUseToken(!useToken);
  };

  const stName = (s: string) =>
    s === "published" ? tr.st_published : s === "offline" ? tr.st_offline : s === "failed" ? tr.st_failed : s;

  const typeLabel = (v: string) =>
    v === "model" ? tr.type_model : v === "orchestration" ? tr.type_orch : v === "chat" ? tr.type_chat : tr.type_custom;

  const buildExample = (api: any) => {
    const origin = typeof window === "undefined" ? "http://localhost:5173" : window.location.origin;
    const method = api.method || "POST";
    const tokenRef = useToken && myToken() ? myToken() : "<token>";
    const lines: string[] = [`curl -X ${method} "${origin}${api.endpoint || ""}" \\`];
    lines.push(`  -H "Authorization: Bearer ${tokenRef}" \\`);
    const body = buildExampleBody(api);
    if (method !== "GET" && method !== "HEAD") {
      lines.push(`  -H "Content-Type: application/json" \\`);
      lines.push(`  -d '${JSON.stringify(body ?? {}, null, 1).replace(/\n/g, "\n  ")}'`);
    }
    return lines.join("\n");
  };

  const handleSendTest = async () => {
    setTestLoading(true); setTestResponse(null);
    const start = Date.now();
    try {
      let headers: Record<string,string> = {};
      try { headers = JSON.parse(testHeaders); } catch {}
      if (!testUrl.startsWith("/api/")) throw new Error("Only internal /api/ endpoints can be tested");
      let body: any = undefined;
      if (testMethod !== "GET" && testMethod !== "HEAD") {
        try { body = JSON.parse(testBody); } catch { body = testBody; }
      }
      const resp = await apiClient.request({
        url: testUrl.replace(/^\/api(?=\/)/, ""),
        method: testMethod,
        headers,
        data: body,
      });
      const elapsed = Date.now() - start;
      const result = {
        status: resp.status, statusText: resp.statusText,
        headers: resp.headers || {},
        body: resp.data, elapsed,
      };
      setTestResponse(result);
      setTestHistory(prev => [{time:new Date().toLocaleTimeString(),method:testMethod,url:testUrl,status:resp.status,body:result}, ...prev.slice(0, 19)]);
    } catch (e: any) {
      if (e.response) {
        // HTTP error (4xx/5xx): show the real status and the API's error body
        // instead of a generic network error.
        setTestResponse({
          status: e.response.status, statusText: e.response.statusText || "",
          headers: e.response.headers || {}, body: e.response.data,
          elapsed: Date.now() - start,
        });
      } else {
        setTestResponse({ status: 0, statusText: "Network Error", error: e.message, elapsed: Date.now() - start });
      }
    } finally { setTestLoading(false); }
  };

  const filtered = filterType ? data.filter((a:any) => a.api_type === filterType) : data;

  const columns = [
    { title: tr.col_name, dataIndex: "name", key: "name", ellipsis: true },
    { title: tr.col_type, dataIndex: "api_type", key: "api_type",
      render: (v:string) => <Tag color={v==="model"?"blue":v==="orchestration"?"purple":v==="chat"?"green":"default"}>{typeLabel(v)}</Tag> },
    { title: tr.col_version, dataIndex: "version", key: "version", render: (v:string) => <Tag color="blue">{v}</Tag> },
    { title: tr.col_status, dataIndex: "status", key: "status",
      render: (s:string) => <Tag color={stColor[s]||"default"}>{stName(s)||s}</Tag> },
    { title: tr.col_method, dataIndex: "method", key: "method", width:80,
      render: (m:string) => <Tag color={m==="GET"?"green":"blue"}>{m}</Tag> },
    { title: tr.col_calls, dataIndex: "total_calls", key: "total_calls", width:80 },
    { title: tr.col_rate, key: "rate", width:100,
      render: (_:any, r:any) => <Text style={{color:r.total_calls>0&&(r.success_calls/r.total_calls)<0.9?"#ff4d4f":undefined}}>{r.total_calls>0?((r.success_calls/r.total_calls)*100).toFixed(1)+"%":"-"}</Text> },
    { title: tr.col_actions, key: "actions", width:300,
      render: (_:any, r:any) => (
        <Space size="small" wrap>
          <Button size="small" icon={<EyeOutlined />} onClick={() => { setDetail(r); setShowDetail(true); }}>{tr.detail}</Button>
          <Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={() => openTest(r)}>{tr.test}</Button>
          {r.status === "published" ? (
            <Button size="small" icon={<PauseCircleOutlined />} onClick={() => void toggleOnline(r, false)}>{tr.offline_btn}</Button>
          ) : (
            <Button size="small" icon={<PlayCircleOutlined />} onClick={() => void toggleOnline(r, true)}>{tr.online}</Button>
          )}
          {r.source_kind === "custom" && !r.source_id && (
            <Button size="small" icon={<EditOutlined />} onClick={() => openEditor(r)}>{tr.edit}</Button>
          )}
          {(r.source_kind === "custom" || r.source_kind === "orchestration" || r.source_kind === "chat" || r.source_kind === "model") && (
            <DeleteConfirmation label={`${tr.delete_confirm || "删除 "}${r.name}`} targetName={r.name} onConfirm={() => void handleDelete(r.id)} />
          )}
        </Space>
      )},
  ];

  return (
    <AppLayout>
      <Card><Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}><Title level={4} style={{ margin: 0 }}>{tr.title}</Title><Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor()}>{tr.create || "新建 API"}</Button></Space>
        <Row gutter={16} style={{ marginBottom: 20 }}>
          <Col xs={12} md={6}><Statistic title={tr.stat_total} value={stats.total_apis} /></Col>
          <Col xs={12} md={6}><Statistic title={tr.stat_published} value={stats.published} valueStyle={{ color: "#389e0d" }} /></Col>
          <Col xs={12} md={6}><Statistic title={tr.stat_offline} value={stats.offline} valueStyle={{ color: "#cf1322" }} /></Col>
          <Col xs={12} md={6}><Statistic title={tr.stat_calls} value={stats.total_calls} /></Col>
        </Row>
        <Space style={{ marginBottom: 16 }}>
          <Button type={filterType===""?"primary":"default"} onClick={()=>setFilterType("")}>{tr.filter_all}</Button>
          <Button type={filterType==="model"?"primary":"default"} onClick={()=>setFilterType("model")}>{tr.model_api}</Button>
          <Button type={filterType==="orchestration"?"primary":"default"} onClick={()=>setFilterType("orchestration")}>{tr.orch_api}</Button>
          <Button type={filterType==="chat"?"primary":"default"} onClick={()=>setFilterType("chat")}>{tr.chat_api}</Button>
          <Button type={filterType==="custom"?"primary":"default"} onClick={()=>setFilterType("custom")}>{tr.custom}</Button>
        </Space>
        {loadError && <Alert type="error" showIcon message={loadError} style={{ marginBottom: 16 }} />}
        <Table dataSource={filtered} columns={columns} rowKey="id" loading={loading} size="small"
          pagination={{ pageSize: 15 }} locale={{ emptyText: tr.empty }} />
      </Card>

      <Modal open={showEditor} title={editing ? tr.editor_edit : tr.editor_new} onCancel={() => setShowEditor(false)} onOk={() => form.submit()}>
        <Form form={form} layout="vertical" onFinish={handleSave} autoComplete="off">
          <Form.Item name="name" label={tr.f_name} rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="api_type" hidden><Input /></Form.Item>
          <Form.Item label={tr.f_type}><Input value={tr.f_type_value} disabled /></Form.Item>
          <Form.Item name="endpoint" label={tr.f_endpoint} rules={[{ required: true, pattern: /^\/api\//, message: tr.f_endpoint_rule }]}><Input /></Form.Item>
          <Form.Item name="method" label={tr.f_method}><Select options={["GET", "POST", "PUT", "PATCH", "DELETE"].map(value => ({ value, label: value }))} /></Form.Item>
          <Form.Item name="version" label={tr.f_version}><Input /></Form.Item>
          <Form.Item name="description" label={tr.f_description}><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>

      <Modal open={showDetail} onCancel={()=>setShowDetail(false)} footer={null} width={700} title={tr.detail_title}>
        {detail && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label={tr.d_name}>{detail.name}</Descriptions.Item>
            <Descriptions.Item label={tr.col_version}>{detail.version}</Descriptions.Item>
            <Descriptions.Item label={tr.col_type}>{typeLabel(detail.api_type)}</Descriptions.Item>
            <Descriptions.Item label={tr.d_algorithm}>{detail.algorithm_type || "-"}</Descriptions.Item>
            <Descriptions.Item label={tr.d_endpoint} span={2}><Text code>{detail.endpoint || "-"}</Text></Descriptions.Item>
            <Descriptions.Item label={tr.col_status}><Tag color={stColor[detail.status]}>{stName(detail.status)}</Tag></Descriptions.Item>
            <Descriptions.Item label={tr.col_method}><Tag>{detail.method}</Tag></Descriptions.Item>
            <Descriptions.Item label={tr.d_total_calls}>{detail.total_calls}</Descriptions.Item>
            <Descriptions.Item label={tr.d_success}>{detail.success_calls}</Descriptions.Item>
            <Descriptions.Item label={tr.d_failed}>{detail.failed_calls}</Descriptions.Item>
            <Descriptions.Item label={tr.d_public}>{detail.is_public ? tr.yes : tr.no}</Descriptions.Item>
            <Descriptions.Item label={tr.d_description} span={2}>{detail.description || "-"}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

      <Modal open={showTest} onCancel={() => setShowTest(false)} footer={null} width={900} title={<Space><PlayCircleOutlined /> {tr.test_title}{testApi?.name}</Space>}>
        <div style={{ display: "flex", gap: 16, height: 640 }}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12, overflow: "auto" }}>
            <Space>
              <Select value={testMethod} onChange={setTestMethod} style={{ width: 100 }}
                options={["GET","POST","PUT","DELETE","PATCH"].map(m=>({value:m,label:m}))} />
              <Input value={testUrl} readOnly style={{ flex: 1 }} />
              <Button type="primary" icon={<SendOutlined />} onClick={handleSendTest} loading={testLoading}>{t.ai_chat.send}</Button>
            </Space>
            {testApi && (
              <div>
                <Space style={{ marginBottom: 4 }}>
                  <Text type="secondary">{tr.example_title}</Text>
                  <Button size="small" icon={<CopyOutlined />} onClick={()=>{navigator.clipboard.writeText(buildExample(testApi));message.success(tr.copied);}}>{tr.copy}</Button>
                  <Button size="small" icon={<KeyOutlined />} onClick={toggleToken} danger={useToken}>{useToken ? tr.hide_token : tr.use_token}</Button>
                </Space>
                <pre style={{background:"#f5f5f5",padding:12,borderRadius:8,fontSize:12,margin:0,whiteSpace:"pre-wrap",wordBreak:"break-all",height:170,overflowY:"auto"}}>
                  {buildExample(testApi)}
                </pre>
                <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 2 }}>
                  {useToken ? tr.example_note_filled : tr.example_note}
                </Text>
              </div>
            )}
            <Text type="secondary">{tr.headers}:</Text>
            <TextArea value={testHeaders} onChange={e=>setTestHeaders(e.target.value)} rows={3} style={{ fontFamily:"monospace",fontSize:12 }} />
            <Text type="secondary">{tr.body}:</Text>
            <TextArea value={testBody} onChange={e=>setTestBody(e.target.value)} rows={14} style={{ fontFamily:"monospace",fontSize:12 }} />
          </div>
          <div style={{ flex: 1, borderLeft: "1px solid #f0f0f0", paddingLeft: 16, overflow: "auto" }}>
            {testResponse ? (
              <div>
                <Space style={{marginBottom:8}}>
                  <Tag color={testResponse.status>=200&&testResponse.status<300?"green":"red"}>{testResponse.status} {testResponse.statusText}</Tag>
                  <Text type="secondary">{testResponse.elapsed}ms</Text>
                  <Button size="small" icon={<CopyOutlined />} onClick={()=>{navigator.clipboard.writeText(JSON.stringify(testResponse.body,null,2));message.success(tr.copied);}}>{tr.copy}</Button>
                </Space>
                {testResponse.error && <Text type="danger">{testResponse.error}</Text>}
                <pre style={{background:"#f5f5f5",padding:12,borderRadius:8,overflow:"auto",maxHeight:260,fontSize:12,margin:0}}>
                  {typeof testResponse.body==="string"?testResponse.body:JSON.stringify(testResponse.body,null,2)}
                </pre>
                {(() => {
                  const docs = testApi ? (RESPONSE_FIELD_DOCS[testApi.api_type] || []) : [];
                  const bodyObj = (testResponse.body && typeof testResponse.body === "object" && !Array.isArray(testResponse.body)) ? testResponse.body : null;
                  if (!docs.length || !bodyObj) return null;
                  const rows: Array<[string, string]> = docs.filter(([key]) => key in bodyObj).map(([key, zh, en]) => [key, lang === "zh" ? zh : en]);
                  const first = Array.isArray(bodyObj.records) ? bodyObj.records[0] : null;
                  if (testApi.api_type === "orchestration" && first && typeof first === "object") {
                    if ("triggered" in first) {
                      rows.push(
                        ["records[].triggered", lang === "zh" ? "是否达到阈值触发自动重训" : "Whether auto-retrain was triggered"],
                        ["records[].total_rows", lang === "zh" ? "错误数据集累计行数" : "Error dataset total rows"],
                        ["records[].cycle_rows", lang === "zh" ? "本轮周期新增行数" : "Rows added this cycle"],
                        ["records[].threshold_rows", lang === "zh" ? "触发重训的阈值行数" : "Threshold rows to trigger retrain"],
                      );
                    }
                    // 动态输出元数据：目标列与类别随模型版本走
                    const tgt = testApi?.response_schema?.target;
                    if (tgt && tgt.name && "prediction" in first) {
                      rows.push(["records[].prediction", lang === "zh"
                        ? `目标列「${tgt.name}」的预测${tgt.classes?.length ? `；类别：${tgt.classes.join(" / ")}` : ""}`
                        : `Prediction of target column "${tgt.name}"${tgt.classes?.length ? `; classes: ${tgt.classes.join(" / ")}` : ""}`]);
                    }
                  }
                  if (testApi.api_type === "model") {
                    const cols = testApi?.response_schema?.columns;
                    const c0 = Array.isArray(cols) ? cols[0] : null;
                    if (c0 && c0.classes?.length) {
                      rows.push(
                        ["predictions", lang === "zh"
                          ? `目标列「${c0.display_name || c0.machine_key}」的${c0.task === "classification" ? "分类" : ""}预测（与输入一一对应）`
                          : `Prediction of target column "${c0.display_name || c0.machine_key}" (one per input record)`],
                        ["probabilities", lang === "zh"
                          ? `各类别概率；类别标签：${c0.classes.join(" / ")}`
                          : `Class probabilities; labels: ${c0.classes.join(" / ")}`],
                      );
                    }
                  }
                  // 动态行覆盖同字段的静态解释（后写优先）
                  const deduped = new Map<string, string>();
                  for (const [field, desc] of rows) deduped.set(field, desc);
                  if (!deduped.size) return null;
                  return (
                    <div style={{ marginTop: 12 }}>
                      <Text strong style={{ fontSize: 12 }}>{tr.field_docs}</Text>
                      <table style={{ width: "100%", marginTop: 4, borderCollapse: "collapse", fontSize: 12 }}>
                        <tbody>
                          {Array.from(deduped.entries()).map(([field, desc]) => (
                            <tr key={field}>
                              <td style={{ border: "1px solid #f0f0f0", padding: "3px 8px", fontFamily: "monospace", whiteSpace: "nowrap", verticalAlign: "top" }}>{field}</td>
                              <td style={{ border: "1px solid #f0f0f0", padding: "3px 8px" }}>{desc}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                })()}
              </div>
            ) : (
              <div style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",height:"100%",color:"#ccc"}}>
                <SendOutlined style={{fontSize:48,marginBottom:16}} />
                <Text type="secondary">{tr.click_send}</Text>
              </div>
            )}
          </div>
        </div>
        {testHistory.length > 0 && (
          <div style={{ marginTop: 16, borderTop: "1px solid #f0f0f0", paddingTop: 12 }}>
            <Text strong>{tr.history}</Text>
            <div style={{ maxHeight: 120, overflow: "auto", marginTop: 8 }}>
              {testHistory.slice(0, 10).map((h, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0", borderBottom: "1px solid #fafafa", fontSize: 12 }}>
                  <Text type="secondary">{h.time}</Text>
                  <Tag style={{fontSize:11}} color={h.method==="GET"?"green":"blue"}>{h.method}</Tag>
                  <Text ellipsis style={{maxWidth:300}}>{h.url}</Text>
                  <Text style={{color:h.status>=200&&h.status<300?"#52c41a":"#ff4d4f",fontWeight:"bold"}}>{h.status}</Text>
                </div>
              ))}
            </div>
          </div>
        )}
      </Modal>
    </AppLayout>
  );
}
