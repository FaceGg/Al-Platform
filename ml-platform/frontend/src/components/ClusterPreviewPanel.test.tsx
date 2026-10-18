import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ClusterPreviewPanel from "./ClusterPreviewPanel";

const clusters = [
  { clusterId: "0", sampleCount: 30 },
  { clusterId: "1", sampleCount: 10 },
];

describe("ClusterPreviewPanel", () => {
  it("renders per-cluster share bars with counts and percentages", () => {
    render(<ClusterPreviewPanel clusters={clusters} evaluation={null} lang="zh" />);
    expect(screen.getByText("簇 0")).toBeTruthy();
    expect(screen.getByText("簇 1")).toBeTruthy();
    expect(screen.getByText("30 (75.0%)")).toBeTruthy();
    expect(screen.getByText("10 (25.0%)")).toBeTruthy();
    const bar = document.querySelector<HTMLElement>(".data-annotation__cluster-preview-bar");
    expect(bar?.style.width).toBe("75%");
  });

  it("renders frozen evaluation metadata including selected K and scores", () => {
    render(
      <ClusterPreviewPanel
        clusters={clusters}
        evaluation={{
          selected_k: 2,
          k_scores: { "2": 0.5123, "3": 0.4211 },
          evaluation_mode: "deterministic_hash_sample",
          evaluation_sample_count: 50000,
          total_sample_count: 120000,
          importance_method: "permutation",
        }}
        lang="zh"
      />,
    );
    expect(screen.getByText("簇数 K：2")).toBeTruthy();
    expect(screen.getByText(/确定性抽样评分/)).toBeTruthy();
    expect(screen.getByText(/50,000 \/ 120,000/)).toBeTruthy();
    expect(screen.getByText(/K=2: 0.512/)).toBeTruthy();
    expect(screen.getByText(/K=3: 0.421/)).toBeTruthy();
    expect(screen.getByText(/权重来源：置换重要性/)).toBeTruthy();
    const selected = document.querySelector(".data-annotation__cluster-preview-score--selected");
    expect(selected?.textContent).toContain("K=2");
  });

  it("renders English labels when lang is en", () => {
    render(<ClusterPreviewPanel clusters={clusters} evaluation={{ evaluation_mode: "all_rows" }} lang="en" />);
    expect(screen.getByText("Cluster 0")).toBeTruthy();
    expect(screen.getByText(/Full-scope scoring/)).toBeTruthy();
  });

  it("renders the chart-style scatter with axes, title and colored legend", () => {
    render(
      <ClusterPreviewPanel
        clusters={clusters}
        evaluation={{
          scatter_points: [[0.0, 0.0, 0], [1.0, 1.0, 1], [2.0, 0.5, 0]],
          selected_k: 2,
          scatter_axes: { x: "PC1 (32.9%)", y: "PC2 (16.4%)" },
        }}
        lang="zh"
      />,
    );
    expect(screen.getByLabelText("聚类散点图")).toBeTruthy();
    // 图表标题与轴标签（PCA 解释方差）
    expect(screen.getByText("KMeans 聚类（K=2）")).toBeTruthy();
    expect(screen.getByText("PC1 (32.9%)")).toBeTruthy();
    expect(screen.getByText("PC2 (16.4%)")).toBeTruthy();
    // 散点圆 + 图例圆（每簇 1 个图例点）
    const circles = document.querySelectorAll(".data-annotation__cluster-preview-scatter circle");
    expect(circles.length).toBe(3 + 2);
    const fills = new Set(
      Array.from(circles)
        .slice(0, 3)
        .map((circle) => circle.getAttribute("fill")),
    );
    expect(fills.size).toBe(2);
    // 图例含每簇计数
    expect(screen.getByText("簇 0 (n=30)")).toBeTruthy();
    expect(screen.getByText("簇 1 (n=10)")).toBeTruthy();
  });

  it("renders density scatter title with noise count and gray noise legend", () => {
    render(
      <ClusterPreviewPanel
        clusters={[{ clusterId: "0", sampleCount: 26 }, { clusterId: "1", sampleCount: 56 }]}
        evaluation={{
          cluster_method: "umap_hdbscan",
          selected_k: 2,
          noise_count: 19,
          scatter_points: [[0, 0, 0], [1, 1, 1], [2, 2, -1]],
          scatter_axes: { x: "UMAP-1", y: "UMAP-2" },
        }}
        lang="zh"
      />,
    );
    expect(screen.getByText("UMAP + HDBSCAN 聚类（2 簇，19 噪声）")).toBeTruthy();
    expect(screen.getByText("UMAP-1")).toBeTruthy();
    expect(screen.getByText("UMAP-2")).toBeTruthy();
    expect(screen.getByText("噪声 (n=19)")).toBeTruthy();
    // 噪声散点为灰色
    const noiseCircle = Array.from(document.querySelectorAll(".data-annotation__cluster-preview-scatter circle"))
      .find((circle) => circle.getAttribute("fill") === "#9ca3af");
    expect(noiseCircle).toBeTruthy();
  });

  it("ignores malformed scatter points", () => {
    render(
      <ClusterPreviewPanel
        clusters={clusters}
        evaluation={{ scatter_points: [[Number.NaN, 0, 0] as [number, number, number], [1, "x", 0] as unknown as [number, number, number]] }}
        lang="zh"
      />,
    );
    expect(document.querySelector(".data-annotation__cluster-preview-scatter")).toBeNull();
  });

  it("renders empty state metadata when no clusters exist", () => {
    render(<ClusterPreviewPanel clusters={[]} evaluation={null} lang="zh" />);
    expect(screen.getByText("簇数 K：—")).toBeTruthy();
    expect(document.querySelector(".data-annotation__cluster-preview-row")).toBeNull();
  });
});
