import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import APIMarketplacePage from "./APIMarketplacePage";

const apiGet = vi.hoisted(() => vi.fn());
const apiDelete = vi.hoisted(() => vi.fn());

vi.mock("../api/client", () => ({ apiGet, apiDelete }));
vi.mock("../components/AppLayout", () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("../i18n", () => ({ useI18n: () => ({ t: { api_market: { title: "API 市场", detail: "详情", test: "测试", model_api: "模型 API", custom: "自定义", copy: "复制", history: "历史" }, ai_chat: { send: "发送" } } }) }));

describe("APIMarketplacePage", () => {
  beforeEach(() => {
    apiGet.mockResolvedValue({ items: [] });
    apiDelete.mockResolvedValue({});
  });

  it("loads APIs through the client-relative platform endpoint", async () => {
    render(<MemoryRouter><APIMarketplacePage /></MemoryRouter>);
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/platform/apis"));
    expect(screen.getByText("API 市场")).toBeInTheDocument();
  });
});
