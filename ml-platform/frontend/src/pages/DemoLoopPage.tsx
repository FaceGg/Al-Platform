import { useCallback, useEffect, useState } from "react";
import {
  Button, Card, message, Popconfirm, Select, Space, Table, Tag, Tooltip, Typography,
} from "antd";
import {
  ArrowRightOutlined, DeleteOutlined, DeploymentUnitOutlined, EditOutlined,
  PlusOutlined, ReloadOutlined, TeamOutlined,
} from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import AppLayout from "../components/AppLayout";
import LoopConfigModal, { type LoopEditorState } from "../components/loop/LoopConfigModal";
import { formatApiError } from "../api/client";
import {
  type DemoLoopConfig, deleteDemoLoop, fetchDemoLoopAnnotators, fetchDemoLoopDatasets,
  fetchDemoLoopDeployments, fetchDemoLoopProjects, fetchDemoLoops,
} from "../api/demoLoop";
import { useI18n } from "../i18n";
import { parseBackendTime } from "../utils/time";

const { Title, Text } = Typography;

export default function DemoLoopPage() {
  const { t } = useI18n();
  const tr = ((t as unknown as Record<string, Record<string, string | undefined>>).demo_loop ?? {}) as Record<string, string | undefined>;
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [loops, setLoops] = useState<DemoLoopConfig[]>([]);
  const [editor, setEditor] = useState<LoopEditorState | null>(null);
  const [deployments, setDeployments] = useState<Array<{ id: string; name: string; observed_state: string }>>([]);
  const [datasets, setDatasets] = useState<Array<{ id: string; name: string }>>([]);
  const [annotators, setAnnotators] = useState<Array<{ id: string; username: string }>>([]);

  useEffect(() => {
    fetchDemoLoopProjects().then((res: any) => {
      const items = res.items || [];
      setProjects(items);
      if (items.length) setProjectId(items[0].id);
    }).catch((error) => message.error(formatApiError(error, "项目加载失败")));
  }, []);

  const loadProjectData = useCallback(async (pid: string) => {
    if (!pid) return;
    try {
      const [loopsRes, dep, ds, ann] = await Promise.all([
        fetchDemoLoops(pid).catch(() => ({ items: [] })),
        fetchDemoLoopDeployments(pid).catch(() => ({ items: [] })),
        fetchDemoLoopDatasets(pid).catch(() => ({ items: [] })),
        fetchDemoLoopAnnotators(pid).catch(() => ({ items: [] })),
      ]);
      setLoops((loopsRes?.items || []) as DemoLoopConfig[]);
      setDeployments((dep?.items || []).map((item: any) => ({
        id: item.id, name: item.name, observed_state: item.observed_state,
      })));
      setDatasets((ds?.items || []).map((item: any) => ({ id: item.id, name: item.name })));
      setAnnotators((ann?.items || []).map((item: any) => ({ id: item.id, username: item.username })));
    } catch (error) {
      message.error(formatApiError(error, "闭环数据加载失败"));
    }
  }, []);

  useEffect(() => { loadProjectData(projectId); }, [projectId, loadProjectData]);

  const refreshLoops = async () => {
    const list: DemoLoopConfig[] = await fetchDemoLoops(projectId).then((res: any) => res?.items || []).catch(() => []);
    setLoops(list);
  };

  const openDetail = (loop: DemoLoopConfig) => {
    navigate(`/demo-loop/${loop.id}?project=${projectId}`);
  };

  const handleDeleteLoop = async (loopId: string) => {
    try {
      await deleteDemoLoop(projectId, loopId);
      message.success(tr.deleted || "闭环任务已删除");
      await refreshLoops();
    } catch (error) {
      message.error(formatApiError(error, "删除失败"));
    }
  };

  return (
    <AppLayout>
      <style>{`
        .loop-task-table .ant-table-tbody > tr { cursor: pointer; }
      `}</style>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap size="large">
          <Title level={3} style={{ margin: 0 }}>
            <DeploymentUnitOutlined /> {tr.title || "推理-回流-重训 自动化闭环"}
          </Title>
          <span>
            <Text type="secondary">{tr.project || "项目"}</Text>
            <Select
              style={{ minWidth: 220, marginLeft: 8 }}
              value={projectId || undefined}
              onChange={(value) => setProjectId(value)}
              options={projects.map((item) => ({ value: item.id, label: item.name }))}
              placeholder={tr.choose_project || "选择项目"}
            />
          </span>
          <Button icon={<ReloadOutlined />} onClick={() => loadProjectData(projectId)}>
            {tr.refresh || "刷新"}
          </Button>
          <Button onClick={() => window.open("/demo-showcase.html", "_blank")}>
            {tr.showcase || "运行监控大屏"}
          </Button>
        </Space>
      </Card>

      <Card
        title={<><TeamOutlined /> {tr.loops_title || "闭环任务"}</>}
        extra={(
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>点击任务行进入任务详情</Text>
            <Button size="small" type="primary" icon={<PlusOutlined />}
              onClick={() => setEditor({ mode: "create" })} data-testid="new-loop-btn">
              {tr.new_loop || "新建闭环"}
            </Button>
          </Space>
        )}
      >
        <Table
          className="loop-task-table"
          data-testid="loop-task-list"
          size="small"
          rowKey="id"
          dataSource={loops}
          pagination={false}
          onRow={(record) => ({
            onClick: () => openDetail(record),
            style: { cursor: "pointer" },
          })}
          locale={{ emptyText: tr.empty_loops || "暂无闭环任务，点击右上角「新建闭环」创建" }}
          columns={[
            {
              title: tr.col_name || "任务名称",
              dataIndex: "name",
              render: (value: string) => <span style={{ fontWeight: 500 }}>{value}</span>,
            },
            {
              title: tr.col_error || "回流行数",
              dataIndex: "error_count",
              width: 100,
              render: (value: number) => <Tag color={value > 0 ? "orange" : "default"}>回流 {value ?? 0}</Tag>,
            },
            {
              title: tr.col_alert || "告警次数",
              dataIndex: "alert_count",
              width: 100,
              render: (value: number) => <Tag color={value > 0 ? "red" : "default"}>告警 {value ?? 0}</Tag>,
            },
            {
              title: "创建时间",
              dataIndex: "created_at",
              width: 130,
              render: (value: string | null) => {
                const parsed = value ? parseBackendTime(value) : null;
                return <Text type="secondary" style={{ fontSize: 12 }}>
                  {parsed ? parsed.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "-"}
                </Text>;
              },
            },
            {
              title: tr.col_retrain || "自动建模",
              dataIndex: "retrain_status",
              width: 110,
              render: (value: string) => (
                <Tag color={value === "completed" ? "green" : value === "failed" ? "red" : value === "running" || value === "queued" ? "blue" : "default"}>
                  {value === "completed" ? "已换模" : value === "failed" ? "重训失败" : value === "running" || value === "queued" ? "重训中" : "未重训"}
                </Tag>
              ),
            },
            {
              title: tr.col_actions || "操作",
              width: 150,
              render: (_: unknown, record) => (
                <Space size={4}>
                  <Button
                    size="small" icon={<ArrowRightOutlined />}
                    onClick={(event) => { event.stopPropagation(); openDetail(record); }}
                  >
                    详情
                  </Button>
                  <Button
                    size="small" icon={<EditOutlined />}
                    onClick={(event) => { event.stopPropagation(); setEditor({ mode: "edit", loop: record }); }}
                  />
                  <Popconfirm
                    title="删除该闭环任务？"
                    description="事件与计数一并删除，报错数据文件保留。"
                    onConfirm={(event) => { event?.stopPropagation(); handleDeleteLoop(record.id); }}
                    onCancel={(event) => event?.stopPropagation()}
                  >
                    <Button
                      size="small" danger icon={<DeleteOutlined />}
                      onClick={(event) => event.stopPropagation()}
                    />
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <LoopConfigModal
        editor={editor}
        projectId={projectId}
        deployments={deployments}
        datasets={datasets}
        annotators={annotators}
        onCancel={() => setEditor(null)}
        onSaved={() => { setEditor(null); void refreshLoops(); }}
      />
    </AppLayout>
  );
}
