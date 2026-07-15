import { describe, expect, it } from "vitest";

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
    "./api/training.test.ts",
    "./pages/TrainingJobsPage.test.tsx",
  ],
  4: [
    "./api/templates.test.ts",
    "./components/workspace/CustomNode.test.ts",
    "./components/workspace/NodeConfigPanel.test.tsx",
    "./pages/TemplateWizardPage.test.tsx",
  ],
};

const discoveredTestFiles = Object.keys(
  import.meta.glob("./**/*.test.{ts,tsx}"),
).concat("./weekAcceptance.test.ts").sort();

describe("Week 1-4 frontend acceptance manifest", () => {
  it("assigns every test file to exactly one development week", () => {
    const assigned = Object.values(weekTestFiles).flat();
    expect(new Set(assigned).size).toBe(assigned.length);
    expect(assigned.sort()).toEqual(discoveredTestFiles);
  });

  it("keeps every completed week represented", () => {
    for (const week of [1, 2, 3, 4]) {
      expect(weekTestFiles[week].length).toBeGreaterThan(0);
    }
  });
});
