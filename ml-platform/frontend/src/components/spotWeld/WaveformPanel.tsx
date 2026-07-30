import { useEffect, useRef } from "react";
import * as echarts from "echarts";

import type { QualityWaveforms } from "../../api/spotWeldQuality";

interface WaveformPanelProps {
  waveforms: QualityWaveforms;
}

const CHANNELS: Array<{ key: keyof QualityWaveforms; label: string; color: string }> = [
  { key: "current", label: "电流", color: "#1677ff" },
  { key: "voltage", label: "电压", color: "#13c2c2" },
  { key: "resistance", label: "电阻", color: "#722ed1" },
  { key: "power", label: "功率", color: "#fa8c16" },
];

export default function WaveformPanel({ waveforms }: WaveformPanelProps) {
  const chartRefs = useRef<Array<HTMLDivElement | null>>([]);

  useEffect(() => {
    const charts: echarts.ECharts[] = [];
    CHANNELS.forEach(({ key, label, color }, index) => {
      const element = chartRefs.current[index];
      if (!element) return;
      const chart = echarts.init(element);
      chart.setOption({
        animation: false,
        tooltip: { trigger: "axis" },
        grid: { left: 44, right: 18, top: 12, bottom: 34 },
        xAxis: { type: "category", data: waveforms[key].map((_, point) => point), boundaryGap: false },
        yAxis: { type: "value", scale: true },
        dataZoom: [
          { type: "inside", xAxisIndex: 0, filterMode: "none" },
          { type: "slider", xAxisIndex: 0, height: 18, bottom: 2 },
        ],
        series: [{ name: label, type: "line", showSymbol: false, data: waveforms[key], lineStyle: { color, width: 1.5 }, itemStyle: { color } }],
      });
      charts.push(chart);
    });

    const resize = () => charts.forEach((chart) => chart.resize());
    window.addEventListener("resize", resize);
    resize();
    return () => {
      window.removeEventListener("resize", resize);
      charts.forEach((chart) => chart.dispose());
    };
  }, [waveforms]);

  return (
    <div className="spot-weld-waveform-panel" aria-label="四通道波形图">
      {CHANNELS.map(({ key, label }, index) => (
        <section className="spot-weld-waveform-panel__channel" key={key} aria-labelledby={`waveform-${key}`}>
          <h4 id={`waveform-${key}`}>{label}</h4>
          <div
            className="spot-weld-waveform-panel__chart"
            ref={(element) => { chartRefs.current[index] = element; }}
            role="img"
            aria-label={`${label}波形`}
          />
        </section>
      ))}
    </div>
  );
}
