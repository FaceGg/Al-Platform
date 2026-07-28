import { describe, expect, it } from "vitest";
import { translations } from "./i18n";

const weekTestFiles: Record<number, string[]> = {
  1: [
    "./api/auth.test.ts",
    "./api/client.test.ts",
    "./components/AppLayout.test.tsx",
    "./moduleImports.test.ts",
    "./weekAcceptance.test.ts",
  ],
  2: [
    "./api/workflowVersions.test.ts",
    "./pages/WorkspacePage.test.ts",
    "./stores/workflowStore.test.ts",
  ],
  3: [
    "./api/datasets.test.ts",
    "./api/training.test.ts",
    "./pages/DataManagePage.test.tsx",
    "./pages/TrainingJobsPage.test.tsx",
  ],
  4: [
    "./api/templates.test.ts",
    "./components/workspace/CustomNode.test.ts",
    "./components/workspace/NodeConfigPanel.test.tsx",
    "./pages/TemplateWizardPage.test.tsx",
  ],
  6: [
    "./api/experiments.test.ts",
  ],
  8: [
    "./api/modelRegistry.test.ts",
    "./pages/ModelLibraryPage.test.tsx",
  ],
  10: [
    "./api/securityNotifications.test.ts",
    "./components/NotificationCenter.test.tsx",
    "./pages/ProjectDetailPage.test.tsx",
    "./pages/ProjectGovernanceTabs.test.tsx",
  ],
};

const discoveredTestFiles = Object.keys(
  import.meta.glob("./**/*.test.{ts,tsx}"),
).concat("./weekAcceptance.test.ts").sort();

describe("frontend acceptance manifest", () => {
  it("assigns every test file to exactly one development week", () => {
    const assigned = Object.values(weekTestFiles).flat();
    expect(new Set(assigned).size).toBe(assigned.length);
    expect(assigned.sort()).toEqual(discoveredTestFiles);
  });

  it("keeps every completed week represented", () => {
    for (const week of [1, 2, 3, 4, 6, 8, 10]) {
      expect(weekTestFiles[week].length).toBeGreaterThan(0);
    }
  });

  it("keeps security notification and project governance translations symmetric", () => {
    const paths = (value: Record<string, unknown>, prefix = ""): string[] => Object.entries(value)
      .flatMap(([key, child]) => {
        const path = prefix ? `${prefix}.${key}` : key;
        return child && typeof child === "object" && !Array.isArray(child)
          ? paths(child as Record<string, unknown>, path)
          : [path];
      })
      .sort();

    for (const section of ["securityNotifications", "projectGovernance"] as const) {
      expect(translations.zh[section]).toBeDefined();
      expect(paths(translations.zh[section])).toEqual(paths(translations.en[section]));
    }
  });
});
