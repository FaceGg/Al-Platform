import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

describe("platform branding", () => {
  it.each([
    "index.html",
    "src/i18n/index.tsx",
    "src/components/AppLayout.tsx",
    "src/pages/LoginPage.tsx",
    "src/pages/RegisterPage.tsx",
    "src/pages/DashboardPage.tsx",
  ])("uses 智擎 in %s", (path) => {
    expect(read(path)).toContain("智擎");
  });

  it("keeps the authenticated navigation assertion on the new brand", () => {
    expect(read("e2e/core-navigation.spec.ts")).toContain('toContainText("智擎")');
  });
});
