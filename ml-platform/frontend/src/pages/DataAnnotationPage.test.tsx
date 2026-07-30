import { App as AntApp } from "antd";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DataAnnotationPage from "./DataAnnotationPage";

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("../components/AppLayout", () => ({ default: ({ children }: any) => <>{children}</> }));
vi.mock("../api/client", () => ({ default: { get } }));

describe("DataAnnotationPage", () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ data: { items: [] } });
  });

  it("shows the independent annotation workspace before a quality run exists", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AntApp><DataAnnotationPage /></AntApp>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "数据标注" })).toBeInTheDocument();
    expect(screen.getByLabelText("Project")).toBeInTheDocument();
    expect(screen.getByText("样本队列")).toBeInTheDocument();
    expect(screen.getByText("四通道波形")).toBeInTheDocument();
    expect(screen.getByText("标注与审核")).toBeInTheDocument();
  });
});
