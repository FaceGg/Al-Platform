import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ComputeResourcePage from "./ComputeResourcePage";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => mocks);

function makeNode(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "n1",
    name: "GPU-Node-01",
    node_number: "N001",
    ip_address: "192.168.1.100",
    node_type: "gpu",
    status: "online",
    purpose: "training",
    cpu_cores: 32,
    gpu_count: 4,
    memory_gb: 256,
    disk_gb: 2000,
    current_load: 40,
    tags: [],
    last_heartbeat: new Date().toISOString(),
    heartbeat_stale: false,
    ...overrides,
  };
}

function makeDevice(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "d1",
    name: "Edge-Box-01",
    group_id: "factory-1",
    ip_address: "10.0.0.50",
    device_type: "box",
    status: "online",
    model_deployed: "weld_quality_v1",
    version: "v2",
    last_heartbeat: null,
    heartbeat_stale: true,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.apiGet.mockImplementation((url: string) => {
    if (url.startsWith("/compute/nodes")) return Promise.resolve({ items: [makeNode()], total: 1 });
    if (url === "/compute/devices") return Promise.resolve({ items: [makeDevice()], total: 1 });
    return Promise.reject(new Error(`Unexpected URL: ${url}`));
  });
  mocks.apiPost.mockResolvedValue({});
  mocks.apiPut.mockResolvedValue({});
  mocks.apiDelete.mockResolvedValue({});
});

function renderPage() {
  return render(<ComputeResourcePage />);
}

describe("ComputeResourcePage", () => {
  it("renders compute nodes with heartbeat state", async () => {
    renderPage();
    expect(await screen.findByText("GPU-Node-01")).toBeInTheDocument();
    expect(screen.getByText("心跳正常")).toBeInTheDocument();
    expect(screen.getByText("192.168.1.100")).toBeInTheDocument();
  });

  it("flags nodes whose heartbeat went stale", async () => {
    mocks.apiGet.mockImplementation((url: string) => {
      if (url.startsWith("/compute/nodes")) {
        return Promise.resolve({ items: [makeNode({ last_heartbeat: null, heartbeat_stale: true })], total: 1 });
      }
      if (url === "/compute/devices") return Promise.resolve({ items: [], total: 0 });
      return Promise.reject(new Error(`Unexpected URL: ${url}`));
    });
    renderPage();
    expect(await screen.findByText("从未上报")).toBeInTheDocument();
  });

  it("lists edge devices under the devices tab with runtime info", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "边缘设备" }));
    expect(await screen.findByText("Edge-Box-01")).toBeInTheDocument();
    expect(screen.getByText("weld_quality_v1")).toBeInTheDocument();
    expect(screen.getByText("从未上报")).toBeInTheDocument();
  });

  it("re-queries nodes with the selected status filter", async () => {
    renderPage();
    await screen.findByText("GPU-Node-01");
    mocks.apiGet.mockClear();
    fireEvent.mouseDown(screen.getByText("按状态筛选"));
    fireEvent.click(await screen.findByText("在线", { selector: ".ant-select-item-option-content" }));
    await waitFor(() =>
      expect(mocks.apiGet).toHaveBeenCalledWith("/compute/nodes?status=online"),
    );
  });

  it("reports a node heartbeat through the heartbeat endpoint", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /上报心跳/ }));
    await waitFor(() =>
      expect(mocks.apiPost).toHaveBeenCalledWith("/compute/nodes/n1/heartbeat", {}),
    );
  });

  it("reports a device heartbeat through the heartbeat endpoint", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "边缘设备" }));
    fireEvent.click(await screen.findByRole("button", { name: /上报心跳/ }));
    await waitFor(() =>
      expect(mocks.apiPost).toHaveBeenCalledWith("/compute/devices/d1/heartbeat", {}),
    );
  });

  it("creates an edge device through the device modal", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("tab", { name: "边缘设备" }));
    fireEvent.click(await screen.findByRole("button", { name: /新增设备/ }));
    fireEvent.change(screen.getByLabelText("设备名称"), { target: { value: "Edge-Box-02" } });
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() =>
      expect(mocks.apiPost).toHaveBeenCalledWith("/compute/devices", expect.objectContaining({
        name: "Edge-Box-02",
        status: "online",
      })),
    );
  });

  it("deletes a compute node after confirmation", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /删\s*除/ }));
    fireEvent.click(await screen.findByRole("button", { name: "OK" }));
    await waitFor(() => expect(mocks.apiDelete).toHaveBeenCalledWith("/compute/nodes/n1"));
  });
});
