import { useEffect, useRef, useState } from "react";
import { Button, Popconfirm, Segmented, Spin, message } from "antd";
import { RestOutlined } from "@ant-design/icons";
import * as echarts from "echarts";
import apiClient from "../api/client";
import AppLayout from "../components/AppLayout";
import PageHeading from "../components/PageHeading";
import { useI18n } from "../i18n";

/** 系统管理 → Tokens 使用统计：聚合网关 egress 审计（仿对话式「使用统计」布局）。 */

interface DayBucket { date: string; calls: number; failed: number; prompt_tokens: number; completion_tokens: number }
interface ModelBucket { model: string; calls: number; failed: number; prompt_tokens: number; completion_tokens: number }
interface PurposeBucket { purpose: string; calls: number; failed: number; prompt_tokens: number; completion_tokens: number }
interface UsageStats {
  days: number;
  summary: {
    total_calls: number; failed_calls: number;
    prompt_tokens: number; completion_tokens: number; total_tokens: number;
    avg_latency_ms: number | null;
  };
  by_day: DayBucket[];
  by_model: ModelBucket[];
  by_purpose: PurposeBucket[];
}

const fmtTokens = (value: number): string =>
  value >= 1_000_000 ? `${(value / 1_000_000).toFixed(2)}M`
  : value >= 1_000 ? `${(value / 1_000).toFixed(1)}K`
  : String(value);

