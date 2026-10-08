import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "light" | "dark";

const ThemeContext = createContext<{
  theme: Theme;
  toggle: () => void;
  setTheme: (theme: Theme) => void;
}>({
  theme: "dark",
  toggle: () => {},
  setTheme: () => {},
});

function initialTheme(): Theme {
  const stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Apply the theme to <html> *before* anything renders against it. */
function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // The class must be on <html> before children render, not after they commit:
  // `usePalette` resolves the CSS colour tokens with getComputedStyle *during*
  // render, so if the class lagged by one commit it would read the outgoing
  // theme's palette and cache it. Setting it in the lazy initialiser and in the
  // toggle keeps the DOM and the React state in the same tick.
  const [theme, setThemeState] = useState<Theme>(() => {
    const t = initialTheme();
    applyTheme(t);
    return t;
  });

  useEffect(() => {
    applyTheme(theme); // keeps the DOM honest if `theme` ever changes elsewhere
    localStorage.setItem("theme", theme);
  }, [theme]);

  const setTheme = (next: Theme) => {
    applyTheme(next); // before setState, so the re-render reads the new tokens
    setThemeState(next);
  };
  const toggle = () => setTheme(theme === "dark" ? "light" : "dark");

  return (
    <ThemeContext.Provider value={{ theme, toggle, setTheme }}>{children}</ThemeContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export const useTheme = () => useContext(ThemeContext);
