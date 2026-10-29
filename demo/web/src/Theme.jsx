import { useEffect, useState } from "react";

// Light or dark: the system's choice until the switch is used, then the user's, kept in this browser.
// styles.css reads it from data-theme on <html>.
const KEY = "corax.theme";

export function storedTheme() {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
}

const systemTheme = () => window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

// The switch in the bottom right corner of every page
export function ThemeSwitch() {
  const [theme, setTheme] = useState(() => storedTheme() || systemTheme());
  useEffect(() => { applyTheme(theme); }, [theme]);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    try { localStorage.setItem(KEY, next); } catch { /* not kept: this tab only */ }
    setTheme(next);
  }

  const dark = theme === "dark";
  return (
    <button type="button" onClick={toggle} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} title={dark ? "Light mode" : "Dark mode"}
            className="fixed bottom-4 right-4 z-30 grid size-11 cursor-pointer place-items-center rounded-full border border-line bg-panel text-ink shadow-card transition hover:border-accent hover:text-accent">
      {dark ? (
        <svg viewBox="0 0 24 24" aria-hidden="true" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <circle cx="12" cy="12" r="4.5" />
          <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" aria-hidden="true" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round">
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />
        </svg>
      )}
    </button>
  );
}
