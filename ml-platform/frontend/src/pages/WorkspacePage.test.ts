import { describe, expect, it } from "vitest";
import { resolvePort } from "./WorkspacePage";

describe("workspace port persistence", () => {
  const ports = [{ name: "data" }, { name: "predictions" }];

  it("resolves indexed ReactFlow handles to operator port names", () => {
    expect(resolvePort("out-1", ports)).toBe("predictions");
  });

  it("preserves named and unknown handles", () => {
    expect(resolvePort("model", ports)).toBe("model");
    expect(resolvePort("out-9", ports)).toBe("out-9");
  });

  it("maps dynamic handle slots back to their logical port", () => {
    expect(resolvePort("data__slot_2", ports)).toBe("data");
  });
});
