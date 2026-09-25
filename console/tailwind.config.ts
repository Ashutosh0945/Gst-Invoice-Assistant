import type { Config } from "tailwindcss";

// Soft-UI (neumorphic) dark theme. Every surface is the same navy family;
// depth comes from paired light/dark shadows rather than borders.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: { DEFAULT: "#1E1D35", deep: "#1A1930", raised: "#22213C", line: "#2C2B48" },
        ink: { DEFAULT: "#ECECF4", soft: "#A9A8C3", faint: "#6F6E8C" },
        accent: { DEFAULT: "rgb(var(--accent) / <alpha-value>)", soft: "rgb(var(--accent-soft) / <alpha-value>)" },
        good: "#4ADE80",
        warn: "#F5A524",
        bad: "#F87171",
        info: "#60A5FA",
      },
      fontFamily: { sans: ["\"Plus Jakarta Sans Variable\"", "system-ui", "sans-serif"] },
      boxShadow: {
        neu: "8px 8px 18px #141327, -6px -6px 16px #28274A",
        "neu-sm": "4px 4px 10px #141327, -3px -3px 8px #28274A",
        "neu-in": "inset 4px 4px 9px #141327, inset -3px -3px 8px #28274A",
        glow: "0 6px 20px rgb(var(--accent) / 0.35)",
      },
      borderRadius: { xl2: "1.25rem" },
    },
  },
  plugins: [],
};
export default config;
