import type { ClusterOption } from "./AutomaticAnnotationStrategyEditor";

export type ClusterEvaluation = {
  selected_k?: number | string | null;
  k_scores?: Record<string, number> | null;
  evaluation_mode?: string | null;
  evaluation_sample_count?: number | string | null;
  total_sample_count?: number | string | null;
  importance_method?: string | null;
  scatter_points?: Array<[number, number, number]> | null;
};

export type ClusterScatterPoint = { x: number; y: number; clusterId: string };

const SCATTER_PALETTE = ["#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];
const SCATTER_VIEW_SIZE = 100;
const SCATTER_PADDING = 6;
const SCATTER_MAX_POINTS = 1000;

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

function clusterColor(clusters: ClusterOption[], clusterId: string): string {
  const index = Math.max(0, clusters.findIndex((cluster) => cluster.clusterId === clusterId));
  return SCATTER_PALETTE[index % SCATTER_PALETTE.length];
}

function normalizeScatterPoints(
  points: Array<[number, number, number]> | null | undefined,
): ClusterScatterPoint[] {
  if (!Array.isArray(points)) return [];
  const finite = points
    .filter((point) => Array.isArray(point) && point.length >= 3 && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])) && Number.isFinite(Number(point[2])))
    .slice(0, SCATTER_MAX_POINTS)
    .map((point) => ({ x: Number(point[0]), y: Number(point[1]), clusterId: String(point[2]) }));
  if (!finite.length) return [];
  const minX = Math.min(...finite.map((point) => point.x));
  const maxX = Math.max(...finite.map((point) => point.x));
  const minY = Math.min(...finite.map((point) => point.y));
  const maxY = Math.max(...finite.map((point) => point.y));
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  return finite.map((point) => ({
    clusterId: point.clusterId,
    x: SCATTER_PADDING + ((point.x - minX) / spanX) * (SCATTER_VIEW_SIZE - 2 * SCATTER_PADDING),
    y: SCATTER_VIEW_SIZE - SCATTER_PADDING - ((point.y - minY) / spanY) * (SCATTER_VIEW_SIZE - 2 * SCATTER_PADDING),
  }));
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
  const scatterPoints = normalizeScatterPoints(evaluation?.scatter_points);
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
      {scatterPoints.length > 0 && (
        <div className="data-annotation__cluster-preview-scatter" aria-label={lang === "zh" ? "聚类散点图" : "Cluster scatter"}>
          <svg
            viewBox={`0 0 ${SCATTER_VIEW_SIZE} ${SCATTER_VIEW_SIZE}`}
            role="img"
            aria-label={lang === "zh" ? "聚类分布散点图（前 1000 个评估样本，PCA 投影）" : "Cluster distribution scatter (first 1000 evaluation rows, PCA projection)"}
            preserveAspectRatio="xMidYMid meet"
          >
            {scatterPoints.map((point, index) => (
              <circle
                key={`${point.clusterId}-${index}`}
                cx={point.x}
                cy={point.y}
                r={0.9}
                fill={clusterColor(clusters, point.clusterId)}
                fillOpacity={0.75}
              />
            ))}
          </svg>
          <small>{lang === "zh" ? "散点取自轮廓系数评估样本（确定性哈希有序，最多 1000 点）的二维 PCA 投影，仅用于效果预览。" : "Points are the first 1000 silhouette-evaluation rows (deterministic hash order) projected to 2D via PCA; preview only."}</small>
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
