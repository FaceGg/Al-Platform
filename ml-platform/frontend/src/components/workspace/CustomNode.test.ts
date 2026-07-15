import { describe, expect, it } from "vitest";
import { formatResult } from "./CustomNode";

describe("port preview text", () => {
  it("formats tabular data in Chinese", () => {
    expect(formatResult([{ id: 1, value: "ok" }], "zh")).toContain("2 列 × 1 行");
  });

  it("uses localized empty and chart labels", () => {
    expect(formatResult(null, "zh")).toBe("暂无数据");
    expect(formatResult({ chart: true }, "en")).toBe("Chart (image)");
  });
});
