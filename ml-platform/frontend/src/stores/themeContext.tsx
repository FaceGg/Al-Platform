import { createContext, useContext, useState, useMemo, useEffect } from "react";

export type Theme = "light" | "dark";

interface ThemeCtx {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (t: Theme) => void;
}

const ThemeContext = createContext<ThemeCtx>({
  theme: "dark",
  toggleTheme: () => {},
  setTheme: () => {},
});

export function ThemeProvider({ children }: { children: any }) {
  const [theme, setThemeState] = useState<Theme>("dark");

  useEffect(() => {
    const saved = localStorage.getItem("theme") as Theme;
    if (saved === "light" || saved === "dark") {
      setThemeState(saved);
    }
  }, []);

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