import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SystemSettingsPage from "./SystemSettingsPage";

const apiGet = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ default: { get: apiGet } }));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));

const readiness = {
  ready: true,
  database: { ready: true, code: "OK" },
  redis: { ready: true, code: "OK" },
  celery: { ready: true, code: "OK" },
  storage: { ready: true, code: "OK" },
  mlflow: { ready: false, code: "SERVICE_UNAVAILABLE" },
  tensorboard: { ready: true, code: "OK" },
  inference_runtime: { ready: true, code: "OK" },
  notification_crypto_configured: true,
  notification_worker_registered: false,
  migration_head: "20261026_83",
};

describe("SystemSettingsPage", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiGet.mockImplementation((url: string) => {
      if (url === "/ready") return Promise.resolve({ data: readiness });
      if (url === "/llm-profiles") {
        return Promise.resolve({ data: [
          { id: "p1", model_id: "deepseek-chat", is_default: true },
        ] });
      }
      return Promise.resolve({ data: {} });
    });
  });

  it("renders the component health matrix from /api/ready", async () => {
    render(<MemoryRouter><SystemSettingsPage /></MemoryRouter>);

    expect(await screen.findByText("组件健康")).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/ready");
    expect(screen.getByText("数据库")).toBeInTheDocument();
    // MLflow is marked not-ready in the fixture and must surface as an error badge.
    expect(screen.getByText("异常")).toBeInTheDocument();
    expect(screen.getByText("SERVICE_UNAVAILABLE")).toBeInTheDocument();
  });

  it("shows migration head and LLM profile state from real endpoints", async () => {
    render(<MemoryRouter><SystemSettingsPage /></MemoryRouter>);

    expect(await screen.findByText("20261026_83")).toBeInTheDocument();
    expect(await screen.findByText(/deepseek-chat/)).toBeInTheDocument();
    expect(apiGet).toHaveBeenCalledWith("/llm-profiles");
    // The dead /readiness and /config/public calls are gone.
    expect(apiGet.mock.calls.every(([url]: [string]) => url !== "/readiness" && url !== "/config/public")).toBe(true);
  });
});