export default function LLMUsageStatsPage() {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const [days, setDays] = useState(7);
  const [stats, setStats] = useState<UsageStats | null>(null);
  const [loading, setLoading] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    setLoading(true);
    apiClient.get(`/llm-profiles/usage-stats`, { params: { days } })
      .then((res) => setStats(res.data))
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, [days]);

  const resetStats = async () => {
    try {
      await apiClient.post("/llm-profiles/usage-stats/reset");
      message.success(zh ? "已重置，将从现在重新统计" : "Statistics reset");
      setDays(7);
    } catch {
      message.error(zh ? "重置失败" : "Reset failed");
    }
  };

  useEffect(() => {
    if (!chartRef.current || !stats) return;
    const chart = echarts.getInstanceByDom(chartRef.current) ?? echarts.init(chartRef.current);
    chartInstance.current = chart;
    chart.setOption({
      tooltip: { trigger: "axis" },
      legend: { data: zh ? ["输入 tokens", "输出 tokens"] : ["Prompt", "Completion"], bottom: 0, textStyle: { fontSize: 11 } },
      // bottom 预留日期轴标签 + 图例两行的高度：34px 时两者挤在一起重叠（用户报障）
      grid: { left: 48, right: 16, top: 24, bottom: 64 },
      xAxis: { type: "category", data: stats.by_day.map((d) => d.date.slice(5)), axisLabel: { fontSize: 10 } },
      yAxis: { type: "value", axisLabel: { fontSize: 10 } },
      series: [
        { name: zh ? "输入 tokens" : "Prompt", type: "bar", stack: "t", data: stats.by_day.map((d) => d.prompt_tokens), itemStyle: { color: "#2f9bf5" }, barMaxWidth: 26 },
        { name: zh ? "输出 tokens" : "Completion", type: "bar", stack: "t", data: stats.by_day.map((d) => d.completion_tokens), itemStyle: { color: "#47c3a0" }, barMaxWidth: 26 },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [stats, zh]);

  const summary = stats?.summary;
  const cards = [
    { label: zh ? "总 Tokens" : "Total tokens", value: summary ? fmtTokens(summary.total_tokens) : "—", sub: summary ? `${zh ? "输入" : "in"} ${fmtTokens(summary.prompt_tokens)} · ${zh ? "输出" : "out"} ${fmtTokens(summary.completion_tokens)}` : "" },
    { label: zh ? "调用次数" : "Calls", value: summary ? String(summary.total_calls) : "—", sub: summary ? `${zh ? "失败" : "failed"} ${summary.failed_calls}` : "" },
    { label: zh ? "平均延迟" : "Avg latency", value: summary?.avg_latency_ms != null ? `${(summary.avg_latency_ms / 1000).toFixed(1)}s` : "—", sub: "" },
    { label: zh ? "统计范围" : "Window", value: `${stats?.days ?? days}${zh ? " 天" : "d"}`, sub: zh ? "tokens 自功能上线起记录" : "tokens recorded since launch" },
  ];

  return (
    <AppLayout>
      <PageHeading
        section="admin"
        navKey="llm_usage"
        desc={zh
          ? "大模型网关调用的用量聚合：tokens、调用次数、延迟与趋势（数据来自平台审计）。"
          : "Aggregated LLM gateway usage from the platform audit trail."}
        actions={(
          <>
            <Segmented
              value={days}
              onChange={(v) => setDays(v as number)}
              options={[
                { value: 1, label: zh ? "今天" : "Today" },
                { value: 7, label: zh ? "近 7 天" : "7d" },
                { value: 30, label: zh ? "近 30 天" : "30d" },
              ]}
            />
            <Popconfirm
              title={zh ? "重置统计？历史数据将不再计入，从现在重新统计。" : "Reset statistics?"}
              onConfirm={() => void resetStats()}
            >
              <Button icon={<RestOutlined />}>{zh ? "重置" : "Reset"}</Button>
            </Popconfirm>
          </>
        )}
      />

      <Spin spinning={loading}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12, marginBottom: 14 }}>
          {cards.map((card) => (
            <div key={card.label} className="v2-panel" style={{ margin: 0, padding: "12px 14px" }}>
              <div style={{ fontSize: 12, color: "var(--v2-dim)" }}>{card.label}</div>
              <div style={{ fontSize: 24, fontWeight: 700, color: "var(--v2-txt)", marginTop: 4 }}>{card.value}</div>
              {card.sub ? <div style={{ fontSize: 11.5, color: "var(--v2-dim)", marginTop: 2 }}>{card.sub}</div> : null}
            </div>
          ))}
        </div>

        <div className="v2-panel" style={{ margin: 0, marginBottom: 14 }}>
          <h4><span className="bar" />{zh ? "按天趋势" : "Daily trend"}</h4>
          {stats && stats.by_day.length > 0 ? (
            <div ref={chartRef} style={{ width: "100%", height: 260 }} />
          ) : (
            <div className="v2-empty" style={{ padding: 24 }}>{zh ? "该时间范围内暂无调用" : "No calls in this window"}</div>
          )}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 14, flexWrap: "wrap" }}>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "按模型" : "By model"}</h4>
            <table className="v2-table">
              <thead><tr>
                <th>{zh ? "模型" : "Model"}</th><th>{zh ? "调用" : "Calls"}</th>
                <th>{zh ? "失败" : "Failed"}</th><th>{zh ? "Tokens" : "Tokens"}</th>
              </tr></thead>
              <tbody>
                {(stats?.by_model ?? []).length === 0 ? (
                  <tr><td colSpan={4} className="v2-empty">—</td></tr>
                ) : stats?.by_model.map((row) => (
                  <tr key={row.model}>
                    <td className="tt">{row.model}</td>
                    <td>{row.calls}</td>
                    <td style={{ color: row.failed ? "var(--v2-red)" : undefined }}>{row.failed}</td>
                    <td>{fmtTokens(row.prompt_tokens + row.completion_tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="v2-panel" style={{ margin: 0 }}>
            <h4><span className="bar" />{zh ? "按用途" : "By purpose"}</h4>
            <table className="v2-table">
              <thead><tr>
                <th>{zh ? "用途" : "Purpose"}</th><th>{zh ? "调用" : "Calls"}</th><th>{zh ? "Tokens" : "Tokens"}</th>
              </tr></thead>
              <tbody>
                {(stats?.by_purpose ?? []).length === 0 ? (
                  <tr><td colSpan={3} className="v2-empty">—</td></tr>
                ) : stats?.by_purpose.map((row) => (
                  <tr key={row.purpose}>
                    <td>{row.purpose}</td>
                    <td>{row.calls}</td>
                    <td>{fmtTokens(row.prompt_tokens + row.completion_tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Spin>
    </AppLayout>
  );
}
