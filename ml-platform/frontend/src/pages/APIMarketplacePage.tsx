import { useState, useEffect, useRef } from "react";
import { Alert, Card, Table, Tag, Button, Space, Typography, Modal, Descriptions, message, Select, Input, Form, Row, Col, Statistic } from "antd";
import { PlayCircleOutlined, EyeOutlined, SendOutlined, CopyOutlined, PlusOutlined, EditOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import apiClient, { apiGet, apiPost, apiPut, apiDelete, formatApiError } from "../api/client";
import { useI18n } from "../i18n";
import { notifyDashboardStatsChanged } from "../events/dashboardStats";
import DeleteConfirmation from "../components/DeleteConfirmation";

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;
const stColor: Record<string, string> = { published: "green", offline: "red", failed: "orange" };
const stName: Record<string, string> = { published: "Published", offline: "Offline", failed: "Failed" };

export default function APIMarketplacePage() {
  const { t } = useI18n();
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

  const openTest = (api: any) => {
    setTestApi(api);
    setTestMethod(api.method || "POST");
    setTestUrl(api.endpoint || "/api/");
    setTestBody(api.request_schema ? JSON.stringify(api.request_schema, null, 2) : '{\n  \n}');
    setTestResponse(null);
    setShowTest(true);
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
      setTestResponse({ status: 0, statusText: "Network Error", error: e.message, elapsed: Date.now() - start });
    } finally { setTestLoading(false); }
  };

  const filtered = filterType ? data.filter((a:any) => a.api_type === filterType) : data;

  const columns = [
    { title: "API Name", dataIndex: "name", key: "name", ellipsis: true },
    { title: "Type", dataIndex: "api_type", key: "api_type",
      render: (t:string) => <Tag color={t==="model"?"blue":t==="orchestration"?"purple":"default"}>{t==="model"?"Model":t==="orchestration"?"Orch.":"Custom"}</Tag> },
    { title: "Version", dataIndex: "version", key: "version", render: (v:string) => <Tag color="blue">{v}</Tag> },
    { title: "Status", dataIndex: "status", key: "status",
      render: (s:string) => <Tag color={stColor[s]||"default"}>{stName[s]||s}</Tag> },
    { title: "Method", dataIndex: "method", key: "method", width:80,
      render: (m:string) => <Tag color={m==="GET"?"green":"blue"}>{m}</Tag> },
    { title: "Calls", dataIndex: "total_calls", key: "total_calls", width:80 },
    { title: "Success Rate", key: "rate", width:100,
      render: (_:any, r:any) => <Text style={{color:r.total_calls>0&&(r.success_calls/r.total_calls)<0.9?"#ff4d4f":undefined}}>{r.total_calls>0?((r.success_calls/r.total_calls)*100).toFixed(1)+"%":"-"}</Text> },
    { title: "Actions", key: "actions", width:200,
      render: (_:any, r:any) => (
        <Space size="small">
          <Button size="small" icon={<EyeOutlined />} onClick={() => { setDetail(r); setShowDetail(true); }}>{t.api_market.detail}</Button>
          <Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={() => openTest(r)}>{t.api_market.test}</Button>
          {r.source_kind === "custom" && !r.source_id && (
            <>
              <Button size="small" icon={<EditOutlined />} onClick={() => openEditor(r)}>编辑</Button>
              <DeleteConfirmation label={`删除 ${r.name}`} targetName={r.name} onConfirm={() => void handleDelete(r.id)} />
            </>
          )}
        </Space>
      )},
  ];

  return (
    <AppLayout>
      <Card><Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}><Title level={4} style={{ margin: 0 }}>{t.api_market.title}</Title><Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor()}>{t.api_market.create || "新建 API"}</Button></Space>
        <Row gutter={16} style={{ marginBottom: 20 }}>
          <Col xs={12} md={6}><Statistic title="API 总数" value={stats.total_apis} /></Col>
          <Col xs={12} md={6}><Statistic title="已发布" value={stats.published} valueStyle={{ color: "#389e0d" }} /></Col>
          <Col xs={12} md={6}><Statistic title="已下线" value={stats.offline} valueStyle={{ color: "#cf1322" }} /></Col>
          <Col xs={12} md={6}><Statistic title="API 调用总数" value={stats.total_calls} /></Col>
        </Row>
        <Space style={{ marginBottom: 16 }}>
          <Button type={filterType===""?"primary":"default"} onClick={()=>setFilterType("")}>All</Button>
          <Button type={filterType==="model"?"primary":"default"} onClick={()=>setFilterType("model")}>{t.api_market.model_api}</Button>
          <Button type={filterType==="orchestration"?"primary":"default"} onClick={()=>setFilterType("orchestration")}>Orch. API</Button>
          <Button type={filterType==="custom"?"primary":"default"} onClick={()=>setFilterType("custom")}>{t.api_market.custom}</Button>
        </Space>
        {loadError && <Alert type="error" showIcon message={loadError} style={{ marginBottom: 16 }} />}
        <Table dataSource={filtered} columns={columns} rowKey="id" loading={loading} size="small"
          pagination={{ pageSize: 15 }} locale={{ emptyText: "No APIs yet" }} />
      </Card>

      <Modal open={showEditor} title={editing ? "编辑 API" : "新建 API"} onCancel={() => setShowEditor(false)} onOk={() => form.submit()}>
        <Form form={form} layout="vertical" onFinish={handleSave}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="api_type" hidden><Input /></Form.Item>
          <Form.Item label="类型"><Input value="自定义" disabled /></Form.Item>
          <Form.Item name="endpoint" label="内部路径" rules={[{ required: true, pattern: /^\/api\//, message: "必须是 /api/ 开头的内部路径" }]}><Input /></Form.Item>
          <Form.Item name="method" label="方法"><Select options={["GET", "POST", "PUT", "PATCH", "DELETE"].map(value => ({ value, label: value }))} /></Form.Item>
          <Form.Item name="version" label="版本"><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>

      <Modal open={showDetail} onCancel={()=>setShowDetail(false)} footer={null} width={700} title="API Detail">
        {detail && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="Name">{detail.name}</Descriptions.Item>
            <Descriptions.Item label="Version">{detail.version}</Descriptions.Item>
            <Descriptions.Item label="Type">{detail.api_type}</Descriptions.Item>
            <Descriptions.Item label="Algorithm">{detail.algorithm_type || "-"}</Descriptions.Item>
            <Descriptions.Item label="Endpoint" span={2}><Text code>{detail.endpoint || "-"}</Text></Descriptions.Item>
            <Descriptions.Item label="Status"><Tag color={stColor[detail.status]}>{stName[detail.status]}</Tag></Descriptions.Item>
            <Descriptions.Item label="Method"><Tag>{detail.method}</Tag></Descriptions.Item>
            <Descriptions.Item label="Total Calls">{detail.total_calls}</Descriptions.Item>
            <Descriptions.Item label="Success">{detail.success_calls}</Descriptions.Item>
            <Descriptions.Item label="Failed">{detail.failed_calls}</Descriptions.Item>
            <Descriptions.Item label="Public">{detail.is_public ? "Yes" : "No"}</Descriptions.Item>
            <Descriptions.Item label="Description" span={2}>{detail.description || "-"}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

      <Modal open={showTest} onCancel={() => setShowTest(false)} footer={null} width={900} title={<Space><PlayCircleOutlined /> API Test: {testApi?.name}</Space>}>
        <div style={{ display: "flex", gap: 16, height: 500 }}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
            <Space>
              <Select value={testMethod} onChange={setTestMethod} style={{ width: 100 }}
                options={["GET","POST","PUT","DELETE","PATCH"].map(m=>({value:m,label:m}))} />
              <Input value={testUrl} readOnly style={{ flex: 1 }} />
              <Button type="primary" icon={<SendOutlined />} onClick={handleSendTest} loading={testLoading}>{t.ai_chat.send}</Button>
            </Space>
            <Text type="secondary">Headers:</Text>
            <TextArea value={testHeaders} onChange={e=>setTestHeaders(e.target.value)} rows={3} style={{ fontFamily:"monospace",fontSize:12 }} />
            <Text type="secondary">Body:</Text>
            <TextArea value={testBody} onChange={e=>setTestBody(e.target.value)} rows={6} style={{ fontFamily:"monospace",fontSize:12 }} />
          </div>
          <div style={{ flex: 1, borderLeft: "1px solid #f0f0f0", paddingLeft: 16, overflow: "auto" }}>
            {testResponse ? (
              <div>
                <Space style={{marginBottom:8}}>
                  <Tag color={testResponse.status>=200&&testResponse.status<300?"green":"red"}>{testResponse.status} {testResponse.statusText}</Tag>
                  <Text type="secondary">{testResponse.elapsed}ms</Text>
                  <Button size="small" icon={<CopyOutlined />} onClick={()=>{navigator.clipboard.writeText(JSON.stringify(testResponse.body,null,2));message.success("Copied");}}>{t.api_market.copy}</Button>
                </Space>
                {testResponse.error && <Text type="danger">{testResponse.error}</Text>}
                <pre style={{background:"#f5f5f5",padding:12,borderRadius:8,overflow:"auto",maxHeight:400,fontSize:12,margin:0}}>
                  {typeof testResponse.body==="string"?testResponse.body:JSON.stringify(testResponse.body,null,2)}
                </pre>
              </div>
            ) : (
              <div style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",height:"100%",color:"#ccc"}}>
                <SendOutlined style={{fontSize:48,marginBottom:16}} />
                <Text type="secondary">Click "Send" to test the API</Text>
              </div>
            )}
          </div>
        </div>
        {testHistory.length > 0 && (
          <div style={{ marginTop: 16, borderTop: "1px solid #f0f0f0", paddingTop: 12 }}>
            <Text strong>{t.api_market.history}</Text>
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
