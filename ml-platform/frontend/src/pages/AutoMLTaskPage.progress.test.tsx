import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AutoMLTaskPage from "./AutoMLTaskPage";

const getJob = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ taskId: "job-1" }),
}));
vi.mock("../api/client", () => ({
  default: { get: getJob, post: vi.fn() },
  formatApiError: (_error: unknown, fallback: string) => fallback,
}));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

describe("AutoMLTaskPage progress polling", () => {
  beforeEach(() => {
    vi.useRealTimers();
    getJob.mockReset();
    getJob
      .mockResolvedValueOnce({
        data: {
          status: "running",
          metrics: { progress: { completed: 1, total: 20, percent: 5 } },
        },
      })
      .mockResolvedValue({
        data: {
          status: "running",
          metrics: { progress: { completed: 2, total: 20, percent: 10 } },
        },
      });
  });

  it("refreshes progress while the lifecycle status remains running", async () => {
    render(<AutoMLTaskPage />);
    await waitFor(() => expect(screen.getByText("已完成试验 1 / 20")).toBeInTheDocument());

    await new Promise((resolve) => setTimeout(resolve, 2200));

    await waitFor(() => expect(screen.getByText("已完成试验 2 / 20")).toBeInTheDocument());
    expect(getJob.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
