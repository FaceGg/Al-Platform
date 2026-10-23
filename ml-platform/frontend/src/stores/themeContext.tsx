import { createContext, useContext, useState, useMemo, useEffect } from "react";

export type Theme = "light" | "dark";

interface ThemeCtx {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (t: Theme) => void;
}

const ThemeContext = createContext<ThemeCtx>({
  theme: "light",
  toggleTheme: () => {},
  setTheme: () => {},
});

export function ThemeProvider({ children }: { children: any }) {
  // 默认明亮主题；仅在用户显式切换过（localStorage 有合法值）时沿用其选择
  const [theme, setThemeState] = useState<Theme>(() => {
    const saved = localStorage.getItem("theme") as Theme;
    return saved === "light" || saved === "dark" ? saved : "light";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const ctx = useMemo<ThemeCtx>(
    () => ({
      theme,
      toggleTheme: () => {
        const next = theme === "dark" ? "light" : "dark";
        setThemeState(next);
        localStorage.setItem("theme", next);
      },
      setTheme: (t) => {
        setThemeState(t);
        localStorage.setItem("theme", t);
      },
    }),
    [theme]
  );

  return <ThemeContext.Provider value={ctx}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);
