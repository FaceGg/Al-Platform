import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TemplateWizardPage from "./TemplateWizardPage";

const navigate = vi.fn();
const getTemplate = vi.fn();
const instantiateTemplate = vi.fn();
const get = vi.fn();
const post = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useParams: () => ({ templateId: "weld_quality" }),
    useSearchParams: () => [new URLSearchParams("project=project-1")],
    useNavigate: () => navigate,
  };
});
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../i18n", () => ({
  useI18n: () => ({
    lang: "en",
    t: {
      common: { error: "Error" },
      template: {
        wizard_title: "Industrial workflow template",
        scenario: "Scenario",
        target: "Target",
        required_columns: "Required columns",
        project: "Project",
        dataset_artifact: "Dataset artifact",
        parameter_config: "Parameter configuration",
        create_project: "Create project",
        use_existing_project: "Use existing project",
        project_name: "Project name",
        project_description: "Project description",
        create_workflow: "Create workflow",
        load_failed: "Unable to load template",
        create_failed: "Unable to create workflow",
        no_datasets: "No dataset artifacts",
      },
    },
  }),
}));
vi.mock("../api/templates", () => ({
  getTemplate: (...args: unknown[]) => getTemplate(...args),
  instantiateTemplate: (...args: unknown[]) => instantiateTemplate(...args),
}));
vi.mock("../api/client", () => ({
  default: { get: (...args: unknown[]) => get(...args), post: (...args: unknown[]) => post(...args) },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));

describe("TemplateWizardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getTemplate.mockResolvedValue({
      id: "weld_quality",
      name: "Weld quality",
      description: "Predict Fault from welding features",
      scenario: "Fault classification",
      task_type: "classification",
      target_column: "Fault",
      required_columns: ["Car Body", "Welding Spot", "Date", "Fault"],
      parameters: [{ key: "n_estimators", label: "Tree count", type: "int", default: 100, required: false }],
    });
    get.mockImplementation((url: string) => {
      if (url === "/projects") return Promise.resolve({ data: { items: [{ id: "project-1", name: "Welding" }] } });
      if (url === "/projects/project-1/datasets") {
        return Promise.resolve({ data: { items: [{ artifact_id: "artifact-1", name: "weld.csv", row_count: 316 }] } });
      }
      if (url === "/projects/project-2/datasets") return Promise.resolve({ data: { items: [] } });
      return Promise.reject(new Error(`Unexpected URL ${url}`));
    });
    instantiateTemplate.mockResolvedValue({ workflow_id: "workflow-1" });
    post.mockResolvedValue({ data: { id: "project-2", name: "New welding project" } });
  });

  it("selects a project dataset and submits semantic parameters", async () => {
    render(<TemplateWizardPage />);

    expect(await screen.findByText("Weld quality")).toBeInTheDocument();
    expect(screen.getByText("Fault classification")).toBeInTheDocument();
    expect(screen.getAllByText("Fault")).toHaveLength(2);
    expect(screen.getByText(/Car Body/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/file path/i)).not.toBeInTheDocument();

    fireEvent.mouseDown(screen.getByLabelText("Dataset artifact"));
    fireEvent.click(await screen.findByText(/weld.csv/));
    fireEvent.change(screen.getByLabelText(/Tree count/), { target: { value: "80" } });
    fireEvent.click(screen.getByRole("button", { name: "Create workflow" }));

    await waitFor(() => expect(instantiateTemplate).toHaveBeenCalledWith("weld_quality", {
      project_id: "project-1",
      dataset_artifact_id: "artifact-1",
      parameters: { n_estimators: 80 },
    }));
    expect(navigate).toHaveBeenCalledWith("/workspace/workflow-1");
  });

  it("creates a project before selecting its dataset", async () => {
    render(<TemplateWizardPage />);
    await screen.findByText("Weld quality");

    fireEvent.click(screen.getByRole("button", { name: /Create project/ }));
    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "New welding project" } });
    fireEvent.click(screen.getByRole("button", { name: /Create project/ }));

    await waitFor(() => expect(post).toHaveBeenCalledWith("/projects", {
      name: "New welding project",
      description: "",
    }));
    expect(get).toHaveBeenCalledWith("/projects/project-2/datasets");
  });
});
