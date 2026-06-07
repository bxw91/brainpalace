import type { Config } from "tailwindcss";

/**
 * BrainPalace control-plane theme.
 *
 * Aesthetic: an observability / control-plane console. Deep near-black slate
 * canvas, a single cool teal accent for primary actions, semantic status hues
 * (emerald = running, amber = unhealthy, slate = stopped, rose = stale/error).
 * Strict 8px spatial grid. Distinctive geometric display + grotesque body —
 * NOT the generic Inter/Roboto look.
 */
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Canvas + surfaces (cool near-black, layered).
        ink: {
          900: "#070b10",
          800: "#0b1118",
          700: "#101822",
          600: "#16212e",
          500: "#1d2c3c",
          400: "#27384b",
        },
        // Hairlines / borders.
        line: {
          DEFAULT: "#1e2c3a",
          strong: "#2c4054",
        },
        // Primary accent — cool teal.
        accent: {
          DEFAULT: "#2dd4bf",
          soft: "#5eead4",
          deep: "#0f766e",
          glow: "#14b8a6",
        },
        // Text ramp.
        fg: {
          DEFAULT: "#e6edf3",
          muted: "#9bb0c3",
          // Lightened from #5f7488 to clear WCAG AA 4.5:1 on every panel surface
          // (≥5.06:1 even against the lightest ink-500/600 fills).
          faint: "#7d92a6",
        },
        // Semantic status.
        run: "#34d399",
        warn: "#fbbf24",
        idle: "#64748b",
        bad: "#fb7185",
      },
      fontFamily: {
        display: [
          '"Space Grotesk Local"',
          '"Sora"',
          '"Geist"',
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        sans: [
          '"Hanken Grotesk"',
          '"IBM Plex Sans"',
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          '"JetBrains Mono"',
          '"IBM Plex Mono"',
          "ui-monospace",
          "SFMono-Regular",
          "monospace",
        ],
      },
      spacing: {
        // explicit 8px-grid helpers
        18: "4.5rem",
        22: "5.5rem",
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.125rem",
      },
      boxShadow: {
        panel:
          "0 1px 0 0 rgba(255,255,255,0.02) inset, 0 24px 48px -24px rgba(0,0,0,0.65)",
        glow: "0 0 0 1px rgba(45,212,191,0.35), 0 8px 28px -8px rgba(45,212,191,0.35)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-dot": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.4s cubic-bezier(0.22,1,0.36,1) both",
        "pulse-dot": "pulse-dot 1.8s ease-in-out infinite",
        shimmer: "shimmer 1.4s infinite",
      },
    },
  },
  plugins: [],
};

export default config;
