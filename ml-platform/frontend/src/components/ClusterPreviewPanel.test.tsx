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

  it("renders empty state metadata when no clusters exist", () => {
    render(<ClusterPreviewPanel clusters={[]} evaluation={null} lang="zh" />);
    expect(screen.getByText("簇数 K：—")).toBeTruthy();
    expect(document.querySelector(".data-annotation__cluster-preview-row")).toBeNull();
  });
});
