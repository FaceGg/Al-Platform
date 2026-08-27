import { useState, useEffect, useRef } from "react";
import { Card, Table, Tag, Button, Space, Typography, Modal, Descriptions, message, Select, Input, Tabs, Spin, Empty } from "antd";
import { PlayCircleOutlined, DeleteOutlined, EyeOutlined, SendOutlined, CopyOutlined, CheckOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import { apiGet, apiDelete } from "../api/client";
import { useI18n } from "../i18n";
import { notifyDashboardStatsChanged } from "../events/dashboardStats";

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;
const stColor: Record<string, string> = { published: "green", offline: "red", failed: "orange" };
const stName: Record<string, string> = { published: "Published", offline: "Offline", failed: "Failed" };

export default function APIMarketplacePage() {
  const { t } = useI18n();
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [showTest, setShowTest] = useState(false);
  const [testApi, setTestApi] = useState<any>(null);
  const [filterType, setFilterType] = useState("");
  const [testMethod, setTestMethod] = useState("POST");
  const [testUrl, setTestUrl] = useState("http://127.0.0.1:8000");
  const [testBody, setTestBody] = useState('{\n  \n}');
  const [testHeaders, setTestHeaders] = useState('{"Content-Type":"application/json"}');
  const [testResponse, setTestResponse] = useState<any>(null);
  const [testLoading, setTestLoading] = useState(false);
  const [testHistory, setTestHistory] = useState<Array<{time:string; method:string; url:string; status:number; body:any}>>([]);

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    setLoading(true);
    try { const res: any = await apiGet("/api/platform/apis"); setData(res.items || []); }
    finally { setLoading(false); }
  };

  const handleDelete = async (id: string) => {
    await apiDelete("/api/platform/apis/" + id);
    notifyDashboardStatsChanged();
    message.success("Deleted"); fetchData();
  };

  const openTest = (api: any) => {
    setTestApi(api);
    setTestMethod(api.method || "POST");
    setTestUrl("http://127.0.0.1:8000" + (api.endpoint || "/api/"));
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
      const options: RequestInit = { method: testMethod, headers };
      if (testMethod !== "GET" && testMethod !== "HEAD") {
        try { options.body = testBody; } catch { options.body = testBody; }
      }
      const resp = await fetch(testUrl, options);
      const elapsed = Date.now() - start;
      let respBody: any;
      const ct = resp.headers.get("content-type") || "";
      if (ct.includes("json")) respBody = await resp.json();
      else respBody = await resp.text();
      const result = {
        status: resp.status, statusText: resp.statusText,
        headers: Object.fromEntries(resp.headers.entries()),
        body: respBody, elapsed,
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
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(r.id)} />
        </Space>
      )},
  ];

  return (
    <AppLayout>
      <Card><Title level={4}>{t.api_market.title}</Title>
        <Space style={{ marginBottom: 16 }}>
          <Button type={filterType===""?"primary":"default"} onClick={()=>setFilterType("")}>All</Button>
          <Button type={filterType==="model"?"primary":"default"} onClick={()=>setFilterType("model")}>{t.api_market.model_api}</Button>
          <Button type={filterType==="orchestration"?"primary":"default"} onClick={()=>setFilterType("orchestration")}>Orch. API</Button>
          <Button type={filterType==="custom"?"primary":"default"} onClick={()=>setFilterType("custom")}>{t.api_market.custom}</Button>
        </Space>
        <Table dataSource={filtered} columns={columns} rowKey="id" loading={loading} size="small"
          pagination={{ pageSize: 15 }} locale={{ emptyText: "No APIs yet" }} />
      </Card>

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
              <Input value={testUrl} onChange={e=>setTestUrl(e.target.value)} style={{ flex: 1 }} />
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
