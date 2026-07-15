import { describe, expect, it } from "vitest";

const productionModules = import.meta.glob(
  [
    "./api/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./i18n/*.{ts,tsx}",
    "./pages/*.{ts,tsx}",
    "./stores/*.{ts,tsx}",
    "!./**/*.test.{ts,tsx}",
  ],
  { eager: true },
);

describe("frontend module imports", () => {
  it("imports every application feature module", () => {
    expect(Object.keys(productionModules).length).toBeGreaterThanOrEqual(40);
    for (const [modulePath, moduleExports] of Object.entries(productionModules)) {
      expect(moduleExports, modulePath).toBeTruthy();
    }
  });
});
