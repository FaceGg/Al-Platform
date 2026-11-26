import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  App as AntApp, Button, Card, Col, Descriptions, Empty, Input, Modal, Row, Select, Space, Switch, Tag, Tree, Typography,
} from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import AppLayout from "../components/AppLayout";
import V2PageFrame from "../components/V2PageFrame";
import PageHeading from "../components/PageHeading";
import { ScopeSelector, StaleBanner, useMonitorScope } from "../components/quality/MonitorParts";
import { ackReceived, callQuality, getStations, subscribeMonitorStream } from "../api/qualityMonitor";
import type { StationCard, StationsPayload } from "../api/qualityMonitor";
import { ALERT_LABELS, SEVERITY_COLOR, apiErrorText } from "../api/qualityAlerts";
import type { AlertSeverity } from "../api/qualityAlerts";
import { useI18n } from "../i18n";
import { formatLocalTime } from "../utils/time";

/** 质量管理 · 监控 / 实时生产监控（B1-05，技术方案 §9B.4）。
 *
 * 产线 / 工位 / 设备三级树 + 工位卡；新事件经推送流上屏（D29），断流自动回退轮询。
 */

const POLL_SECONDS = 3;
type LiveMode = "off" | "stream" | "polling";

export default function QualityMonitorPage() {
  const { message } = AntApp.useApp();
  const { lang } = useI18n();
  const zh = lang === "zh";
  const navigate = useNavigate();
  const { projectId, setProjectId, projects, scenes, stations, scope, setLevel, options } = useMonitorScope();
  const [data, setData] = useState<StationsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [auto, setAuto] = useState(true);
  const [live, setLive] = useState<LiveMode>("off");
  const [lastEventAt, setLastEventAt] = useState<string | null>(null);
  const [selectedLine, setSelectedLine] = useState<string | undefined>(undefined);
  const [callTarget, setCallTarget] = useState<StationCard | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!projectId) { setData(null); return; }
    setLoading(true);
    getStations(projectId, scope)
      .then(setData)
      .catch((e) => message.error(apiErrorText(e)))
      .finally(() => setLoading(false));
  }, [projectId, scope, message]);

  useEffect(() => { load(); }, [load]);

  // 实时刷新：优先推送流；建立失败或断流时回退到 3 秒轮询（关闭「自动刷新」则都不做）
  useEffect(() => {
    if (!projectId || !auto) { setLive("off"); return; }
    let pollTimer: number | undefined;
    const startPolling = () => {
      setLive("polling");
      if (pollTimer === undefined) {
        pollTimer = window.setInterval(() => {
          if (document.visibilityState !== "hidden") load();
        }, POLL_SECONDS * 1000);
      }
    };
    const stop = subscribeMonitorStream(projectId, scope, {
      onEvent: (event) => {
        if (event.type === "snapshot") setLive("stream");
        setLastEventAt(new Date().toISOString());
        load();
      },
      onFallback: startPolling,
    });
    return () => {
      stop();
      if (pollTimer !== undefined) window.clearInterval(pollTimer);
    };
  }, [projectId, scope, auto, load]);

  const confirmReceived = async (card: StationCard) => {
    setBusy(true);
    try {
      const result = await ackReceived(projectId!, card.station_id);
      message.success(zh ? `已确认收到 ${result.acknowledged} 条预警` : `${result.acknowledged} alerts acknowledged`);
      load();
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const sendCall = async () => {
    if (!callTarget) return;
    setBusy(true);
    try {
      await callQuality(projectId!, callTarget.station_id, reason.trim());
      message.success(zh ? "已通知工位责任人与项目负责人" : "Responsible user and project owner notified");
      setCallTarget(null);
      setReason("");
    } catch (e) {
      message.error(apiErrorText(e));
    } finally {
      setBusy(false);
    }
  };

  const cards = (data?.cards ?? []).filter(
    (card) => !selectedLine || (card.production_line ?? "未归属产线") === selectedLine,
  );
  const treeData = (data?.tree ?? []).map((line) => ({
    key: line.key,
    title: `${line.title}（${line.children.length}）`,
    children: line.children.map((station) => ({
      key: station.key,
      title: (
        <Space size={4}>
          <span>{station.title}</span>
          {station.open_alerts > 0 && <Tag color="red">{station.open_alerts}</Tag>}
          {station.device && !station.device.online && <Tag>{zh ? "离线" : "Offline"}</Tag>}
        </Space>
      ),
    })),
  }));
  const liveText = live === "stream" ? (zh ? "实时推送" : "Streaming") : live === "polling" ? (zh ? `轮询（每 ${POLL_SECONDS} 秒）` : `Polling (every ${POLL_SECONDS}s)`) : (zh ? "已暂停" : "Paused");

  return (
    <AppLayout>
      <V2PageFrame section="quality" navKey="quality_monitor" testId="v2-quality-monitor">
        <PageHeading
          section="quality"
          navKey="quality_monitor"
          desc={zh ? "实时生产监控：产线 / 工位 / 设备三级树与工位卡；新事件经推送流上屏，断流自动改为轮询。" : "Real-time production monitoring with a line / station / device tree and live station cards."}
          actions={(
            <Space wrap>
              <Select
                aria-label={zh ? "选择项目" : "Select project"}
                style={{ minWidth: 180 }}
                placeholder={zh ? "选择项目" : "Select project"}
                value={projectId ?? undefined}
                onChange={(value: string) => setProjectId(value)}
                options={projects.map((p) => ({ value: p.id, label: p.name }))}
              />
              <ScopeSelector scope={scope} options={options} scenes={scenes} stations={stations} onChange={setLevel} />
              <Switch
                aria-label={zh ? "自动刷新" : "Auto refresh"}
                checked={auto}
                checkedChildren={zh ? "自动" : "Auto"}
                unCheckedChildren={zh ? "手动" : "Manual"}
                onChange={setAuto}
              />
              <Tag data-testid="live-mode" color={live === "stream" ? "green" : live === "polling" ? "gold" : "default"}>{liveText}</Tag>
              <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>{zh ? "刷新" : "Refresh"}</Button>
            </Space>
          )}
        />
        <StaleBanner stale={data?.stale} />
        <Row gutter={16}>
          <Col xs={24} lg={7}>
            <Card size="small" title={zh ? "产线 / 工位 / 设备" : "Lines / stations / devices"} loading={loading}>
              {treeData.length === 0 ? (
                <Empty description={zh ? "范围内没有启用的工位：先在「工位与设备」里登记工位并填写产线归属" : "No enabled stations in scope"} />
              ) : (
                <Tree
                  data-testid="production-tree"
                  defaultExpandAll
                  selectedKeys={[selectedLine ? `line:${selectedLine}` : scope.station_id ?? ""]}
                  treeData={treeData}
                  onSelect={(keys) => {
                    const key = keys.length > 0 ? String(keys[0]) : undefined;
                    if (!key) { setSelectedLine(undefined); setLevel("station_id", undefined); return; }
                    if (key.startsWith("line:")) {
                      setSelectedLine(key.slice("line:".length));
                      setLevel("station_id", undefined);
                    } else {
                      setSelectedLine(undefined);
                      setLevel("station_id", key);
                    }
                  }}
                />
              )}
            </Card>
          </Col>
          <Col xs={24} lg={17}>
            {cards.length === 0 ? (
              <Card size="small"><Empty description={zh ? "没有工位卡：调整范围或先登记工位" : "No station cards"} /></Card>
            ) : (
              <Row gutter={[16, 16]} data-testid="station-cards">
                {cards.map((card) => (
                  <Col xs={24} md={12} xl={8} key={card.station_id}>
                    <Card
                      size="small"
                      data-testid={`card-${card.code}`}
                      title={(
                        <Space wrap>
                          <span>{card.name}（{card.code}）</span>
                          {card.device && (
                            <Tag color={card.device.online ? "green" : "red"}>
                              {card.device.online ? (zh ? "设备在线" : "Device online") : (zh ? "设备离线" : "Device offline")}
                            </Tag>
                          )}
                        </Space>
                      )}
                    >
                      <Descriptions size="small" column={2}>
                        <Descriptions.Item label={zh ? "产品" : "Product"}>{card.product ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={zh ? "批次" : "Batch"}>{card.batch ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={zh ? "最新生产" : "Last production"} span={2}>
                          {card.last_production_at ? formatLocalTime(card.last_production_at) : (zh ? "尚无推理记录" : "No inference yet")}
                        </Descriptions.Item>
                        <Descriptions.Item label={zh ? "结果" : "Result"}>
                          {card.result === "anomaly" ? <Tag color="red">{zh ? "异常" : "Anomaly"}</Tag>
                            : card.result === "ok" ? <Tag color="green">{zh ? "正常" : "OK"}</Tag>
                              : card.result ? <Tag>{card.predicted_label ?? card.result}</Tag> : "-"}
                        </Descriptions.Item>
                        <Descriptions.Item label={zh ? "风险分数" : "Score"}>{card.score ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={zh ? "班次产量" : "Shift output"}>
                          {card.shift_total}{card.shift_anomaly > 0 ? `（${zh ? "异常" : "anomaly"} ${card.shift_anomaly}）` : ""}
                        </Descriptions.Item>
                        <Descriptions.Item label={zh ? "未关闭事件" : "Open alerts"}>
                          {card.open_alerts > 0 ? <Tag color="red">{card.open_alerts}</Tag> : 0}
                        </Descriptions.Item>
                      </Descriptions>
                      {card.latest_alert && (
                        <Typography.Link
                          data-testid={`latest-${card.code}`}
                          onClick={() => navigate(`/quality/disposition?alert=${card.latest_alert?.id}`)}
                        >
                          <Tag color={SEVERITY_COLOR[card.latest_alert.severity as AlertSeverity]}>
                            {ALERT_LABELS.severity[lang][card.latest_alert.severity as AlertSeverity] ?? card.latest_alert.severity}
                          </Tag>
                          {card.latest_alert.title}
                        </Typography.Link>
                      )}
                      <Space style={{ marginTop: 12 }} wrap>
                        <Button
                          size="small" type="primary" data-testid={`ack-${card.code}`}
                          disabled={card.open_alerts === 0 || busy}
                          onClick={() => void confirmReceived(card)}
                        >
                          {zh ? "确认收到" : "Acknowledge"}
                        </Button>
                        <Button size="small" data-testid={`call-${card.code}`} onClick={() => setCallTarget(card)}>
                          {zh ? "呼叫质量人员" : "Call quality"}
                        </Button>
                      </Space>
                    </Card>
                  </Col>
                ))}
              </Row>
            )}
          </Col>
        </Row>
        <Modal
          open={Boolean(callTarget)}
          destroyOnClose
          title={callTarget ? `${zh ? "呼叫质量人员" : "Call quality staff"}：${callTarget.name}（${callTarget.code}）` : ""}
          okText={zh ? "呼叫" : "Call"}
          okButtonProps={{ disabled: reason.trim().length < 2, loading: busy }}
          onCancel={() => { setCallTarget(null); setReason(""); }}
          onOk={() => void sendCall()}
        >
          <Typography.Paragraph type="secondary">
            {zh ? "将通知该工位的责任人与项目负责人，并记录在审计日志里。请说明现场情况。" : "Notifies the station's responsible user and the project owner; the call is audited."}
          </Typography.Paragraph>
          <Input.TextArea
            aria-label={zh ? "呼叫原因" : "Reason"}
            rows={3}
            maxLength={500}
            value={reason}
            placeholder={zh ? "呼叫原因（必填）" : "Reason (required)"}
            onChange={(event) => setReason(event.target.value)}
          />
        </Modal>
      </V2PageFrame>
    </AppLayout>
  );
}
