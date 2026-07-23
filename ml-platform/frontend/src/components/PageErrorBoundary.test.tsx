import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PageErrorBoundary from "./PageErrorBoundary";

function BrokenPage(): never {
  throw new Error("chunk failed");
}

describe("PageErrorBoundary", () => {
  afterEach(() => vi.restoreAllMocks());

  it("keeps a page failure recoverable instead of rendering a blank screen", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const suppressJSDOMError = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", suppressJSDOMError);
    render(
      <PageErrorBoundary pageName="AutoML">
        <BrokenPage />
      </PageErrorBoundary>,
    );

    expect(screen.getByText("AutoML 暂时无法加载")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
    window.removeEventListener("error", suppressJSDOMError);
  });
});
