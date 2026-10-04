"use client";

import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

type Mode = "light" | "dark" | "system";
const KEY = "gstdesk-theme";

export function applyTheme(mode: Mode) {
  const dark = mode === "dark" || (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

/** Runs before the page paints (see app/layout.tsx) so there's no flash of the wrong theme. */
export const themeBootScript = `(function(){try{var m=localStorage.getItem("${KEY}")||"system";var d=m==="dark"||(m==="system"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.theme=d?"dark":"light";}catch(e){document.documentElement.dataset.theme="dark";}})();`;

export function ThemeToggle() {
  const [mode, setMode] = useState<Mode>("system");
  useEffect(() => {
    const saved = (localStorage.getItem(KEY) as Mode) || "system";
    setMode(saved);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => { if ((localStorage.getItem(KEY) || "system") === "system") applyTheme("system"); };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  const choose = (m: Mode) => {
    setMode(m);
    try { localStorage.setItem(KEY, m); } catch { /* private mode */ }
    applyTheme(m);
  };
  const opts: Array<[Mode, typeof Sun, string]> = [["light", Sun, "Light"], ["dark", Moon, "Dark"], ["system", Monitor, "System"]];
  return (
    <div role="radiogroup" aria-label="Colour theme" className="hidden sm:flex items-center gap-1 p-1 rounded-xl bg-base-deep shadow-neu-in">
      {opts.map(([m, Icon, label]) => (
        <button key={m} role="radio" aria-checked={mode === m} title={`${label} theme`} onClick={() => choose(m)}
          className={`w-9 h-9 grid place-items-center rounded-lg transition ${mode === m ? "bg-base shadow-neu-sm text-accent-soft" : "text-ink-faint hover:text-ink-strong"}`}>
          <Icon className="w-4 h-4" aria-hidden /><span className="sr-only">{label}</span>
        </button>
      ))}
    </div>
  );
}
