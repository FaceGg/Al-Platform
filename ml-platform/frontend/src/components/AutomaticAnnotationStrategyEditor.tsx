import type { AnnotationOutputColumn } from "../api/models";

export type AutomaticRuleCondition = {
  id: string;
  field: string;
  operator: "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "in" | "not_in" | "is_null" | "not_null";
  value: string;
};

export type AutomaticRuleDraft = {
  id: string;
  priority: number;
  join: "all" | "any";
  conditions: AutomaticRuleCondition[];
  values: Record<string, string>;
  clusterIds: string;
};

export type AutomaticStrategyDraft = {
  strategy: "cluster" | "rule" | "cluster_rule";
  selectedClusters: string[];
  otherValues: Record<string, string>;
  clusterLabels: Record<string, Record<string, string>>;
  rules: AutomaticRuleDraft[];
};

export type ClusterOption = { clusterId: string; sampleCount: number };
export type AutomaticAnnotationSourceColumn = { name: string; dtype: string };

const operators: Array<[AutomaticRuleCondition["operator"], string]> = [
  ["eq", "等于"], ["neq", "不等于"], ["gt", ">"], ["gte", ">="],
  ["lt", "<"], ["lte", "<="], ["in", "属于"], ["not_in", "不属于"],
  ["is_null", "为空"], ["not_null", "非空"],
];

const nullOperators = new Set<AutomaticRuleCondition["operator"]>(["is_null", "not_null"]);

function ruleId() {
  return crypto.randomUUID();
}

export function createAutomaticRule(columns: AnnotationOutputColumn[]): AutomaticRuleDraft {
  return {
    id: ruleId(),
    priority: 0,
    join: "all",
    conditions: [{ id: ruleId(), field: "", operator: "eq", value: "" }],
    values: Object.fromEntries(columns.map((column) => [column.machine_key, ""])),
    clusterIds: "",
  };
}

export function createAutomaticStrategyDraft(columns: AnnotationOutputColumn[]): AutomaticStrategyDraft {
  return {
    strategy: "cluster",
    selectedClusters: [],
    otherValues: Object.fromEntries(columns.map((column) => [column.machine_key, ""])),
    clusterLabels: {},
    rules: [createAutomaticRule(columns)],
  };
}

type Props = {
  idPrefix: string;
  columns: AnnotationOutputColumn[];
  sourceColumns: AutomaticAnnotationSourceColumn[];
  value: AutomaticStrategyDraft;
  onChange: (next: AutomaticStrategyDraft) => void;
  clusters?: ClusterOption[];
};

