import { describe, expect, it } from "vitest";

const weekTestFiles: Record<number, string[]> = {
  1: [
    "./api/auth.test.ts",
    "./api/client.test.ts",
    "./components/AppLayout.test.tsx",
    "./components/PageErrorBoundary.test.tsx",
    "./pages/KnowledgeBasePage.test.tsx",
    "./pages/KnowledgeGraphPage.test.tsx",
    "./pages/UserManagementPage.test.tsx",
    "./moduleImports.test.ts",
    "./stores/themeContext.test.tsx",
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
    "./components/workspace/CustomNode.test.tsx",
    "./components/workspace/NodeConfigPanel.export.test.tsx",
    "./components/workspace/NodeConfigPanel.test.tsx",
    "./components/workspace/NodeConfigPanel.join.test.tsx",
    "./components/workspace/NodeConfigPanel.required.test.tsx",
    "./components/workspace/OperatorPanel.test.tsx",
    "./components/workspace/workflowExport.test.ts",
    "./pages/TemplateWizardPage.test.tsx",
  ],
  6: [
    "./api/experiments.test.ts",
    "./pages/AutoMLPage.test.tsx",
  ],
  8: [
    "./api/modelRegistry.test.ts",
    "./pages/ModelLibraryPage.test.tsx",
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
    for (const week of [1, 2, 3, 4, 6, 8]) {
      expect(weekTestFiles[week].length).toBeGreaterThan(0);
    }
  });
});
