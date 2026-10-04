import type { Config } from "tailwindcss";

// Soft-UI (neumorphic) theme with Dark / Light / System modes. Every colour and shadow is a
// CSS variable (theme token) defined once in app/globals.css, so all pages switch together.
const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: { DEFAULT: "rgb(var(--c-base) / <alpha-value>)", deep: "rgb(var(--c-base-deep) / <alpha-value>)",
                raised: "rgb(var(--c-base-raised) / <alpha-value>)", line: "rgb(var(--c-line) / <alpha-value>)" },
        ink: { DEFAULT: "rgb(var(--c-ink) / <alpha-value>)", strong: "rgb(var(--c-ink-strong) / <alpha-value>)",
               soft: "rgb(var(--c-ink-soft) / <alpha-value>)", faint: "rgb(var(--c-ink-faint) / <alpha-value>)" },
        accent: { DEFAULT: "rgb(var(--c-accent) / <alpha-value>)", soft: "rgb(var(--c-accent-soft) / <alpha-value>)",
                  deep: "rgb(var(--c-accent-deep) / <alpha-value>)" },
        good: "rgb(var(--c-good) / <alpha-value>)",
        warn: "rgb(var(--c-warn) / <alpha-value>)",
        bad: "rgb(var(--c-bad) / <alpha-value>)",
        info: "rgb(var(--c-info) / <alpha-value>)",
      },
      fontFamily: { sans: ["\"Plus Jakarta Sans Variable\"", "system-ui", "sans-serif"] },
      boxShadow: {
        neu: "8px 8px 18px rgb(var(--sh-dark)), -6px -6px 16px rgb(var(--sh-light))",
        "neu-sm": "4px 4px 10px rgb(var(--sh-dark)), -3px -3px 8px rgb(var(--sh-light))",
        "neu-in": "inset 4px 4px 9px rgb(var(--sh-dark)), inset -3px -3px 8px rgb(var(--sh-light))",
        glow: "0 6px 20px rgb(var(--c-accent) / 0.35)",
      },
      borderRadius: { xl2: "1.25rem" },
    },
  },
  plugins: [],
};
export default config;
