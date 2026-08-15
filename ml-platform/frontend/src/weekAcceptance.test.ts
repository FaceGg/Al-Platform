import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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
  12: [
    "./api/spotWeldQuality.test.ts",
    "./components/AppLayoutUsername.test.tsx",
    "./components/PageErrorBoundary.test.tsx",
    "./components/spotWeld/WaveformPanel.test.tsx",
    "./components/workspace/CustomNode.test.tsx",
    "./components/workspace/NodeConfigPanel.export.test.tsx",
    "./components/workspace/NodeConfigPanel.join.test.tsx",
    "./components/workspace/NodeConfigPanel.required.test.tsx",
    "./components/workspace/OperatorPanel.test.tsx",
    "./components/workspace/workflowExport.test.ts",
    "./pages/AutoMLPage.test.tsx",
    "./pages/DashboardPage.test.tsx",
    "./pages/DataAnnotationPage.test.tsx",
    "./pages/KnowledgeBasePage.test.tsx",
    "./pages/KnowledgeGraphPage.test.tsx",
    "./pages/LoginPage.test.tsx",
    "./pages/MonitorPage.test.tsx",
    "./pages/ProjectListPage.test.tsx",
    "./pages/UserManagementPage.test.tsx",
    "./stores/themeContext.test.tsx",
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

  it("uses an explicit, overrideable Python command for browser acceptance", () => {
    const config = readFileSync(resolve(process.cwd(), "playwright.config.ts"), "utf-8");
    const resolver = readFileSync(
      resolve(process.cwd(), "e2e", "pythonExecutable.ts"),
      "utf-8",
    );

    expect(resolver).toContain("ML_PLATFORM_PYTHON");
    expect(config).toContain("const pythonCommand");
    expect(config).toContain("`${pythonCommand} -m uvicorn app.main:app");
    expect(config).toContain("`${pythonCommand} -m uvicorn app.inference_runtime.app");
  });

  it("uses one overrideable Python resolver for browser services and fixtures", () => {
    const config = readFileSync(resolve(process.cwd(), "playwright.config.ts"), "utf-8");
    const fixture = readFileSync(
      resolve(process.cwd(), "e2e", "model-inference.spec.ts"),
      "utf-8",
    );

    expect(config).toContain('from "./e2e/pythonExecutable"');
    expect(fixture).toContain('from "./pythonExecutable"');
    expect(fixture).toContain("resolveE2ePython()");
    expect(fixture).not.toContain('execFileSync("python"');
  });

  it("uses an explicit external Week 12 stack without starting local browser services", () => {
    const config = readFileSync(resolve(process.cwd(), "playwright.config.ts"), "utf-8");

    expect(config).toContain(
      'const externalAcceptanceBaseUrl = process.env.WEEK12_ACCEPTANCE_BASE_URL?.trim();',
    );
    expect(config).toContain(
      'const useExternalAcceptanceStack = process.env.RUN_WEEK12_BROWSER_ACCEPTANCE === "1"',
    );
    expect(config).toContain("webServer: useExternalAcceptanceStack ? undefined : [");
    expect(config).toContain('outputDir: externalAcceptanceEvidenceDir');
    expect(config).toContain('trace: useExternalAcceptanceStack ? "on" : "on-first-retry"');
    expect(config).toContain('const externalAcceptanceReportPath = path.join(');
    expect(config).toContain('["json", { outputFile: externalAcceptanceReportPath }]');
  });

  it("keeps every secondary notification role context on the configured acceptance stack", () => {
    const spec = readFileSync(
      resolve(process.cwd(), "e2e", "security-notifications.spec.ts"),
      "utf-8",
    );

    expect(spec).not.toContain("http://127.0.0.1:5173");
    expect(spec).toContain("const acceptanceBaseUrl = new URL(page.url()).origin;");
    expect(spec).toContain(
      "const viewerContext = await browser.newContext({ baseURL: acceptanceBaseUrl });",
    );
    expect(spec).toContain(
      "const outsiderContext = await browser.newContext({ baseURL: acceptanceBaseUrl });",
    );
  });
});
