import type { ClusterOption } from "./AutomaticAnnotationStrategyEditor";

export type ClusterEvaluation = {
  selected_k?: number | string | null;
  k_scores?: Record<string, number> | null;
  evaluation_mode?: string | null;
  evaluation_sample_count?: number | string | null;
  total_sample_count?: number | string | null;
  importance_method?: string | null;
};

const numberFormatter = new Intl.NumberFormat("en-US");

function formatCount(value: number | string | null | undefined): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? numberFormatter.format(parsed) : "—";
}

function formatScore(value: unknown): string {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(3) : "—";
}

function evaluationModeLabel(mode: string | null | undefined, lang: string): string {
  if (mode === "all_rows") {
    return lang === "zh" ? "全量评分" : "Full-scope scoring";
  }
  if (mode === "deterministic_hash_sample") {
    return lang === "zh" ? "确定性抽样评分" : "Deterministic sampled scoring";
  }
  return mode || "—";
}

function importanceMethodLabel(method: string | null | undefined, lang: string): string {
  if (method === "estimator_native") {
    return lang === "zh" ? "模型原生重要性" : "Native importance";
  }
  if (method === "permutation") {
    return lang === "zh" ? "置换重要性" : "Permutation importance";
  }
  if (method && method.startsWith("one_hot_aggregated")) {
    return lang === "zh" ? "独热聚合重要性" : "One-hot aggregated importance";
  }
  if (method === "frozen_artifact") {
    return lang === "zh" ? "冻结工件重要性" : "Frozen artifact importance";
  }
  return method || "—";
}

export default function ClusterPreviewPanel({
  clusters,
  evaluation,
  lang,
}: {
  clusters: ClusterOption[];
  evaluation?: ClusterEvaluation | null;
  lang: string;
}) {
  const totalCount = clusters.reduce((sum, cluster) => sum + (Number.isFinite(cluster.sampleCount) ? cluster.sampleCount : 0), 0);
  const kScores = evaluation?.k_scores && typeof evaluation.k_scores === "object" ? evaluation.k_scores : {};
  const sortedScores = Object.entries(kScores)
    .map(([k, score]) => ({ k, score: Number(score) }))
    .filter((item) => Number.isFinite(item.score))
    .sort((left, right) => Number(left.k) - Number(right.k));
  return (
    <div className="data-annotation__cluster-preview" aria-label={lang === "zh" ? "聚类预览效果" : "Cluster preview"}>
      <div className="data-annotation__cluster-preview-meta">
        <span>{lang === "zh" ? `簇数 K：${evaluation?.selected_k ?? "—"}` : `Selected K: ${evaluation?.selected_k ?? "—"}`}</span>
        <span>{lang === "zh" ? "评估方式：" : "Evaluation: "}{evaluationModeLabel(evaluation?.evaluation_mode, lang)}</span>
        <span>
          {lang === "zh" ? "评估样本：" : "Evaluation rows: "}
          {formatCount(evaluation?.evaluation_sample_count ?? null)}
          {evaluation?.total_sample_count != null && Number(evaluation.total_sample_count) > 0
            ? ` / ${formatCount(evaluation.total_sample_count)}`
            : ""}
        </span>
        <span>{lang === "zh" ? "权重来源：" : "Weights: "}{importanceMethodLabel(evaluation?.importance_method, lang)}</span>
      </div>
      {sortedScores.length > 0 && (
        <div className="data-annotation__cluster-preview-scores">
          {sortedScores.map((item) => (
            <span
              key={item.k}
              className={`data-annotation__cluster-preview-score${String(evaluation?.selected_k) === item.k ? " data-annotation__cluster-preview-score--selected" : ""}`}
            >
              K={item.k}: {formatScore(item.score)}
            </span>
          ))}
        </div>
      )}
      <ul className="data-annotation__cluster-preview-bars">
        {clusters.map((cluster) => {
          const share = totalCount > 0 ? (cluster.sampleCount / totalCount) * 100 : 0;
          return (
            <li className="data-annotation__cluster-preview-row" key={cluster.clusterId}>
              <span className="data-annotation__cluster-preview-label">{lang === "zh" ? `簇 ${cluster.clusterId}` : `Cluster ${cluster.clusterId}`}</span>
              <span className="data-annotation__cluster-preview-bar-track" aria-hidden="true">
                <span className="data-annotation__cluster-preview-bar" style={{ width: `${Math.min(100, Math.max(0, share))}%` }} />
              </span>
              <span className="data-annotation__cluster-preview-count">
                {numberFormatter.format(cluster.sampleCount)} ({share.toFixed(1)}%)
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
