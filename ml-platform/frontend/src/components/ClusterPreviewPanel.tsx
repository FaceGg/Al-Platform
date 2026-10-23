import type { ClusterOption } from "./AutomaticAnnotationStrategyEditor";

export type ClusterEvaluation = {
  selected_k?: number | string | null;
  k_scores?: Record<string, number> | null;
  evaluation_mode?: string | null;
  evaluation_sample_count?: number | string | null;
  total_sample_count?: number | string | null;
  importance_method?: string | null;
  scatter_points?: Array<[number, number, number]> | null;
  /** 散点轴标签：KMeans 为 "PC1 (32.9%)" 等解释方差，UMAP 路径为 "UMAP-1/2" */
  scatter_axes?: { x?: string; y?: string } | null;
  /** weighted_kmeans（默认，轮廓系数选 K）或 umap_hdbscan（密度聚类自动定簇，含噪声点） */
  cluster_method?: string | null;
  noise_count?: number | string | null;
};

export type ClusterScatterPoint = { x: number; y: number; clusterId: string };

const SCATTER_PALETTE = ["#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];
const NOISE_COLOR = "#9ca3af";
// 图表化散点尺寸：绘图区 + 坐标轴/刻度/轴标签边距
const SCATTER_W = 440;
const SCATTER_H = 300;
const PAD_L = 52;
const PAD_R = 14;
const PAD_T = 34;
const PAD_B = 40;
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
  // 噪声点（-1）独立灰色，避免与簇 0 的蓝色混淆造成"两簇交错"的误读
  if (clusterId === "-1") return NOISE_COLOR;
  const index = Math.max(0, clusters.findIndex((cluster) => cluster.clusterId === clusterId));
  return SCATTER_PALETTE[index % SCATTER_PALETTE.length];
}

type ScatterPlot = {
  points: ClusterScatterPoint[];
  xTicks: Array<{ pos: number; label: string }>;
  yTicks: Array<{ pos: number; label: string }>;
};

function formatTick(value: number): string {
  const rounded = Math.abs(value) >= 100 ? Math.round(value) : Number(value.toFixed(1));
  return String(rounded);
}