export default function AutomaticAnnotationStrategyEditor({ idPrefix, columns, sourceColumns, value, onChange, clusters = [] }: Props) {
  const hasClusterMappings = clusters.length > 0 && (value.strategy === "cluster" || value.strategy === "cluster_rule");
  const updateRule = (ruleIdValue: string, update: Partial<AutomaticRuleDraft>) => {
    onChange({ ...value, rules: value.rules.map((rule) => rule.id === ruleIdValue ? { ...rule, ...update } : rule) });
  };
  const updateCondition = (ruleIdValue: string, conditionId: string, update: Partial<AutomaticRuleCondition>) => {
    const rule = value.rules.find((item) => item.id === ruleIdValue);
    if (!rule) return;
    updateRule(ruleIdValue, { conditions: rule.conditions.map((condition) => condition.id === conditionId ? { ...condition, ...update } : condition) });
  };
  const updateClusterSelection = (clusterId: string, selected: boolean) => {
    const selectedClusters = selected
      ? [...new Set([...value.selectedClusters, clusterId])]
      : value.selectedClusters.filter((item) => item !== clusterId);
    const clusterLabels = { ...value.clusterLabels };
    if (selected && !clusterLabels[clusterId]) {
      clusterLabels[clusterId] = Object.fromEntries(columns.map((column) => [column.machine_key, ""]));
    }
    if (!selected) delete clusterLabels[clusterId];
    onChange({ ...value, selectedClusters, clusterLabels });
  };

  return <div className="data-annotation__automatic-strategy" aria-label="自动标注策略配置">
    <div className="data-annotation__setup-field">
      <label htmlFor={`${idPrefix}-strategy`}>自动标注策略</label>
      <select id={`${idPrefix}-strategy`} aria-label="自动标注策略" value={value.strategy} onChange={(event) => onChange({ ...value, strategy: event.target.value as AutomaticStrategyDraft["strategy"] })}>
        <option value="cluster">按簇</option>
        <option value="rule">按规则</option>
        <option value="cluster_rule">簇加规则</option>
      </select>
    </div>
    <div className="data-annotation__automatic-values" aria-label="其他兜底值">
      {columns.map((column) => <div className="data-annotation__setup-field" key={column.machine_key}>
        <label htmlFor={`${idPrefix}-other-${column.machine_key}`}>其他 · {column.display_name}</label>
        <input
          id={`${idPrefix}-other-${column.machine_key}`}
          aria-label={`其他兜底值 ${column.display_name}`}
          type={column.value_type === "string" ? "text" : "number"}
          step={column.value_type === "float" ? "any" : "1"}
          value={value.otherValues[column.machine_key] || ""}
          onChange={(event) => onChange({ ...value, otherValues: { ...value.otherValues, [column.machine_key]: event.target.value } })}
        />
      </div>)}
    </div>
    {(value.strategy === "rule" || value.strategy === "cluster_rule") && <section className="data-annotation__automatic-rules" aria-label="规则配置">
      <div className="data-annotation__rules-head"><h3>规则</h3><button type="button" className="ant-btn ant-btn-sm" onClick={() => onChange({ ...value, rules: [...value.rules, createAutomaticRule(columns)] })}>添加规则</button></div>
      {value.rules.map((rule, ruleIndex) => <div className="data-annotation__annotation-rule" key={rule.id}>
        <div className="data-annotation__annotation-rule-head"><strong>规则 {ruleIndex + 1}</strong>{value.rules.length > 1 && <button type="button" className="ant-btn ant-btn-sm" aria-label={`删除规则 ${ruleIndex + 1}`} onClick={() => onChange({ ...value, rules: value.rules.filter((item) => item.id !== rule.id) })}>删除</button>}</div>
        <div className="data-annotation__automatic-rule-grid">
          <div className="data-annotation__setup-field"><label htmlFor={`${idPrefix}-rule-priority-${rule.id}`}>优先级</label><input id={`${idPrefix}-rule-priority-${rule.id}`} aria-label={`规则 ${ruleIndex + 1} 优先级`} type="number" step="1" value={rule.priority} onChange={(event) => updateRule(rule.id, { priority: Number(event.target.value) || 0 })} /></div>
          {rule.conditions.length > 1 && <div className="data-annotation__setup-field"><label htmlFor={`${idPrefix}-rule-join-${rule.id}`}>条件关系</label><select id={`${idPrefix}-rule-join-${rule.id}`} aria-label={`规则 ${ruleIndex + 1} 条件关系`} value={rule.join} onChange={(event) => updateRule(rule.id, { join: event.target.value as AutomaticRuleDraft["join"] })}><option value="all">AND</option><option value="any">OR</option></select></div>}
          {value.strategy === "cluster_rule" && <div className="data-annotation__setup-field"><label htmlFor={`${idPrefix}-rule-clusters-${rule.id}`}>规则簇过滤</label><input id={`${idPrefix}-rule-clusters-${rule.id}`} aria-label={`规则 ${ruleIndex + 1} 簇过滤`} value={rule.clusterIds} onChange={(event) => updateRule(rule.id, { clusterIds: event.target.value })} /></div>}
        </div>
        {rule.conditions.map((condition, conditionIndex) => <div className="data-annotation__automatic-rule-grid" key={condition.id}>
          <div className="data-annotation__setup-field"><label htmlFor={`${idPrefix}-condition-field-${condition.id}`}>条件字段</label><select id={`${idPrefix}-condition-field-${condition.id}`} aria-label={`规则 ${ruleIndex + 1} 条件 ${conditionIndex + 1} 字段`} value={condition.field} onChange={(event) => updateCondition(rule.id, condition.id, { field: event.target.value })}><option value="">选择字段</option>{sourceColumns.map((column) => <option value={column.name} key={column.name}>{column.name}</option>)}</select></div>
          <div className="data-annotation__setup-field"><label htmlFor={`${idPrefix}-condition-operator-${condition.id}`}>比较</label><select id={`${idPrefix}-condition-operator-${condition.id}`} aria-label={`规则 ${ruleIndex + 1} 条件 ${conditionIndex + 1} 比较`} value={condition.operator} onChange={(event) => updateCondition(rule.id, condition.id, { operator: event.target.value as AutomaticRuleCondition["operator"] })}>{operators.map(([operator, label]) => <option value={operator} key={operator}>{label}</option>)}</select></div>
          {!nullOperators.has(condition.operator) && <div className="data-annotation__setup-field"><label htmlFor={`${idPrefix}-condition-value-${condition.id}`}>比较值</label><input id={`${idPrefix}-condition-value-${condition.id}`} aria-label={`规则 ${ruleIndex + 1} 条件 ${conditionIndex + 1} 比较值`} value={condition.value} onChange={(event) => updateCondition(rule.id, condition.id, { value: event.target.value })} /></div>}
          {rule.conditions.length > 1 && <button type="button" className="ant-btn ant-btn-sm" aria-label={`删除规则 ${ruleIndex + 1} 条件 ${conditionIndex + 1}`} onClick={() => updateRule(rule.id, { conditions: rule.conditions.filter((item) => item.id !== condition.id) })}>删除条件</button>}
        </div>)}
        <button type="button" className="ant-btn ant-btn-sm" onClick={() => updateRule(rule.id, { conditions: [...rule.conditions, { id: ruleId(), field: "", operator: "eq", value: "" }] })}>添加条件</button>
        <div className="data-annotation__automatic-values" aria-label={`规则 ${ruleIndex + 1} 标签值`}>
          {columns.map((column) => <div className="data-annotation__setup-field" key={column.machine_key}>
            <label htmlFor={`${idPrefix}-rule-value-${rule.id}-${column.machine_key}`}>命中 · {column.display_name}</label>
            <input id={`${idPrefix}-rule-value-${rule.id}-${column.machine_key}`} aria-label={`规则 ${ruleIndex + 1} 命中 ${column.display_name}`} type={column.value_type === "string" ? "text" : "number"} step={column.value_type === "float" ? "any" : "1"} value={rule.values[column.machine_key] || ""} onChange={(event) => updateRule(rule.id, { values: { ...rule.values, [column.machine_key]: event.target.value } })} />
          </div>)}
        </div>
      </div>)}
    </section>}
    {hasClusterMappings && <section className="data-annotation__automatic-clusters" aria-label="簇映射">
      <h3>簇映射</h3>
      {clusters.map((cluster) => <div className="data-annotation__annotation-rule" key={cluster.clusterId}>
        <label><input type="checkbox" checked={value.selectedClusters.includes(cluster.clusterId)} onChange={(event) => updateClusterSelection(cluster.clusterId, event.target.checked)} />簇 {cluster.clusterId} · {cluster.sampleCount} 个样本</label>
        {value.selectedClusters.includes(cluster.clusterId) && <div className="data-annotation__automatic-values">
          {columns.map((column) => <div className="data-annotation__setup-field" key={column.machine_key}>
            <label htmlFor={`${idPrefix}-cluster-${cluster.clusterId}-${column.machine_key}`}>簇 {cluster.clusterId} · {column.display_name}</label>
            <input id={`${idPrefix}-cluster-${cluster.clusterId}-${column.machine_key}`} aria-label={`簇 ${cluster.clusterId} ${column.display_name}`} type={column.value_type === "string" ? "text" : "number"} step={column.value_type === "float" ? "any" : "1"} value={value.clusterLabels[cluster.clusterId]?.[column.machine_key] || ""} onChange={(event) => onChange({ ...value, clusterLabels: { ...value.clusterLabels, [cluster.clusterId]: { ...(value.clusterLabels[cluster.clusterId] || {}), [column.machine_key]: event.target.value } } })} />
          </div>)}
        </div>}
      </div>)}
    </section>}
  </div>;
}
