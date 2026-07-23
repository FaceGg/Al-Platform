import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider, useTheme } from "./themeContext";

function ThemeProbe() {
  const { theme, toggleTheme } = useTheme();

  return (
    <button type="button" onClick={toggleTheme}>
      {theme}
    </button>
  );
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("synchronizes the active theme to the document root", () => {
    render(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>
    );

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    fireEvent.click(screen.getByRole("button", { name: "dark" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(localStorage.getItem("theme")).toBe("light");
  });
});
