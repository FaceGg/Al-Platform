import { useCallback, useEffect, useState } from "react";
import { Alert, Select, Space } from "antd";
import type { MonitorScopeParams, StaleState } from "../../api/qualityMonitor";
import { getScopeOptions } from "../../api/qualityMonitor";
import type { QualityScene, QualityStation } from "../../api/qualityDomain";
import { useQualityAlertLookups } from "../../hooks/useQualityAlertLookups";
import { useI18n } from "../../i18n";
import { formatLocalTime } from "../../utils/time";

/** 监控三页共用的部分（F3，技术方案 §9B）：四级范围选择、陈旧数据横幅、格式化。 */

type ScopeKey = "factory" | "workshop" | "production_line" | "station_id" | "scene_id";

const EMPTY_OPTIONS = { factory: [], workshop: [], production_line: [] };

/** 四级范围的状态：选了上一级就清掉更下级的限定，避免出现互相矛盾的组合。 */
export function useMonitorScope() {
  const lookups = useQualityAlertLookups();
  const [scope, setScope] = useState<MonitorScopeParams>({});
  const [options, setOptions] = useState<{ factory: string[]; workshop: string[]; production_line: string[] }>(
    EMPTY_OPTIONS,
  );

  useEffect(() => {
    setScope({});
    setOptions(EMPTY_OPTIONS);
    if (!lookups.projectId) return;
    getScopeOptions(lookups.projectId).then(setOptions).catch(() => setOptions(EMPTY_OPTIONS));
  }, [lookups.projectId]);

  const setLevel = useCallback((key: ScopeKey, value: string | undefined) => {
    setScope((current) => {
      const next: MonitorScopeParams = { ...current };
      if (value) next[key] = value;
      else delete next[key];
      const order: ScopeKey[] = ["factory", "workshop", "production_line", "station_id"];
      for (const lower of order.slice(order.indexOf(key) + 1)) delete next[lower];
      return next;
    });
  }, []);

  return { ...lookups, scope, setLevel, options };
}

export function ScopeSelector({
  scope, options, scenes, stations, onChange,
}: {
  scope: MonitorScopeParams;
  options: { factory: string[]; workshop: string[]; production_line: string[] };
  scenes: QualityScene[];
  stations: QualityStation[];
  onChange: (key: ScopeKey, value: string | undefined) => void;
}) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  const level = (key: ScopeKey, label: string, values: string[]) => (
    <Select
      aria-label={label}
      allowClear
      style={{ minWidth: 120 }}
      placeholder={label}
      value={scope[key]}
      onChange={(value: string | undefined) => onChange(key, value)}
      options={values.map((item) => ({ value: item, label: item }))}
    />
  );
  const visibleStations = stations.filter(
    (station) => !scope.production_line || station.production_line === scope.production_line,
  );
  return (
    <Space wrap data-testid="scope-selector">
      {level("factory", zh ? "工厂" : "Factory", options.factory)}
      {level("workshop", zh ? "车间" : "Workshop", options.workshop)}
      {level("production_line", zh ? "产线" : "Line", options.production_line)}
      <Select
        aria-label={zh ? "工位" : "Station"}
        allowClear
        showSearch
        optionFilterProp="label"
        style={{ minWidth: 160 }}
        placeholder={zh ? "工位" : "Station"}
        value={scope.station_id}
        onChange={(value: string | undefined) => onChange("station_id", value)}
        options={visibleStations.map((station) => ({ value: station.id, label: `${station.name}（${station.code}）` }))}
      />
      <Select
        aria-label={zh ? "场景筛选" : "Scene filter"}
        allowClear
        style={{ minWidth: 160 }}
        placeholder={zh ? "场景" : "Scene"}
        value={scope.scene_id}
        onChange={(value: string | undefined) => onChange("scene_id", value)}
        options={scenes.map((scene) => ({ value: scene.id, label: `${scene.name}（${scene.code}）` }))}
      />
    </Space>
  );
}

/** 诚实设计①：距最后一次有产量超过 24 小时（或从未生产）时挂横幅。 */
export function StaleBanner({ stale }: { stale: StaleState | null | undefined }) {
  const { lang } = useI18n();
  const zh = lang === "zh";
  if (!stale?.stale) return null;
  return (
    <Alert
      type="warning"
      showIcon
      data-testid="stale-banner"
      style={{ marginBottom: 16 }}
      message={zh ? "数据可能已过期" : "Data may be stale"}
      description={stale.never_produced
        ? (zh ? "当前范围内还没有任何生产记录，下面的数字都是零，不代表产线状态。" : "No production recorded in this scope yet.")
        : (zh
          ? `距最后一次有产量已超过 ${Math.floor(stale.hours ?? 0)} 小时（最后生产时间 ${formatLocalTime(stale.last_production_at)}），页面数字可能不代表当前状态。`
          : `Last production was ${Math.floor(stale.hours ?? 0)} hours ago; numbers may not reflect the current state.`)}
    />
  );
}

export function percentText(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `${(value * 100).toFixed(1)}%`;
}

export function durationText(seconds: number | null | undefined, zh: boolean): string {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 60) return `${Math.round(seconds)} ${zh ? "秒" : "s"}`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} ${zh ? "分钟" : "min"}`;
  return `${(seconds / 3600).toFixed(1)} ${zh ? "小时" : "h"}`;
}
