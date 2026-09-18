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

  it("renders the deterministic scatter projection with per-cluster colors", () => {
    render(
      <ClusterPreviewPanel
        clusters={clusters}
        evaluation={{ scatter_points: [[0.0, 0.0, 0], [1.0, 1.0, 1], [2.0, 0.5, 0]] }}
        lang="zh"
      />,
    );
    expect(screen.getByLabelText("聚类散点图")).toBeTruthy();
    const circles = document.querySelectorAll(".data-annotation__cluster-preview-scatter circle");
    expect(circles.length).toBe(3);
    const fills = new Set(Array.from(circles).map((circle) => circle.getAttribute("fill")));
    expect(fills.size).toBe(2);
    // Min-max normalization maps the corner points to the padded viewBox.
    const first = circles[0];
    expect(Number(first.getAttribute("cx"))).toBeCloseTo(6, 5);
    expect(Number(first.getAttribute("cy"))).toBeCloseTo(94, 5);
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