function buildScatterPlot(
  points: Array<[number, number, number]> | null | undefined,
): ScatterPlot {
  if (!Array.isArray(points)) return { points: [], xTicks: [], yTicks: [] };
  const finite = points
    .filter((point) => Array.isArray(point) && point.length >= 3 && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])) && Number.isFinite(Number(point[2])))
    .slice(0, SCATTER_MAX_POINTS)
    .map((point) => ({ x: Number(point[0]), y: Number(point[1]), clusterId: String(point[2]) }));
  if (!finite.length) return { points: [], xTicks: [], yTicks: [] };
  const minX = Math.min(...finite.map((point) => point.x));
  const maxX = Math.max(...finite.map((point) => point.x));
  const minY = Math.min(...finite.map((point) => point.y));
  const maxY = Math.max(...finite.map((point) => point.y));
  const spanX = maxX - minX || 1;
  const spanY = maxY - minY || 1;
  const plotW = SCATTER_W - PAD_L - PAD_R;
  const plotH = SCATTER_H - PAD_T - PAD_B;
  const toX = (value: number) => PAD_L + ((value - minX) / spanX) * plotW;
  const toY = (value: number) => SCATTER_H - PAD_B - ((value - minY) / spanY) * plotH;
  const tickValues = (min: number, max: number) => [min, min + (max - min) / 2, max];
  return {
    points: finite.map((point) => ({ clusterId: point.clusterId, x: toX(point.x), y: toY(point.y) })),
    xTicks: tickValues(minX, maxX).map((value) => ({ pos: toX(value), label: formatTick(value) })),
    yTicks: tickValues(minY, maxY).map((value) => ({ pos: toY(value), label: formatTick(value) })),
  };
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
  const isDensityMethod = evaluation?.cluster_method === "umap_hdbscan";
  const noiseCount = Number(evaluation?.noise_count ?? 0);
  const kScores = evaluation?.k_scores && typeof evaluation.k_scores === "object" ? evaluation.k_scores : {};
  const sortedScores = Object.entries(kScores)
    .map(([k, score]) => ({ k, score: Number(score) }))
    .filter((item) => Number.isFinite(item.score))
    .sort((left, right) => Number(left.k) - Number(right.k));
  const scatterPlot = buildScatterPlot(evaluation?.scatter_points);
  const scatterAxes = evaluation?.scatter_axes || {};
  const scatterTitle = isDensityMethod
    ? (lang === "zh"
      ? `UMAP + HDBSCAN 聚类（${evaluation?.selected_k ?? "?"} 簇，${formatCount(evaluation?.noise_count ?? 0)} 噪声）`
      : `UMAP + HDBSCAN Clustering (${evaluation?.selected_k ?? "?"} clusters, ${formatCount(evaluation?.noise_count ?? 0)} noise)`)
    : (lang === "zh"
      ? `KMeans 聚类（K=${evaluation?.selected_k ?? "?"}）`
      : `KMeans Clustering (K=${evaluation?.selected_k ?? "?"})`);
  const axisXLabel = scatterAxes.x || (isDensityMethod ? "UMAP-1" : "PC1");
  const axisYLabel = scatterAxes.y || (isDensityMethod ? "UMAP-2" : "PC2");
  return (
    <div className="data-annotation__cluster-preview" aria-label={lang === "zh" ? "聚类预览效果" : "Cluster preview"}>
      <div className="data-annotation__cluster-preview-body">
        <div className="data-annotation__cluster-preview-charts">
          {scatterPlot.points.length > 0 && (
            <div className="data-annotation__cluster-preview-scatter" aria-label={lang === "zh" ? "聚类散点图" : "Cluster scatter"}>
              <svg
                viewBox={`0 0 ${SCATTER_W} ${SCATTER_H}`}
                role="img"
                aria-label={lang === "zh" ? `${scatterTitle}散点图` : `${scatterTitle} scatter`}
                preserveAspectRatio="xMidYMid meet"
                style={{ width: "100%", height: "auto" }}
              >
                <text x={(PAD_L + SCATTER_W - PAD_R) / 2} y={16} textAnchor="middle" fontSize={13} fontWeight={600} fill="currentColor">
                  {scatterTitle}
                </text>
                {/* 坐标轴 */}
                <line x1={PAD_L} y1={PAD_T} x2={PAD_L} y2={SCATTER_H - PAD_B} stroke="currentColor" strokeWidth={0.8} />
                <line x1={PAD_L} y1={SCATTER_H - PAD_B} x2={SCATTER_W - PAD_R} y2={SCATTER_H - PAD_B} stroke="currentColor" strokeWidth={0.8} />
                {scatterPlot.xTicks.map((tick) => (
                  <g key={`x-${tick.label}`}>
                    <line x1={tick.pos} y1={SCATTER_H - PAD_B} x2={tick.pos} y2={SCATTER_H - PAD_B + 4} stroke="currentColor" strokeWidth={0.8} />
                    <text x={tick.pos} y={SCATTER_H - PAD_B + 14} textAnchor="middle" fontSize={9} fill="currentColor" opacity={0.65}>{tick.label}</text>
                  </g>
                ))}
                {scatterPlot.yTicks.map((tick) => (
                  <g key={`y-${tick.label}`}>
                    <line x1={PAD_L - 4} y1={tick.pos} x2={PAD_L} y2={tick.pos} stroke="currentColor" strokeWidth={0.8} />
                    <text x={PAD_L - 6} y={tick.pos + 3} textAnchor="end" fontSize={9} fill="currentColor" opacity={0.65}>{tick.label}</text>
                  </g>
                ))}
                <text x={(PAD_L + SCATTER_W - PAD_R) / 2} y={SCATTER_H - 6} textAnchor="middle" fontSize={10} fill="currentColor" opacity={0.75}>
                  {axisXLabel}
                </text>
                <text x={12} y={(PAD_T + SCATTER_H - PAD_B) / 2} textAnchor="middle" fontSize={10} fill="currentColor" opacity={0.75} transform={`rotate(-90 12 ${(PAD_T + SCATTER_H - PAD_B) / 2})`}>
                  {axisYLabel}
                </text>
                {/* 散点：噪声灰、其余按簇色 */}
                {scatterPlot.points.map((point, index) => (
                  <circle
                    key={`${point.clusterId}-${index}`}
                    cx={point.x}
                    cy={point.y}
                    r={2.4}
                    fill={clusterColor(clusters, point.clusterId)}
                    fillOpacity={0.75}
                  />
                ))}
                {/* 图例：右上角，簇 + 噪声 */}
                {clusters.map((cluster, index) => {
                  const legendY = PAD_T + 12 + index * 14;
                  const color = clusterColor(clusters, cluster.clusterId);
                  return (
                    <g key={`legend-${cluster.clusterId}`}>
                      <circle cx={SCATTER_W - PAD_R - 78} cy={legendY - 3} r={3} fill={color} fillOpacity={0.85} />
                      <text x={SCATTER_W - PAD_R - 70} y={legendY} fontSize={9.5} fill="currentColor">
                        {lang === "zh" ? `簇 ${cluster.clusterId} (n=${numberFormatter.format(cluster.sampleCount)})` : `Cluster ${cluster.clusterId} (n=${numberFormatter.format(cluster.sampleCount)})`}
                      </text>
                    </g>
                  );
                })}
                {isDensityMethod && noiseCount > 0 && (
                  <g>
                    <circle cx={SCATTER_W - PAD_R - 78} cy={PAD_T + 12 + clusters.length * 14 - 3} r={3} fill={NOISE_COLOR} fillOpacity={0.85} />
                    <text x={SCATTER_W - PAD_R - 70} y={PAD_T + 12 + clusters.length * 14} fontSize={9.5} fill="currentColor">
                      {lang === "zh" ? `噪声 (n=${numberFormatter.format(noiseCount)})` : `Noise (n=${numberFormatter.format(noiseCount)})`}
                    </text>
                  </g>
                )}
              </svg>
              <small>{isDensityMethod
                ? (lang === "zh"
                  ? "散点为 UMAP 嵌入空间（聚类实际发生空间）的前两维投影（最多 1000 点）；灰色 = 噪声点（不归属任何簇，按 needs_review 处理），彩色 = 所属簇。仅用于效果预览。"
                  : "First two dims of the UMAP embedding (the space clustering ran in), up to 1000 points; gray = noise (unassigned, needs_review), colors = clusters. Preview only.")
                : (lang === "zh" ? "散点取自轮廓系数评估样本（确定性哈希有序，最多 1000 点）的二维 PCA 投影，仅用于效果预览。" : "Points are the first 1000 silhouette-evaluation rows (deterministic hash order) projected to 2D via PCA; preview only.")}</small>
            </div>
          )}
          <ul className="data-annotation__cluster-preview-bars">
            {clusters.map((cluster) => {
              const share = totalCount > 0 ? (cluster.sampleCount / totalCount) * 100 : 0;
              return (
                <li className="data-annotation__cluster-preview-row" key={cluster.clusterId}>
                  <span className="data-annotation__cluster-preview-label">{lang === "zh" ? `簇 ${cluster.clusterId}` : `Cluster ${cluster.clusterId}`}</span>
                  <span className="data-annotation__cluster-preview-bar-track" aria-hidden="true">
                    <span className="data-annotation__cluster-preview-bar" style={{ width: `${Math.min(100, Math.max(0, share))}%`, background: clusterColor(clusters, cluster.clusterId) }} />
                  </span>
                  <span className="data-annotation__cluster-preview-count">
                    {numberFormatter.format(cluster.sampleCount)} ({share.toFixed(1)}%)
                  </span>
                </li>
              );
            })}
            {isDensityMethod && noiseCount > 0 && (
              <li className="data-annotation__cluster-preview-row" key="noise">
                <span className="data-annotation__cluster-preview-label">{lang === "zh" ? "噪声" : "Noise"}</span>
                <span className="data-annotation__cluster-preview-bar-track" aria-hidden="true">
                  <span className="data-annotation__cluster-preview-bar" style={{ width: `${Math.min(100, (noiseCount / Math.max(1, totalCount + noiseCount)) * 100)}%`, background: "#9ca3af" }} />
                </span>
                <span className="data-annotation__cluster-preview-count">
                  {numberFormatter.format(noiseCount)}
                </span>
              </li>
            )}
          </ul>
        </div>
        <div className="data-annotation__cluster-preview-info">
          <div className="data-annotation__cluster-preview-meta">
            {isDensityMethod
              ? <span>{lang === "zh" ? `簇数自动确定：K=${evaluation?.selected_k ?? "—"}` : `Auto-selected K: ${evaluation?.selected_k ?? "—"}`}</span>
              : <span>{lang === "zh" ? `簇数 K：${evaluation?.selected_k ?? "—"}` : `Selected K: ${evaluation?.selected_k ?? "—"}`}</span>}
            {isDensityMethod && Number(evaluation?.noise_count ?? 0) > 0 && (
              <span>{lang === "zh" ? `噪声点：${formatCount(evaluation?.noise_count ?? null)}（不参与簇选择，落 needs_review）` : `Noise: ${formatCount(evaluation?.noise_count ?? null)} (excluded from selection)`}</span>
            )}
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
        </div>
      </div>
    </div>
  );
}
