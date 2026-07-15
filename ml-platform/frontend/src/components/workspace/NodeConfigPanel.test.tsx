import { describe, expect, it } from "vitest";
import { getPortLabel } from "./NodeConfigPanel";

describe("operator parameter labels", () => {
  it("localizes join key labels for both supported languages", () => {
    expect(getPortLabel("join", "left_keys", "zh")).toBe("左侧键列（逗号分隔）");
    expect(getPortLabel("join", "right_keys", "en")).toBe("Right Key Columns (comma-separated)");
  });

  it("returns an empty label when a parameter has no special mapping", () => {
    expect(getPortLabel("join", "unknown", "zh")).toBeNull();
  });
});
